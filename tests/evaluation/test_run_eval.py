"""Offline tests of evaluation/run_eval.py: matching, scoring one question, and the reports.

No stack is needed: the HTTP API is replaced by a stub and the grader by a recorder.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    """Import evaluation/<name>.py by path (the folder is scripts, not an installed package)."""
    spec = importlib.util.spec_from_file_location(
        f"evaluation_{name}", ROOT / "evaluation" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


run_eval = _load("run_eval")

# --- matching ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("المادة الأولى", "المادة 1"),
        ("المادة الثانية", "المادة 2"),
        ("الفصل الحادي عشر", "الفصل 11"),
        ("الفصل السادس", "الفصل 6"),
        ("المادة ١٢", "المادة 12"),
        ("المادة  12 ", "المادة 12"),
    ],
)
def test_article_key_reads_ordinals_as_numbers(a: str, b: str) -> None:
    assert run_eval.article_key(a) == run_eval.article_key(b)


def test_article_key_keeps_different_articles_apart() -> None:
    assert run_eval.article_key("المادة 1") != run_eval.article_key("المادة 11")
    assert run_eval.article_key("المادة 1") != run_eval.article_key("الفصل 1")
    assert run_eval.article_key(None) == ""


def test_matches_public_file_and_article() -> None:
    expected = {"source_file": "public/adala_011.pdf", "article": "المادة الأولى"}
    assert run_eval.matches(expected, "adala_011.pdf", "المادة 1")
    assert run_eval.matches(expected, "public/adala_011.pdf", "المادة 1")
    assert not run_eval.matches(expected, "adala_011.pdf", "المادة 2")
    assert not run_eval.matches(expected, "adala_010.pdf", "المادة 1")
    assert not run_eval.matches(expected, "adala_011.pdf", None)


def test_matches_internal_file_any_article() -> None:
    expected = {"source_file": "internal/internal_01_ai_governance.pdf", "article": "المادة 1"}
    assert run_eval.matches(expected, "internal_01_ai_governance.pdf", "المادة 7")
    assert run_eval.matches(expected, "internal_01_ai_governance.pdf", None)
    assert not run_eval.matches(expected, "internal_02_personal_data.pdf", "المادة 1")


def test_leaked_files_by_file_only() -> None:
    q = {
        "must_not_cite": [
            {"source_file": "internal/internal_02_personal_data.pdf", "article": "المادة 16"}
        ]
    }
    assert run_eval.leaked_files(q, ["internal_02_personal_data.pdf", "adala_001.pdf", None]) == [
        "internal_02_personal_data.pdf"
    ]
    assert run_eval.leaked_files(q, ["adala_001.pdf"]) == []


# --- one question ---------------------------------------------------------------------------------

DOC_PUBLIC = "a" * 64
DOC_OTHER = "b" * 64
DOC_INTERNAL = "c" * 64
DOC_FILES = {
    DOC_PUBLIC: "adala_011.pdf",
    DOC_OTHER: "adala_010.pdf",
    DOC_INTERNAL: "internal_02_personal_data.pdf",
}


def chunk(doc_id: str, article: str | None, text: str = "نص") -> dict:
    return {"doc_id": doc_id, "source_file": DOC_FILES[doc_id], "article": article, "text": text}


def passage(c: dict, rank: int) -> dict:
    return {"chunk": c, "rank": rank, "score": 1.0 / rank}


def citation(
    doc_id: str | None, article: str | None, excerpt: str = "مقتطف", url: str | None = None
) -> dict:
    return {"doc_id": doc_id, "url": url, "title": "t", "article": article, "page": 1,
            "source": None, "date": None, "excerpt": excerpt}  # fmt: skip


def question(**over: Any) -> dict:
    q = {
        "id": "p9-01",
        "group": "P9",
        "question": "سؤال",
        "language": "ar",
        "role": "lecteur",
        "use_web": False,
        "type": "simple",
        "expected_status": "answered",
        "expected_sources": [{"source_file": "public/adala_011.pdf", "article": "المادة الأولى"}],
        "must_not_cite": [],
        "reference_answer": "جواب",
    }
    q.update(over)
    return q


class StubApi:
    """Answers /search with the given responses in order, and /ask with one answer."""

    def __init__(
        self, searches: list[tuple[int, Any]], answer: dict | None, error: dict | None = None
    ):
        self.searches = list(searches)
        self.answer = answer
        self.error = error
        self.search_calls = 0
        self.asked: list[tuple[str, str, bool]] = []

    def call(self, method: str, path: str, token: str | None = None, body: Any = None):
        assert (method, path) == ("POST", "/search")
        assert body["top_k"] == run_eval.TOP_K
        self.search_calls += 1
        return self.searches.pop(0)

    def ask(self, token: str, q: str, use_web: bool) -> dict:
        self.asked.append((token, q, use_web))
        return {"answer": self.answer, "error": self.error, "first_event_s": 0.5, "seconds": 2.0}


TOKENS = {"lecteur": "tok-l", "editeur": "tok-e", "admin": "tok-a"}


@pytest.fixture
def grades(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replaces the grader; records what it receives."""
    calls: list[dict] = []

    def fake_grade(compose, model, q, answer, passages):  # type: ignore[no-untyped-def]
        calls.append({"q": q["id"], "answer": answer, "passages": passages})
        return {"faithfulness": 1.0, "relevance": 0.5}

    monkeypatch.setattr(run_eval, "grade", fake_grade)
    monkeypatch.setattr(run_eval.time, "sleep", lambda _s: None)
    return calls


def args(no_grader: bool = False, search_only: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        no_grader=no_grader or search_only,
        search_only=search_only,
        compose=["docker", "compose"],
        grader_model=None,
    )


def answered(citations: list[dict], text: str = "جواب [1].") -> dict:
    return {
        "status": "answered",
        "text": text,
        "citations": citations,
        "confidence": 0.8,
        "language": "ar",
    }


def test_answered_and_cited(grades: list[dict]) -> None:
    results = [
        passage(chunk(DOC_OTHER, "المادة 3"), 1),
        passage(chunk(DOC_PUBLIC, "المادة 1", "النص الكامل"), 2),
    ]
    api = StubApi([(200, results)], answered([citation(DOC_PUBLIC, "المادة 1")]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert api.asked == [("tok-l", "سؤال", False)]
    assert (row["hit_rank"], row["hit"], row["rr"]) == (2, True, 0.5)
    assert row["status"] == "answered" and row["status_ok"] is True
    assert row["citations"] == [["adala_011.pdf", "المادة 1"]]
    assert row["cited_ok"] is True
    assert row["leaks"] == []
    assert row["top"] == [["adala_010.pdf", "المادة 3"], ["adala_011.pdf", "المادة 1"]]
    assert row["grade"] == {"faithfulness": 1.0, "relevance": 0.5}
    # The cited article is in the search results: the grader gets its full text, not the excerpt.
    assert grades[0]["passages"] == ["النص الكامل"]


def test_cited_wrong_source(grades: list[dict]) -> None:
    api = StubApi([(200, [])], answered([citation(DOC_OTHER, "المادة 1", excerpt="مقتطف آخر")]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert (row["hit_rank"], row["hit"], row["rr"]) == (None, False, 0.0)
    assert row["status_ok"] is True
    assert row["citations"] == [["adala_010.pdf", "المادة 1"]]
    assert row["cited_ok"] is False
    # Not in the search results: the grader falls back to the cited excerpt.
    assert grades[0]["passages"] == ["مقتطف آخر"]


def test_unknown_doc_id_and_web_citation(grades: list[dict]) -> None:
    cits = [citation("f" * 64, "المادة 1"), citation(None, None, url="https://example.ma/x")]
    api = StubApi([(200, [])], answered(cits))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert row["citations"] == [["f" * 64, "المادة 1"], ["https://example.ma/x", None]]
    assert row["cited_ok"] is False


def test_unknown_answer_is_not_graded(grades: list[dict]) -> None:
    unknown = {
        "status": "unknown",
        "text": "لم أجد",
        "citations": [],
        "confidence": 0.0,
        "language": "ar",
    }
    api = StubApi([(200, [passage(chunk(DOC_PUBLIC, "المادة 1"), 1)])], unknown)

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert row["hit"] is True
    assert row["status_ok"] is False and row["cited_ok"] is False
    assert "grade" not in row and grades == []


def test_no_grader_option(grades: list[dict]) -> None:
    api = StubApi([(200, [])], answered([citation(DOC_PUBLIC, "المادة 1")]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args(no_grader=True))

    assert "grade" not in row and grades == []


def test_search_only_option(grades: list[dict]) -> None:
    q = question(
        must_not_cite=[{"source_file": "internal/internal_02_personal_data.pdf", "article": "x"}]
    )
    results = [
        passage(chunk(DOC_INTERNAL, "المادة 3"), 1),
        passage(chunk(DOC_PUBLIC, "المادة 1"), 2),
    ]
    api = StubApi([(200, results)], answered([citation(DOC_PUBLIC, "المادة 1")]))

    row = run_eval.evaluate(q, api, TOKENS, DOC_FILES, args(search_only=True))

    assert api.asked == [] and grades == []  # no /ask, no grader
    assert row["hit_rank"] == 2 and row["rr"] == 0.5
    assert row["leaks"] == ["internal_02_personal_data.pdf"]  # still checked on the results
    assert "status_ok" not in row and "cited_ok" not in row and "search_seconds" in row


def test_access_question_leaks(grades: list[dict]) -> None:
    q = question(
        type="access",
        expected_status="unknown",
        expected_sources=[],
        reference_answer="",
        must_not_cite=[
            {"source_file": "internal/internal_02_personal_data.pdf", "article": "المادة 16"}
        ],
    )
    # A forbidden file in the search results (any article) and in a citation.
    results = [passage(chunk(DOC_INTERNAL, "المادة 3"), 1)]
    api = StubApi([(200, results)], answered([citation(DOC_INTERNAL, "المادة 9")]))

    row = run_eval.evaluate(q, api, TOKENS, DOC_FILES, args())

    assert row["leaks"] == ["internal_02_personal_data.pdf"]
    assert row["status_ok"] is False
    assert "hit" not in row and "cited_ok" not in row
    assert "grade" not in row and grades == []  # an answer that should not exist is not graded


def test_access_question_clean(grades: list[dict]) -> None:
    q = question(
        type="access",
        expected_status="unknown",
        expected_sources=[],
        reference_answer="",
        must_not_cite=[
            {"source_file": "internal/internal_02_personal_data.pdf", "article": "المادة 16"}
        ],
    )
    unknown = {
        "status": "unknown",
        "text": "لم أجد",
        "citations": [],
        "confidence": 0.0,
        "language": "ar",
    }
    api = StubApi([(200, [passage(chunk(DOC_PUBLIC, "المادة 1"), 1)])], unknown)

    row = run_eval.evaluate(q, api, TOKENS, DOC_FILES, args())

    assert row["leaks"] == [] and row["status_ok"] is True


def test_search_gateway_timeout_is_retried(grades: list[dict]) -> None:
    results = [passage(chunk(DOC_PUBLIC, "المادة 1"), 1)]
    api = StubApi([(504, "<html>"), (200, results)], answered([citation(DOC_PUBLIC, "المادة 1")]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert api.search_calls == 2
    assert "search_error" not in row and row["hit_rank"] == 1


def test_search_failure_is_an_error_without_score(grades: list[dict]) -> None:
    api = StubApi([(504, "<html>")] * 3, answered([citation(DOC_PUBLIC, "المادة 1")]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert api.search_calls == 3
    assert row["search_error"].startswith("504")
    assert "hit" not in row and "rr" not in row
    assert row["top"] == []
    assert row["cited_ok"] is True  # the answer is still scored


def test_search_client_error_is_not_retried(grades: list[dict]) -> None:
    api = StubApi([(422, {"code": "invalid_input"})], answered([]))

    row = run_eval.evaluate(question(), api, TOKENS, DOC_FILES, args())

    assert api.search_calls == 1 and row["search_error"].startswith("422")


def test_ask_error(grades: list[dict]) -> None:
    api = StubApi([(200, [])], None, error={"code": "client_error", "message": "timed out"})

    row = run_eval.evaluate(question(role="editeur"), api, TOKENS, DOC_FILES, args())

    assert api.asked[0][0] == "tok-e"
    assert row["status"] is None and row["status_ok"] is False
    assert row["error"]["code"] == "client_error"
    assert row["citations"] == [] and row["cited_ok"] is False
    assert grades == []


# --- grader output ---------------------------------------------------------------------------------


def test_grade_rounds_scores_and_reports_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_in_api(compose, script):  # type: ignore[no-untyped-def]
        seen.append(script)
        return {
            "model": "m",
            "results": [
                {"parsed": {"score": 0.8, "reason": "f"}, "raw": ""},
                {"parsed": {"score": 0.2, "reason": "r"}, "raw": ""},
            ],
        }

    monkeypatch.setattr(run_eval, "in_api", fake_in_api)
    g = run_eval.grade(["dc"], None, question(), {"text": "<b>جواب</b>"}, ["مصدر"])
    assert (g["faithfulness"], g["relevance"], g["model"]) == (1.0, 0.0, "m")
    assert g["reason"] == {"faithfulness": "f", "relevance": "r"}
    assert "error" not in g
    assert "&lt;b&gt;" in seen[0]  # answer text is escaped inside its tag

    unreadable = {
        "model": "m",
        "results": [{"parsed": None, "raw": "??"}, {"parsed": {"score": "high"}, "raw": "?"}],
    }
    monkeypatch.setattr(run_eval, "in_api", lambda c, s: unreadable)
    g = run_eval.grade(["dc"], None, question(), {"text": "x"}, [])
    assert g["faithfulness"] is None and g["relevance"] is None
    assert g["error"] == "unreadable grader output" and g["raw"] == ["??", "?"]

    def broken(compose, script):  # type: ignore[no-untyped-def]
        raise RuntimeError("container down")

    monkeypatch.setattr(run_eval, "in_api", broken)
    g = run_eval.grade(["dc"], None, question(), {"text": "x"}, [])
    assert g["relevance"] is None and "container down" in g["error"]


def test_grade_keeps_the_two_checks_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    """Faithfulness never sees the reference answer; relevance never sees the sources."""
    import ast

    seen: list[str] = []

    def fake_in_api(compose, script):  # type: ignore[no-untyped-def]
        seen.append(script)
        return {"model": "m", "results": [{"parsed": {"score": 1}}, {"parsed": {"score": 1}}]}

    monkeypatch.setattr(run_eval, "in_api", fake_in_api)
    q = question(reference_answer="REFERENCE-TEXT")
    run_eval.grade(["dc"], "qwen2.5:7b", q, {"text": "ANSWER-TEXT"}, ["SOURCE-TEXT"])
    data = json.loads(ast.literal_eval(seen[0].split("\n", 1)[0].removeprefix("DATA = ")))
    faith, relevance = (call[1]["content"] for call in data["calls"])
    assert "SOURCE-TEXT" in faith and "ANSWER-TEXT" in faith and "REFERENCE-TEXT" not in faith
    assert "REFERENCE-TEXT" in relevance and "ANSWER-TEXT" in relevance
    assert "SOURCE-TEXT" not in relevance
    assert data["model"] == "qwen2.5:7b"


# --- reports --------------------------------------------------------------------------------------


def result(id_: str, **over: Any) -> dict:
    row = {
        "id": id_,
        "group": "P1",
        "type": "simple",
        "role": "lecteur",
        "language": "ar",
        "expected_status": "answered",
        "status": "answered",
        "status_ok": True,
        "error": None,
        "leaks": [],
        "seconds": 10.0,
    }
    row.update(over)
    return row


def write_results(path: Path, rows: list[dict], commit: str = "abc1234") -> Path:
    setup = {
        "kind": "setup",
        "git_commit": commit,
        "config": {"mode": "light", "llm": {"model_light": "q3b"}},
    }
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [setup, *rows]), encoding="utf-8"
    )
    return path


ROWS = [
    result("p1-01", hit=True, hit_rank=1, rr=1.0, cited_ok=True, grade={"faithfulness": 1.0, "relevance": 1.0}),
    result("p1-02", hit=True, hit_rank=4, rr=0.25, cited_ok=False, grade={"faithfulness": 0.5, "relevance": 0.0}, seconds=30.0),
    result("p1-03", hit=False, hit_rank=None, rr=0.0, status="unknown", status_ok=False, cited_ok=False, seconds=20.0),
    result("p1-04", search_error="504 <html>", status="unknown", status_ok=False, cited_ok=False, seconds=40.0),
    result("p1-05", type="access", expected_status="unknown", status="unknown", status_ok=True),
    result("p1-06", type="access", expected_status="unknown", status="answered", status_ok=False, leaks=["internal_02_personal_data.pdf"]),
    result("p1-07", role="admin", hit=False, hit_rank=None, rr=0.0, cited_ok=False, status="unknown", status_ok=False),
]  # fmt: skip


def test_scores() -> None:
    s = run_eval.scores(ROWS)
    assert s["questions"] == 7
    # p1-04 (search failed) and p1-07 (admin) are left out of the search scores.
    assert s["hit@10"] == pytest.approx(2 / 3)
    assert s["MRR"] == pytest.approx((1.0 + 0.25 + 0.0) / 3)
    assert s["status ok"] == pytest.approx(3 / 7)
    assert s["answered+cited"] == pytest.approx(1 / 5)
    assert s["unknown ok"] == pytest.approx(1 / 2)
    assert s["faithful"] == pytest.approx(0.75)
    assert s["relevant"] == pytest.approx(0.5)
    assert s["leaks"] == 1
    assert s["errors"] == 1  # the failed search counts as an error
    assert s["s median"] == 10.0


def test_scores_empty() -> None:
    s = run_eval.scores([])
    assert s["questions"] == 0 and s["hit@10"] is None and s["s mean"] is None


def test_summary(tmp_path: Path) -> None:
    text = run_eval.summary(write_results(tmp_path / "r.jsonl", ROWS))
    assert "commit abc1234" in text and "mode light" in text and "model q3b" in text
    for title in (
        "### Overall",
        "### By type",
        "### By group",
        "### By role",
        "### Questions to look at",
    ):
        assert title in text
    to_look = text.split("### Questions to look at")[1]
    for id_ in ("p1-03", "p1-04", "p1-06", "p1-07"):
        assert f"| {id_} |" in to_look
    assert "| p1-01 |" not in to_look and "| p1-05 |" not in to_look
    assert "search 504" in to_look
    assert "internal_02_personal_data.pdf" in to_look


def test_compare(tmp_path: Path) -> None:
    old = write_results(tmp_path / "old.jsonl", ROWS[:3], commit="old1111")
    new_rows = [
        ROWS[0],
        dict(ROWS[1], hit_rank=1, rr=1.0, cited_ok=True),
        dict(ROWS[2], status_ok=True, status="answered"),
    ]
    new_rows.append(result("p1-99"))  # only in the new run: left out
    new = write_results(tmp_path / "new.jsonl", new_rows, commit="new2222")

    text = run_eval.compare([old, new])

    assert "(3 questions in all of them)" in text
    assert "| | old | new |" in text
    assert "| commit | old1111 | new2222 |" in text
    assert "| MRR | 0.42 | 0.67 |" in text
    changed = text.split("### Questions that changed")[1]
    assert "| p1-02 | cited_ok | False | True |" in changed
    assert "| p1-02 | hit_rank | 4 | 1 |" in changed
    assert "| p1-03 | status_ok | False | True |" in changed
    assert "p1-01" not in changed and "p1-99" not in changed


def write_variant(path: Path, rows: list[dict], max_chars: int, **setup: Any) -> Path:
    config = {"mode": "local", "retrieval": {"rerank_top_n": 16, "rerank_max_chars": max_chars}}
    lines = [{"kind": "setup", "git_commit": "abc1234", "config": config, **setup}, *rows]
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), "utf-8")
    return path


def search_row(id_: str, rank: int | None, seconds: float) -> dict:
    row = {k: v for k, v in result(id_).items() if k not in ("status", "status_ok", "seconds")}
    row.update(hit_rank=rank, hit=rank is not None, rr=1 / rank if rank else 0.0)
    row["search_seconds"] = seconds
    return row


def test_compare_several_search_only_runs(tmp_path: Path) -> None:
    runs = [
        write_variant(
            tmp_path / f"chars{n}.jsonl",
            [search_row("p1-01", 1, s), search_row("p1-02", rank, s)],
            n,
            search_only=True,
        )
        for n, rank, s in ((300, None, 2.0), (500, 3, 3.0), (2000, 3, 8.0))
    ]

    text = run_eval.compare(runs)

    assert "## Comparison of 3 runs (2 questions in all of them)" in text
    assert "| | chars300 | chars500 | chars2000 |" in text
    # Only the settings that differ are listed.
    assert "| retrieval.rerank_max_chars | 300 | 500 | 2000 |" in text
    assert "rerank_top_n" not in text and "| mode |" not in text
    assert "| hit@10 | 0.50 | 1.00 | 1.00 |" in text
    assert "| search s | 2.0 | 3.0 | 8.0 |" in text
    assert "| status ok | – | – | – |" in text  # no answer in a search-only run
    changed = text.split("### Questions that changed")[1]
    assert "| p1-02 | hit_rank | – | 3 | 3 |" in changed
    assert "p1-01" not in changed and "status_ok" not in changed


def test_summary_of_a_search_only_run(tmp_path: Path) -> None:
    path = write_variant(
        tmp_path / "s.jsonl",
        [search_row("p1-01", 1, 2.0), search_row("p1-02", None, 2.0)],
        300,
        search_only=True,
    )
    text = run_eval.summary(path)
    assert "search only" in text and "grader" not in text
    to_look = text.split("### Questions to look at")[1]
    assert "| p1-02 |" in to_look and "| p1-01 |" not in to_look


def test_compare_needs_two_files(tmp_path: Path) -> None:
    one = write_results(tmp_path / "one.jsonl", ROWS[:1])
    with pytest.raises(SystemExit):
        run_eval.main(["compare", str(one)])


def test_read_results_skips_blank_lines(tmp_path: Path) -> None:
    path = write_results(tmp_path / "r.jsonl", ROWS[:2])
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    setup, rows = run_eval.read_results(path)
    assert setup["git_commit"] == "abc1234" and [r["id"] for r in rows] == ["p1-01", "p1-02"]
