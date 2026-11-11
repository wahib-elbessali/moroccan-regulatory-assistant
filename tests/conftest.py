"""Shared test fixtures (00-shared §9).

Note: The UserContext fixtures for P5 (lecteur_ctx, editeur_ctx, admin_ctx, other_lecteur_ctx,
specified in P5-08) will be added to this root conftest.py once P5 lands.
"""

from pathlib import Path

import pytest

from src.core.contracts import Chunk

SAMPLE_CHUNKS_FILE = Path(__file__).parent / "fixtures" / "sample_chunks.jsonl"


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Loads all chunks from tests/fixtures/sample_chunks.jsonl (P1-05).

    Returns a freshly validated and constructed list on each test call (function scope)
    so modifications made by one test do not affect others.
    """
    chunks: list[Chunk] = []
    with open(SAMPLE_CHUNKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks
