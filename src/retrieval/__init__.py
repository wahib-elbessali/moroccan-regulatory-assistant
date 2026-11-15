"""P2 retrieval: the real factory the registry calls (00-shared §9, P2 spec §6.2).

``real_retrieval()`` is the only place where the three slices of P2 are put together: Wahib's
``QdrantStore``, Basma's ``BM25Index`` and the ``Retrieval`` pipeline of ``search.py``. The wiring
is the one agreed in ``P2-common.md``.

**Nothing that touches the configuration is imported at module level.** ``src/core/config.py``
builds ``cfg`` while it is being imported and raises when the environment is incomplete (no
``.env``), and the registry imports it in turn. Importing a submodule of this package —
``src.retrieval.store``, ``.bm25``, ``.search`` — would then drag that failure along, and the
tests of P2 run without a ``.env``. So every project import that could trigger configuration
loading lives in ``real_retrieval()``'s body, and ``import src.retrieval.search`` stays free of
configuration.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # not executed at runtime, so it costs no import
    from .search import Retrieval

__all__ = ["real_retrieval"]

# ``RetrievalSettings`` (P5, ``src/core/config.py``) does not define ``qdrant_url``, ``collection``
# or ``embed_batch_size`` yet, although ``config.yaml`` carries all three under ``retrieval:``; a
# pydantic model ignores the keys it does not declare, so they are silently dropped. These are the
# config.yaml values, used until P5 adds the fields — see the note in ``P2-C-fatima.md``. P2 does
# not edit P5's file.
DEFAULT_QDRANT_URL = "http://qdrant:6333"  # retrieval.qdrant_url
DEFAULT_COLLECTION = "chunks"  # retrieval.collection
DEFAULT_EMBED_BATCH_SIZE = 32  # retrieval.embed_batch_size


def real_retrieval() -> "Retrieval":
    """Builds the real ``Retrieval``: Qdrant, BM25 and the hybrid pipeline (00-shared §9).

    The collection and its payload indexes are created here, before the object is handed out, so
    the first search never meets a missing collection (P2-01, P2-03).

    ``on_write=bump_version`` is what keeps BM25 honest: every write through the store gives the
    version file a new value, and ``BM25Index`` rebuilds itself at the next search (§6.5). The two
    objects share one Qdrant store — BM25 reads its corpus through ``store.scroll_payloads``, so
    P2 keeps no second copy of the chunks.

    The Qdrant URL is resolved in three steps. ``CI_QDRANT_URL`` wins whenever it is set, which
    is how the real half of the contract test (§8) reaches CI's Qdrant service container, exactly
    as P5-09b reads ``CI_POSTGRES_URL`` for Postgres. Without it, ``retrieval.qdrant_url`` is
    used, as long as ``RetrievalSettings`` declares that field. Until P5 adds it,
    ``DEFAULT_QDRANT_URL`` stands in — the same value, read from this module instead of from the
    configuration. ``collection`` and ``embed_batch_size`` fall back the same way, minus the
    environment step.

    Returns:
        A ``Retrieval`` configured from ``cfg.retrieval``.

    Raises:
        ServiceError: Qdrant is unreachable (``ensure_collection``).
        ValidationError: The configuration could not be loaded.
    """
    from qdrant_client import QdrantClient

    from src.core.config import cfg
    from src.core.contracts.registry import get_models

    from .bm25 import BM25Index
    from .search import Retrieval
    from .store import QdrantStore
    from .version import VERSION_FILE, bump_version

    settings = cfg.retrieval
    models = get_models()  # P6; P2 never loads a model itself

    # The URL, in order of precedence:
    #   1. ``CI_QDRANT_URL``, when it is set. In CI the tests run on the runner itself, where
    #      Qdrant is a service container published on localhost and not the ``qdrant`` service
    #      of the compose network. .github/workflows/ci.yml sets it; reading it here is what
    #      P5-09b does with ``CI_POSTGRES_URL`` in ``src/core/db/session.py``.
    #   2. ``settings.qdrant_url``, config.yaml's value, once P5 declares the field. Nothing
    #      sets ``CI_QDRANT_URL`` outside CI, so local Docker and the demo machine land here.
    #   3. ``DEFAULT_QDRANT_URL``, while that field does not exist yet: a pydantic model drops
    #      the keys it does not declare, so ``getattr`` would otherwise find nothing.
    qdrant_url = os.getenv("CI_QDRANT_URL") or getattr(settings, "qdrant_url", DEFAULT_QDRANT_URL)

    store = QdrantStore(
        QdrantClient(url=qdrant_url),
        models,
        collection=getattr(settings, "collection", DEFAULT_COLLECTION),
        embed_batch_size=getattr(settings, "embed_batch_size", DEFAULT_EMBED_BATCH_SIZE),
        on_write=bump_version,
    )
    store.ensure_collection()

    bm25 = BM25Index(load_payloads=store.scroll_payloads, version_file=VERSION_FILE)

    return Retrieval(
        store,
        bm25,
        models=models,
        top_k_vector=settings.top_k_vector,
        top_k_bm25=settings.top_k_bm25,
        rrf_k=settings.rrf_k,
        top_k_final=settings.top_k_final,
        rerank_top_n=settings.rerank_top_n,
    )
