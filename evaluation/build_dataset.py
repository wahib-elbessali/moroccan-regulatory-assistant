"""Build evaluation/dataset.jsonl from the questions each group wrote.

Each group sends its questions as ``evaluation/questions/p<N>.jsonl``, one JSON object per line.
This script checks every line, applies the corrections found when the questions were checked
against the PDFs, drops the questions several groups wrote twice, and writes one file.

Usage (from the repository root)::

    python evaluation/build_dataset.py
    python evaluation/build_dataset.py --questions evaluation/questions --out evaluation/dataset.jsonl

It exits with status 1 and lists every problem when a line is invalid; nothing is written then.
The rules and the list of corrections: evaluation/README.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIELDS = [
    "id",
    "group",
    "question",
    "language",
    "role",
    "use_web",
    "type",
    "expected_status",
    "expected_sources",
    "must_not_cite",
    "reference_answer",
]
LANGUAGES = {"ar", "fr", "darija"}
ROLES = {"lecteur", "editeur", "admin"}
TYPES = {"simple", "multi_part", "french", "darija", "access", "out_of_corpus"}
STATUSES = {"answered", "unknown"}

# Corrections found while checking the questions against the PDFs: id -> (field, old, new, why).
# The old value is checked, so a correction is never applied to a line that has changed since.
FIXES: dict[str, list[tuple[str, str, str, str]]] = {
    "p4-11": [("language", "ar", "fr", "the question is written in French")],
    "p1-07": [
        (
            "reference_answer",
            "ورئاسة النيابة العامة.",
            "ورئاسة النيابة العامة والهيئة الوطنية للمفوضين القضائيين.",
            "article 11 lists three bodies; the reference had two",
        )
    ],
}

# The same question written by several groups: dropped id -> kept id.
DUPLICATES: dict[str, str] = {
    "p3-02": "p1-05",  # adala_011, article 1 (family council)
    "p6-01": "p1-05",
    "p5-09": "p1-05",
    "p4-04": "p1-03",  # adala_005, article 12
    "p2-02": "p1-03",
    "p5-05": "p3-01",
    "p5-06": "p4-06",
    "p2-09": "p3-03",
}


def corpus_files(manifest: Path) -> set[str]:
    """The ``file`` column of the corpus manifest, e.g. ``public/adala_001.pdf``."""
    with manifest.open(encoding="utf-8", newline="") as f:
        return {row["file"] for row in csv.DictReader(f)}


def check_line(row: dict, files: set[str]) -> list[str]:
    """Every problem found in one question; an empty list means the line is valid."""
    problems: list[str] = []
    if list(row) != FIELDS:
        missing = [k for k in FIELDS if k not in row]
        extra = [k for k in row if k not in FIELDS]
        if missing or extra:
            return [f"fields: missing {missing}, unexpected {extra}"]
    for key in ("id", "group", "question", "reference_answer"):
        if not isinstance(row[key], str):
            problems.append(f"{key} must be a string")
    if problems:
        return problems
    if not row["id"].startswith(row["group"].lower() + "-"):
        problems.append(f"id {row['id']!r} does not start with {row['group'].lower()}-")
    if not row["question"].strip():
        problems.append("question is empty")
    for key, allowed in (
        ("language", LANGUAGES),
        ("role", ROLES),
        ("type", TYPES),
        ("expected_status", STATUSES),
    ):
        if row[key] not in allowed:
            problems.append(f"{key} {row[key]!r} not in {sorted(allowed)}")
    if not isinstance(row["use_web"], bool):
        problems.append("use_web must be true or false")
    for key in ("expected_sources", "must_not_cite"):
        sources = row[key]
        if not isinstance(sources, list):
            problems.append(f"{key} must be a list")
            continue
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"source_file", "article"}:
                problems.append(f"{key}: each item needs exactly source_file and article")
            elif source["source_file"] not in files:
                problems.append(f"{key}: {source['source_file']!r} is not in the manifest")
    if row["expected_status"] == "answered":
        if not row["expected_sources"]:
            problems.append("an answered question needs expected_sources")
        if not row["reference_answer"].strip():
            problems.append("an answered question needs a reference_answer")
    elif row["expected_sources"]:
        problems.append("an unknown question must have no expected_sources")
    if row["type"] == "access" and row["expected_status"] == "unknown" and not row["must_not_cite"]:
        problems.append("an access question answered 'unknown' needs must_not_cite")
    return problems


def apply_fixes(row: dict) -> list[str]:
    """Apply this question's corrections; return a note per correction (problems start with !)."""
    notes = []
    for field, old, new, why in FIXES.get(row["id"], []):
        value = row[field]
        if field == "reference_answer" and old in value:
            row[field] = value.replace(old, new)
        elif value == old:
            row[field] = new
        else:
            notes.append(f"! {row['id']}: expected {field} to contain {old!r}; not changed")
            continue
        notes.append(f"{row['id']}: {field} corrected ({why})")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--questions", type=Path, default=ROOT / "evaluation" / "questions")
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation" / "dataset.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "raw" / "manifest.csv")
    args = parser.parse_args(argv)

    files = corpus_files(args.manifest)
    rows: list[dict] = []
    problems: list[str] = []
    for path in sorted(args.questions.glob("p*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path.name}:{number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{where}: not valid JSON ({exc.msg})")
                continue
            if not isinstance(row, dict):
                problems.append(f"{where}: not a JSON object")
                continue
            problems += [f"{where} {row.get('id', '?')}: {p}" for p in check_line(row, files)]
            rows.append(row)

    ids = Counter(row.get("id") for row in rows)
    problems += [f"id {i} appears {n} times" for i, n in ids.items() if n > 1]
    problems += [f"duplicate list: {i} not found" for i in DUPLICATES if i not in ids]
    problems += [f"duplicate list: kept {k} not found" for k in DUPLICATES.values() if k not in ids]
    if problems:
        print("Invalid questions, nothing written:", *problems, sep="\n  ", file=sys.stderr)
        return 1

    notes: list[str] = []
    kept = []
    for row in rows:
        if row["id"] in DUPLICATES:
            notes.append(f"{row['id']}: dropped, same question as {DUPLICATES[row['id']]}")
            continue
        notes += apply_fixes(row)
        kept.append(row)
    if any(n.startswith("!") for n in notes):
        print("Corrections did not apply, nothing written:", *notes, sep="\n  ", file=sys.stderr)
        return 1

    args.out.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8"
    )
    print(*notes, sep="\n")
    print(f"\n{len(kept)} questions written to {args.out} ({len(rows) - len(kept)} dropped)")
    for key in ("group", "type", "role", "language", "expected_status"):
        counts = Counter(row[key] for row in kept)
        print(f"  {key}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
