"""Fixtures for P2 tests. Helpers (chunks, contexts, fake embeddings) are in p2_helpers.py.

Qdrant: the CI service container when CI_QDRANT_URL is set, otherwise Qdrant's in-memory mode.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from qdrant_client import QdrantClient


@pytest.fixture
def qdrant() -> Iterator[QdrantClient]:
    url = os.environ.get("CI_QDRANT_URL")
    client = QdrantClient(url=url) if url else QdrantClient(":memory:")
    yield client
    client.close()


@pytest.fixture
def collection(qdrant: QdrantClient) -> Iterator[str]:
    name = f"test_{uuid.uuid4().hex[:12]}"
    yield name
    if qdrant.collection_exists(name):
        qdrant.delete_collection(name)
