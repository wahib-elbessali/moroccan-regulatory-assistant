"""P6 T4: the full flow works with the internet cut, in ``light`` mode.

Given ``egress`` disconnected and the stack in ``light`` mode, when a user uploads a document and
asks a question it answers, then the answer cites that document and has no web source (the web
lookups end ``skipped``).

Runs against the live compose, from inside the ``api`` container (nothing is published on the
host). It disconnects ``web-search`` and ``searxng`` from ``egress`` for the duration of the test
and always reconnects them. Skipped, with the reason, until every piece is there: the stack up in
``light`` mode, the real api serving (not the dev placeholder), and a real upload route.

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

# Runs inside `api`: logs in as the bootstrap admin, uploads DOCUMENT, waits until it is ready,
# asks QUESTION and prints one JSON line with what happened. Credentials come from the
# container's env and never leave it.
FLOW_SCRIPT = r"""
import json, os, sys, time
import httpx

args = json.loads(sys.stdin.readline())
out = {"step": "start"}
try:
    with httpx.Client(base_url=args.get("base_url", "http://127.0.0.1:8000"), timeout=args["timeout_s"]) as c:
        out["step"] = "openapi"
        if c.get("/openapi.json").status_code != 200:
            raise SystemExit(print(json.dumps({"skip": "api is the dev placeholder, not the real api"})))
        out["step"] = "login"
        r = c.post("/auth/login", json={"username": os.environ["ADMIN_USERNAME"],
                                        "password": os.environ["ADMIN_PASSWORD"]})
        r.raise_for_status()
        h = {"Authorization": "Bearer " + r.json()["access_token"]}
        out["step"] = "upload"
        r = c.post("/documents", headers=h,
                   files={"file": ("t4.txt", args["document"].encode("utf-8"), "text/plain")},
                   data={"title": "T4 offline", "roles": ["admin", "editeur", "lecteur"]})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or not body.get("doc_id"):
            raise SystemExit(print(json.dumps({"skip": f"upload is not real yet ({r.status_code} {body})"})))
        doc_id = out["doc_id"] = body["doc_id"]
        out["step"] = "ingest"
        deadline = time.monotonic() + args["timeout_s"]
        while True:
            status = c.get(f"/documents/{doc_id}/status", headers=h).json()
            if status.get("status") == "ready":
                break
            if status.get("status") == "failed" or time.monotonic() > deadline:
                raise RuntimeError(f"document not ready: {status}")
            time.sleep(2)
        out["step"] = "ask"
        events = []
        with c.stream("POST", "/ask", headers=h,
                      json={"question": args["question"], "use_web": True}) as r:
            r.raise_for_status()
            name = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and name:
                    events.append({"event": name, "data": json.loads(line.split(":", 1)[1])})
                    name = None
        out["events"] = [e for e in events if e["event"] != "thinking"]
        out["step"] = "cleanup"
        c.delete(f"/documents/{doc_id}", headers=h)
        out["step"] = "done"
except SystemExit:
    raise
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
    containers = [_container(s) for s in EGRESS_SERVICES]
    for container in containers:
        subprocess.run(["docker", "network", "disconnect", network, container], check=True)
    try:
        yield
    finally:
        for container in containers:
            subprocess.run(["docker", "network", "connect", network, container], check=False)


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
