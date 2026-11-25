"""P6 T4: the full flow works with the internet cut, in ``light`` mode.

Given ``egress`` disconnected and the stack in ``light`` mode, when a lecteur uploads a private
document and asks a question it answers, then the answer cites that document and has no web source
(the web lookups end ``skipped``).

Runs against the live compose, from inside the ``api`` container (nothing is published on the
host). It disconnects ``web-search`` and ``searxng`` from ``egress`` for the duration of the test
and always reconnects them. Skipped only when the stack is not up in ``light`` mode, or when there
is no upload route (404, 405 or 501): any other error fails the test.

    make up-light   (or: MODE=light docker compose up -d --wait)
    pytest tests/sovereignty/test_offline_flow.py -v
"""

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EGRESS_SERVICES = ("web-search", "searxng")

DOCUMENT = (
    "Article 1. Le délai de recours contre une décision de la commission T4 est de dix-sept jours "
    "à compter de sa notification.\n"
    "Article 2. Le recours est déposé auprès du secrétariat de la commission T4.\n"
)
QUESTION = "Quel est le délai de recours contre une décision de la commission T4 ?"

# Runs inside `api`: the bootstrap admin creates a new lecteur, who uploads DOCUMENT (no roles: a
# private upload), waits until it is ready and asks QUESTION. Prints one JSON line with what
# happened. Credentials come from the container's env, or are made up here, and never leave it.
FLOW_SCRIPT = r"""
import json, os, secrets, sys, time
import httpx

args = json.loads(sys.stdin.readline())
out = {"step": "admin login"}


def ok(r):
    if r.status_code >= 400:
        raise RuntimeError(f"{r.request.method} {r.request.url.path} -> {r.status_code}")
    return r.json()


def login(c, username, password):
    body = ok(c.post("/auth/login", json={"username": username, "password": password}))
    return {"Authorization": "Bearer " + body["access_token"]}


def flow(c):
    admin = login(c, os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"])
    out["step"] = "create lecteur"
    role_id = next(
        r["role_id"] for r in ok(c.get("/admin/roles", headers=admin)) if r["name"] == "lecteur"
    )
    username, password = "t4-" + secrets.token_hex(4), secrets.token_hex(16)
    user = {"username": username, "password": password, "full_name": "T4", "role_id": role_id}
    ok(c.post("/admin/users", headers=admin, json=user))
    out["step"] = "lecteur login"
    h = login(c, username, password)

    out["step"] = "upload"
    file = ("t4.txt", args["document"].encode("utf-8"), "text/plain")
    r = c.post("/documents", headers=h, files={"file": file}, data={"title": "T4 offline"})
    if r.status_code in (404, 405, 501):
        out["skip"] = f"no upload route yet ({r.status_code})"
        return
    doc_id = out["doc_id"] = ok(r)["doc_id"]
    try:
        out["step"] = "ingest"
        deadline = time.monotonic() + args["timeout_s"]
        while True:
            status = ok(c.get(f"/documents/{doc_id}/status", headers=h))
            if status["status"] == "ready":
                break
            if status["status"] == "failed" or time.monotonic() > deadline:
                raise RuntimeError(f"document not ready: {status}")
            time.sleep(2)
        out["step"] = "ask"
        events, name = [], None
        body = {"question": args["question"], "use_web": True}
        with c.stream("POST", "/ask", headers=h, json=body) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"POST /ask -> {r.status_code}")
            for line in r.iter_lines():
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and name:
                    events.append({"event": name, "data": json.loads(line.split(":", 1)[1])})
                    name = None
        out["events"] = [e for e in events if e["event"] != "thinking"]
        out["step"] = "done"
    finally:
        # 409 while the document is being processed. There is no route to delete the user.
        for _ in range(15):
            out["delete_status"] = c.delete(f"/documents/{doc_id}", headers=h).status_code
            if out["delete_status"] != 409:
                break
            time.sleep(2)


try:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=args["timeout_s"]) as client:
        flow(client)
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(out, ensure_ascii=False))
"""


def _compose(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _running_services() -> set[str]:
    if shutil.which("docker") is None:
        return set()
    try:
        result = _compose("ps", "--status", "running", "--services", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(result.stdout.split()) if result.returncode == 0 else set()


def _egress_network() -> str:
    project = _compose("config", "--format", "json", timeout=30)
    name = json.loads(project.stdout)["networks"]["egress"]["name"]
    return str(name)


def _container(service: str) -> str:
    return _compose("ps", "-q", service, timeout=30).stdout.strip()


@pytest.fixture
def offline() -> Iterator[None]:
    """`web-search` and `searxng` cut from `egress` for the test, then always reconnected."""
    needed = {"api", "llm", "models", "web-search", "searxng"}
    missing = needed - _running_services()
    if missing:
        pytest.skip(f"stack not up ({', '.join(sorted(missing))} missing): run `make up-light`")
    mode = _compose("exec", "-T", "api", "printenv", "MODE", timeout=30).stdout.strip()
    if mode != "light":
        pytest.skip(f"stack is in mode {mode or '?'}; T4 runs in light mode (`make up-light`)")

    network = _egress_network()
    containers = {service: _container(service) for service in EGRESS_SERVICES}
    cut: list[str] = []
    try:
        for service, container in containers.items():
            subprocess.run(["docker", "network", "disconnect", network, container], check=True)
            cut.append(service)
        yield
    finally:
        # --alias: without it the service name (`searxng`) no longer resolves after the test.
        results = [
            subprocess.run(
                ["docker", "network", "connect", "--alias", service, network, containers[service]],
                check=False,
            )
            for service in cut
        ]
        assert all(r.returncode == 0 for r in results), f"egress not restored for {cut}"


def _run_flow(timeout_s: int = 300) -> dict[str, Any]:
    args = {"document": DOCUMENT, "question": QUESTION, "timeout_s": timeout_s}
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", FLOW_SCRIPT],
        cwd=REPO_ROOT,
        input=json.dumps(args) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_s * 3,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert lines, f"the flow printed nothing (exit {result.returncode}): {result.stderr[-2000:]}"
    return dict(json.loads(lines[-1]))


def test_t4_full_flow_answers_with_a_citation_and_no_web_offline(offline: None) -> None:
    flow = _run_flow()
    if "skip" in flow:
        pytest.skip(flow["skip"])
    assert "error" not in flow, f"failed at step {flow['step']}: {flow['error']}"
    assert flow["delete_status"] == 204, f"document not deleted: {flow['delete_status']}"

    names = [e["event"] for e in flow["events"]]
    assert names[-1] == "done", names
    answers = [e["data"] for e in flow["events"] if e["event"] == "answer"]
    assert len(answers) == 1, f"no answer, events: {flow['events']}"
    answer = answers[0]

    assert answer["status"] == "answered", answer
    cited = {c["doc_id"] for c in answer["citations"]}
    assert flow["doc_id"] in cited, f"the uploaded document is not cited: {answer['citations']}"
    web = [c for c in answer["citations"] if c.get("url")]
    assert not web, f"web sources while offline (lookups should be skipped): {web}"
