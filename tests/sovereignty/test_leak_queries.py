"""P6 leak-query tests T5 and T6 (mandatory test b), on ``tests/sovereignty/leak_queries.jsonl``.

The file checks always run (also in CI). The ``/search`` checks run against the live compose,
after ``make seed`` has registered the corpus in ``web-search``: every query is sent from inside
the ``api`` container, since ``web-search`` has no published port. When the compose is not up,
they are skipped.

    make up && make seed
    pytest tests/sovereignty/test_leak_queries.py -v
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
QUERIES_FILE = Path(__file__).with_name("leak_queries.jsonl")
CONFIG_FILE = REPO_ROOT / "config.yaml"

EXPECTED = {"blocked", "allowed"}
MIN_PER_KIND = 25  # the spec asks for ~30 of each (T5, T6)
NGRAM_WORDS = 4  # a query shorter than one 4-gram can never be blocked

# Sends every query to web-search /search from inside api and prints one result per query.
# Reads the queries as JSON on its first stdin line; the token comes from the container's env.
SEND_SCRIPT = """
import json, os, sys, uuid
import httpx

queries = json.loads(sys.stdin.readline())
url = os.environ.get("WEB_SEARCH_URL", "http://web-search:8090") + "/search"
headers = {"Authorization": "Bearer " + os.environ["LEAK_API_TOKEN"]}
results = []
with httpx.Client(timeout=30) as client:
    for query in queries:
        body = {"query": query, "max_results": 1, "request_id": str(uuid.uuid4())}
        try:
            response = client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            results.append({"status": 0, "code": type(exc).__name__})
            continue
        try:
            code = response.json().get("code")
        except ValueError:
            code = None
        results.append({"status": response.status_code, "code": code})
print(json.dumps(results))
"""


def _load_queries() -> list[dict[str, Any]]:
    with QUERIES_FILE.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


QUERIES = _load_queries()


def _max_query_words() -> int:
    with CONFIG_FILE.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    return int(config["web"]["max_query_words"])


# --- The file itself (always runs) ------------------------------------------------------------


def test_every_row_has_the_spec_fields() -> None:
    """P6 spec §8: {"query", "expected": "blocked" | "allowed", "source_doc"}."""
    for row in QUERIES:
        assert set(row) == {"query", "expected", "source_doc"}, row
        assert row["expected"] in EXPECTED, row
        assert isinstance(row["query"], str) and row["query"].strip(), row


def test_there_are_about_thirty_queries_of_each_kind() -> None:
    kinds = [row["expected"] for row in QUERIES]
    assert kinds.count("blocked") >= MIN_PER_KIND
    assert kinds.count("allowed") >= MIN_PER_KIND


def test_queries_are_unique() -> None:
    queries = [row["query"] for row in QUERIES]
    assert len(queries) == len(set(queries))


def test_every_blocked_query_comes_from_a_protected_document() -> None:
    """A blocked query copies an internal document or a private upload, never public law."""
    for row in QUERIES:
        if row["expected"] == "blocked":
            assert row["source_doc"], row
            assert row["source_doc"].startswith(("internal/", "uploads/")), row


def test_every_query_fits_what_search_accepts() -> None:
    """/search refuses a query over web.max_query_words (422) before the leak filter sees it."""
    limit = _max_query_words()
    for row in QUERIES:
        words = len(row["query"].split())
        assert NGRAM_WORDS <= words <= limit, (words, row["query"])


# --- Through /search on the live compose (T5, T6) ---------------------------------------------


def _api_is_running() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and {"api", "web-search"} <= set(result.stdout.split())


def _outcome(result: dict[str, Any]) -> str:
    """What web-search did with one query."""
    if result["status"] == 403 and result["code"] == "leak_blocked":
        return "blocked"
    # 503: the query passed the leak filter, but SearxNG or the internet was unreachable.
    if result["status"] == 200 or (
        result["status"] == 503 and result["code"] == "search_unavailable"
    ):
        return "allowed"
    return f"error {result['status']} {result['code']}"


@pytest.fixture(scope="module")
def outcomes() -> list[str]:
    """One outcome per query in QUERIES, from a single run inside the api container."""
    if not _api_is_running():
        pytest.skip("api and web-search are not running (use `make up && make seed` first)")
    stdin = json.dumps([row["query"] for row in QUERIES], ensure_ascii=False) + "\n"
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", SEND_SCRIPT],
        cwd=REPO_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    results: list[dict[str, Any]] = json.loads(result.stdout.strip().splitlines()[-1])
    if any(r["status"] == 403 and r["code"] == "web_disabled" for r in results):
        pytest.skip("web.enabled is false in config.yaml")
    assert len(results) == len(QUERIES)
    return [_outcome(r) for r in results]


def _mismatches(outcomes: list[str], expected: str) -> list[str]:
    return [
        f"{outcome}: {row['source_doc']}"
        for row, outcome in zip(QUERIES, outcomes, strict=True)
        if row["expected"] == expected and outcome != expected
    ]


def test_t5_queries_copying_protected_documents_are_blocked(outcomes: list[str]) -> None:
    """T5 (mandatory test b). If none is blocked, check that `make seed` ran."""
    wrong = _mismatches(outcomes, "blocked")
    assert not wrong, f"{len(wrong)} queries not blocked:\n" + "\n".join(wrong)


def test_t6_legitimate_legal_queries_go_through(outcomes: list[str]) -> None:
    """T6."""
    wrong = _mismatches(outcomes, "allowed")
    assert not wrong, f"{len(wrong)} queries wrongly blocked:\n" + "\n".join(wrong)
