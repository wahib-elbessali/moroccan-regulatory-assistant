"""T23 (P2 spec §8): a question in French brings back the Arabic article that answers it.

This is the one P2 test that cannot be faked. Cross-language retrieval is a property of **bge-m3**
— a French question and an Arabic article get close vectors because the model was trained that
way — so a test with hash or word-overlap embeddings would prove nothing about it. T23 therefore
runs the real pipeline, on the real corpus, against P6's real ``models`` service.

Neither ``qdrant`` nor ``models`` publishes a port (``docker-compose.yml``: only ``gateway``
does), so the search runs **inside the ``api`` container**, which sits on the ``internal`` network
and mounts ``./src``. That is the convention ``tests/sovereignty/test_leak_queries.py`` already
uses for live-compose checks. When the compose is not up, or the corpus is not there, the tests
skip with what to run.

    make up && make seed
    # publish the law by hand once (see `corpus_hidden` below), or:
    #   P2_T23_PUBLISH=1 pytest tests/retrieval/test_t23_cross_language.py -v
    pytest tests/retrieval/test_t23_cross_language.py -v

The question and the expected articles are the ones from the manual run of Sat 11-21:
"Quelles sont les conditions de la kafala d'un enfant abandonné ?" returned
المادة 12, 9 and 17 of law 15.01. That run is **not** evidence for this test — it is only where
the expectation comes from.

Only ``contracts.models`` is forced to ``real`` (with ``registry.override``), because
``config.yaml`` still ships ``models: fake`` and P2 does not change shared configuration. The rest
is ``real_retrieval()`` itself: real Qdrant, real ``QdrantStore``, real ``BM25Index``.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.ingestion import normalize_ar

REPO_ROOT = Path(__file__).resolve().parents[2]

# The French question, asked exactly as a citizen would type it (P2-18: embedded as typed).
FRENCH_QUERY = "Quelles sont les conditions de la kafala d'un enfant abandonné ?"

# Law 15.01 on the kafala of abandoned children: data/raw/manifest.csv, visibility `public`.
SOURCE_FILE = "adala_005.pdf"
LAW_NUMBER = "15.01"

# What the Sat 11-21 run brought back for this question, best first.
EXPECTED_ARTICLES = ("المادة 12", "المادة 9", "المادة 17")

# Runs the real pipeline inside `api` and prints one JSON line tagged "t23".
# `top_k` is left to the default (retrieval.top_k_final), as in the manual run.
#
# The query, the file name and the publish flag arrive as JSON on the first stdin line, the way
# tests/sovereignty/test_leak_queries.py sends its queries: the script itself then holds no
# non-ASCII character, so nothing depends on how `docker compose exec` and the container's Python
# agree to decode a command-line argument.
T23_SCRIPT = """
import json, sys, uuid

OUT = {"t23": True}


def emit(stage, **extra):
    OUT["stage"] = stage
    OUT.update(extra)
    print(json.dumps(OUT, ensure_ascii=False))
    raise SystemExit(0)


config = json.loads(sys.stdin.readline())
query, source_file, law = config["query"], config["source_file"], config["law"]

try:
    from src.core.contracts import ServiceError, UserContext, registry
    from src.core.llm import real_models
    from src.retrieval import real_retrieval
except Exception as exc:
    emit("import_failed", error=type(exc).__name__, detail=str(exc)[:200])

# config.yaml keeps `models: fake`; P2 does not edit it, so the real client is installed here.
models = real_models()
registry.override("models", models)

try:
    retrieval = real_retrieval()          # creates the collection if missing (P2-01)
    payloads = retrieval.store.scroll_payloads()
except Exception as exc:
    emit("qdrant_unusable", error=type(exc).__name__, detail=str(exc)[:200])


def of_the_law(payloads):
    return [
        p for p in payloads
        if p.get("source_file") == source_file or law in (p.get("title") or "")
    ]


chunks = of_the_law(payloads)
if not chunks:
    emit("corpus_missing", chunks_in_store=len(payloads))

doc_ids = sorted({p["doc_id"] for p in chunks})

if config.get("publish"):
    # Opt-in only. The manifest declares this document `public`, and both calls are P2's own
    # idempotent rights operations (P2-23, P2-24) -- the publication P5 will do for itself.
    for doc_id in doc_ids:
        retrieval.update_roles(doc_id, ["lecteur", "editeur"])
        retrieval.show(doc_id)
    chunks = of_the_law(retrieval.store.scroll_payloads())

visible = [
    p for p in chunks
    if p.get("hidden") is False and "lecteur" in (p.get("allowed_roles") or [])
]
if not visible:
    emit("corpus_hidden", doc_ids=doc_ids, chunks=len(chunks))

try:
    models.embed(["ping"])
except ServiceError as exc:
    emit("models_down", error=type(exc).__name__, detail=str(exc)[:200])

ctx = UserContext(
    user_id=uuid.uuid4(), username="t23", role="lecteur",
    web_enabled=False, request_id=uuid.uuid4(),
)
try:
    passages = retrieval.search(query, ctx)
except Exception as exc:
    emit("search_failed", error=type(exc).__name__, detail=str(exc)[:200])

# No chunk text and no title leaves the container: source_file and article are enough to
# recognise the law, and keep this output free of document content (P2-29, spec section 7).
emit(
    "ok",
    doc_ids=doc_ids,
    visible_chunks=len(visible),
    passages=[
        {
            "doc_id": p.chunk.doc_id,
            "source_file": p.chunk.source_file,
            "article": p.chunk.article,
            "language": p.chunk.language,
            "rank": p.rank,
            "score": p.score,
        }
        for p in passages
    ],
)
"""

SKIP_REASONS = {
    "import_failed": "the project code could not be imported inside the api container",
    "qdrant_unusable": "Qdrant is not usable from the api container (is the compose healthy?)",
    "corpus_missing": (
        f"law {LAW_NUMBER} ({SOURCE_FILE}) is not in Qdrant: run `make up && make seed` first"
    ),
    "corpus_hidden": (
        f"law {LAW_NUMBER} is indexed but still hidden. P5's real publication is not wired yet "
        "(the fake document_rights never calls update_roles or show), so "
        "publish it by hand, or re-run with P2_T23_PUBLISH=1"
    ),
    "models_down": "P6's models service did not answer: bge-m3 is needed for cross-language search",
    "search_failed": "the search itself raised",
}


def _compose_services() -> set[str]:
    """The compose services currently running, or an empty set when compose cannot be asked."""
    if shutil.which("docker") is None:
        return set()
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:  # no .env, no daemon, bad compose file…
        return set()
    return set(result.stdout.split())


def _t23_line(stdout: str) -> dict[str, Any]:
    """The script's own JSON line. P5's logging writes JSON to stdout too, hence the tag."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{") or '"t23"' not in line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("t23") is True:
            return payload
    raise AssertionError(f"the script printed no t23 line:\n{stdout[-2000:]}")


@pytest.fixture(scope="module")
def run() -> dict[str, Any]:
    """One real search for ``FRENCH_QUERY``, run inside the ``api`` container.

    Skips — rather than fails — only on infrastructure: compose down, corpus not ingested, the
    document not published, the models service silent. Once all of that is in place the search
    runs and the assertions below decide.
    """
    services = _compose_services()
    if not {"api", "qdrant", "models"} <= services:
        pytest.skip(
            "api, qdrant and models are not all running (use `make up`; a .env is needed for "
            f"docker compose). Running: {sorted(services) or 'none'}"
        )

    config = {
        "query": FRENCH_QUERY,
        "source_file": SOURCE_FILE,
        "law": LAW_NUMBER,
        "publish": os.environ.get("P2_T23_PUBLISH") == "1",
    }
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", T23_SCRIPT],
        cwd=REPO_ROOT,
        input=json.dumps(config, ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,  # the re-ranker alone took 61 s on Sat 11-21; the first BM25 build adds more
    )
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-2000:])

    payload = _t23_line(result.stdout)
    stage = payload["stage"]
    if stage in SKIP_REASONS:
        detail = payload.get("detail") or payload.get("error") or ""
        pytest.skip(f"T23 skipped: {SKIP_REASONS[stage]}" + (f" ({detail})" if detail else ""))
    assert stage == "ok", payload
    return payload


def _articles(passages: list[dict[str, Any]]) -> set[str]:
    """The articles of the returned passages, normalized so Arabic-Indic digits compare equal."""
    return {normalize_ar(p["article"]) for p in passages if p.get("article")}


def test_t23_a_french_question_brings_back_the_arabic_law(run: dict[str, Any]) -> None:
    """T23: the French question returns chunks of law 15.01, which is written in Arabic.

    This is the whole point of the hybrid search's vector half: BM25 shares no word with an
    Arabic article, so a hit here can only come from bge-m3's cross-language embeddings.
    """
    passages = run["passages"]
    assert passages, "the search returned nothing at all"

    from_the_law = [p for p in passages if p["doc_id"] in run["doc_ids"]]
    assert from_the_law, (
        f"no passage of law {LAW_NUMBER} among {len(passages)} results: "
        f"{[(p['rank'], p['source_file'], p['article']) for p in passages]}"
    )
    assert all(p["language"] == "ar" for p in from_the_law)


def test_t23_the_expected_articles_are_among_the_results(run: dict[str, Any]) -> None:
    """The articles the Sat 11-21 run found: المادة 12, 9 and 17.

    At least one of them must come back. Asserting the exact three, in order, would make the test
    fail on any re-ranker or ``rerank_top_n`` change that is not a regression — and tuning those
    is day 10's work.
    """
    found = _articles([p for p in run["passages"] if p["doc_id"] in run["doc_ids"]])
    expected = {normalize_ar(article) for article in EXPECTED_ARTICLES}

    assert found & expected, (
        f"none of {EXPECTED_ARTICLES} came back for the French question; "
        f"articles of law {LAW_NUMBER} in the results: {sorted(found)}"
    )


def test_t23_the_result_is_a_normal_ranked_list(run: dict[str, Any]) -> None:
    """The real pipeline's answer obeys the same contract as everywhere else (P2-16, P2-17)."""
    passages = run["passages"]

    assert [p["rank"] for p in passages] == list(range(1, len(passages) + 1))
    scores = [p["score"] for p in passages]
    assert scores == sorted(scores, reverse=True)


# --- Offline guards: these run everywhere, compose or no compose --------------------------------
#
# The script above is a string, so Python never checks it until the day someone has the whole
# stack up. These three tests are what keep a typo in it from being discovered on the demo
# machine.


def test_the_container_script_is_valid_python() -> None:
    compile(T23_SCRIPT, "<T23_SCRIPT>", "exec")


def test_the_container_script_is_pure_ascii() -> None:
    """The query travels on stdin precisely so the command line needs no encoding agreement."""
    T23_SCRIPT.encode("ascii")


def test_the_t23_line_is_found_among_the_log_lines() -> None:
    """P5's logging writes JSON to stdout as well, so the tag is how the answer is recognised."""
    stdout = "\n".join(
        [
            '{"timestamp": "...", "event": "search", "returned": 3}',
            '{"t23": true, "stage": "ok", "passages": [], "doc_ids": []}',
            '{"timestamp": "...", "event": "http_request"}',
            "not json at all",
        ]
    )

    assert _t23_line(stdout)["stage"] == "ok"

    with pytest.raises(AssertionError):
        _t23_line('{"timestamp": "...", "event": "search"}')
