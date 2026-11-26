"""Offline tests of evaluation/build_dataset.py, on small question files made for each test."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"evaluation_{name}", ROOT / "evaluation" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build = _load("build_dataset")

MANIFEST = (
    "file,title,type,number,date,bo_issue,source_url,language,scanned,visibility\n"
    "public/adala_011.pdf,t,loi,1,,,,ar,no,public\n"
    "internal/internal_02_personal_data.pdf,t,interne,2,,,,ar,no,internal\n"
)


def q(id_: str, **over: object) -> dict:
    row = {
        "id": id_,
        "group": id_.split("-")[0].upper(),
        "question": "سؤال",
        "language": "ar",
        "role": "lecteur",
        "use_web": False,
        "type": "simple",
        "expected_status": "answered",
        "expected_sources": [{"source_file": "public/adala_011.pdf", "article": "المادة 1"}],
        "must_not_cite": [],
        "reference_answer": "جواب",
    }
    row.update(over)
    return row


ACCESS = {
    "type": "access",
    "expected_status": "unknown",
    "expected_sources": [],
    "reference_answer": "",
    "must_not_cite": [
        {"source_file": "internal/internal_02_personal_data.pdf", "article": "المادة 16"}
    ],
}


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A questions folder, a manifest, the output path, and no real-id corrections."""
    monkeypatch.setattr(build, "FIXES", {})
    monkeypatch.setattr(build, "DUPLICATES", {})
    questions = tmp_path / "questions"
    questions.mkdir()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(MANIFEST, encoding="utf-8")
    out = tmp_path / "dataset.jsonl"

    def write(name: str, rows: list[dict | str]) -> None:
        lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
        (questions / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run() -> int:
        return build.main(
            ["--questions", str(questions), "--out", str(out), "--manifest", str(manifest)]
        )

    return write, run, out


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_valid_set_builds(setup, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    write("p1.jsonl", [q("p1-01"), "", q("p1-02", **ACCESS)])
    write("p2.jsonl", [q("p2-01", role="editeur", language="darija", type="darija")])

    assert run() == 0
    assert [r["id"] for r in read(out)] == ["p1-01", "p1-02", "p2-01"]
    assert "3 questions written" in capsys.readouterr().out


def test_duplicates_dropped_and_fixes_applied(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    monkeypatch.setattr(build, "DUPLICATES", {"p2-01": "p1-01"})
    monkeypatch.setattr(
        build,
        "FIXES",
        {
            "p1-01": [("reference_answer", "جواب", "جواب كامل", "why")],
            "p1-02": [("language", "ar", "fr", "why")],
        },
    )
    write("p1.jsonl", [q("p1-01"), q("p1-02", **ACCESS)])
    write("p2.jsonl", [q("p2-01")])

    assert run() == 0
    rows = {r["id"]: r for r in read(out)}
    assert set(rows) == {"p1-01", "p1-02"}
    assert rows["p1-01"]["reference_answer"] == "جواب كامل"
    assert rows["p1-02"]["language"] == "fr"


def test_fix_on_changed_line_writes_nothing(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    monkeypatch.setattr(build, "FIXES", {"p1-01": [("language", "fr", "ar", "why")]})
    write("p1.jsonl", [q("p1-01")])

    assert run() == 1
    assert not out.exists()


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({k: v for k, v in q("p1-01").items() if k != "reference_answer"}, "missing"),
        (q("p1-01", language="en"), "language"),
        (q("p1-01", role="juriste"), "role"),
        (q("p1-01", type="other"), "type"),
        (q("p1-01", use_web="no"), "use_web"),
        (
            q(
                "p1-01",
                expected_sources=[{"source_file": "public/nope.pdf", "article": "المادة 1"}],
            ),
            "manifest",
        ),
        (q("p1-01", expected_sources=[]), "needs expected_sources"),
        (q("p1-01", reference_answer=""), "needs a reference_answer"),
        (q("p1-01", expected_status="unknown"), "must have no expected_sources"),
        (q("p1-01", **{**ACCESS, "must_not_cite": []}), "needs must_not_cite"),
        (q("p1-01", group="P2"), "does not start with"),
        ("{not json", "not valid JSON"),
    ],
)
def test_invalid_line_writes_nothing(setup, capsys, row, message) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    write("p1.jsonl", [q("p1-02"), row])

    assert run() == 1
    assert not out.exists()
    assert message in capsys.readouterr().err


def test_duplicate_id_writes_nothing(setup, capsys) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    write("p1.jsonl", [q("p1-01")])
    write("p1b.jsonl", [q("p1-01")])

    assert run() == 1
    assert not out.exists()
    assert "p1-01 appears 2 times" in capsys.readouterr().err


def test_duplicate_list_with_missing_id_writes_nothing(setup, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    write, run, out = setup
    monkeypatch.setattr(build, "DUPLICATES", {"p9-01": "p1-01"})
    write("p1.jsonl", [q("p1-01")])

    assert run() == 1
    assert not out.exists()
    assert "p9-01 not found" in capsys.readouterr().err


def test_real_question_files_are_valid(tmp_path: Path) -> None:
    """The committed group files build with the real corrections and duplicate list."""
    out = tmp_path / "dataset.jsonl"
    assert build.main(["--out", str(out)]) == 0
    committed = (ROOT / "evaluation" / "dataset.jsonl").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == committed
