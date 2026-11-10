"""Contribution policy check.

Commits, pull requests and files must not carry attribution to third-party code-generation
tools or services: no co-author trailers or "generated with" notes, no tool configuration files,
no tool names in the code or the docs. The same check runs locally (pre-commit hooks) and in CI.

Usage:
    python scripts/check_contribution_policy.py files [PATH ...]   # given files, or all tracked files
    python scripts/check_contribution_policy.py msg FILE           # one commit message (commit-msg hook)
    python scripts/check_contribution_policy.py commits REV_RANGE  # messages, authors and committers
    python scripts/check_contribution_policy.py pr                 # PR_TITLE and PR_BODY from the environment
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SELF = Path(__file__).resolve()

# Tool configuration files and folders that must never be committed (matched on any path part).
FORBIDDEN_NAMES = re.compile(
    r"^(claude\.md|\.claude|agents\.md|gemini\.md|\.gemini|\.cursor|\.cursorrules|\.cursorignore"
    r"|\.windsurf|\.windsurfrules|\.aider.*|\.continue|\.codeium|\.tabnine.*|\.codex|\.clinerules"
    r"|\.cline|\.roo|\.kiro|copilot-instructions\.md)$",
    re.IGNORECASE,
)

# Names and phrases that must not appear in files. General domain words ("agent", "LLM", "AI",
# "model", "cursor") are allowed: this project is an agentic RAG system.
CONTENT = re.compile(
    r"\b(claude|anthropic|chatgpt|copilot|codeium|tabnine|windsurf)\b"
    r"|cursor\.(sh|com)"
    r"|\b(generated|written|created)\s+(by|with|using)\s+(an?\s+)?(ai|llm|assistant)\b"
    r"|\bai[- ]generated\b"
    r"|\bas an ai(\s+language)?\s+model\b",
    re.IGNORECASE,
)

# Commit messages, PR texts, author and committer: everything above, plus service and tool names
# that are legitimate inside the code (a cloud client library, for example) but never as authors.
META = re.compile(
    CONTENT.pattern + r"|\b(openai|gemini|codex)\b"
    r"|\bgpt-?\d"
    r"|noreply@(anthropic|openai)\.com"
    r"|^\s*co-authored-by:.*\b(ai|bot|assistant|llm)\b"
    r"|🤖",
    re.IGNORECASE | re.MULTILINE,
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, encoding="utf-8").stdout


def check_files(paths: list[str]) -> list[str]:
    if not paths:
        paths = [p for p in git("ls-files").splitlines() if p]
    errors = []
    for p in paths:
        path = Path(p)
        if any(FORBIDDEN_NAMES.match(part) for part in path.parts):
            errors.append(f"{p}: tool configuration file or folder")
            continue
        if not path.is_file() or path.resolve() == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary file
        for n, line in enumerate(text.splitlines(), start=1):
            if CONTENT.search(line):
                errors.append(f"{p}:{n}: tool attribution or tool name")
    return errors


def check_text(label: str, text: str) -> list[str]:
    return [f"{label}: tool attribution ({m.group(0).strip()!r})" for m in META.finditer(text)]


def check_commits(rev_range: str) -> list[str]:
    errors = []
    log = git("log", "--format=%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%B%x1e", rev_range)
    for entry in filter(None, (e.strip() for e in log.split("\x1e"))):
        sha, author, committer, body = entry.split("\x1f", 3)
        errors += check_text(f"commit {sha[:8]} author", author)
        errors += check_text(f"commit {sha[:8]} committer", committer)
        errors += check_text(f"commit {sha[:8]} message", body)
    return errors


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == "files":
        errors = check_files(rest)
    elif mode == "msg":
        errors = check_text("commit message", Path(rest[0]).read_text(encoding="utf-8"))
    elif mode == "commits":
        errors = check_commits(rest[0])
    elif mode == "pr":
        errors = check_text("PR title", os.environ.get("PR_TITLE", ""))
        errors += check_text("PR description", os.environ.get("PR_BODY", ""))
    else:
        print(__doc__)
        return 2
    for e in errors:
        print(f"contribution policy: {e}")
    if errors:
        print("\nRemove these before committing: third-party tool attribution is not allowed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
