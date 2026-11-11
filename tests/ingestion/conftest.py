"""Fixtures for ingestion tests (P1-05)."""

import sys
from pathlib import Path

import pytest

# Ensure repository root is on sys.path so 'tests.ingestion.doubles' can be imported cleanly
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.core.contracts import Chunk  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_CHUNKS_PATH = FIXTURES_DIR / "sample_chunks.jsonl"


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Loads all chunks from tests/fixtures/sample_chunks.jsonl (P1-05)."""
    chunks: list[Chunk] = []
    with open(SAMPLE_CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks
