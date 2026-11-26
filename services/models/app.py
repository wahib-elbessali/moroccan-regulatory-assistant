"""models service: bge-m3 embeddings and the bge-reranker-v2-m3 re-ranker over HTTP.

P6 spec §4.2. The models are read from the Hugging Face cache (volume ``hf_cache``, filled once by
`make models`), so the service starts with no internet. Model names come from ``config.yaml``.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from pydantic import BaseModel, Field

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.yaml"))
MAX_TEXTS = 256  # per request; the clients send batches of 32 (retrieval.embed_batch_size)
BATCH_SIZE = 32


def pick_device() -> str:
    """``cuda`` when the container has an NVIDIA card (docker-compose.gpu.yml), else ``cpu``."""
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_models():
    """Load the embedding model and the re-ranker named in ``config.yaml`` (``models`` section).

    On the graphics card, both run in half precision: half the memory, so they fit next to the
    language model.
    """
    names = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["models"]
    from sentence_transformers import CrossEncoder, SentenceTransformer

    device = pick_device()
    embedder = SentenceTransformer(names["embedding"], device=device)
    reranker = CrossEncoder(names["reranker"], device=device)
    if device == "cuda":
        embedder.half()
        reranker.model.half()
    print(f"models loaded on {device}", flush=True)
    return embedder, reranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The server only accepts requests once this has finished: a healthy service has its models.
    app.state.embedder, app.state.reranker = load_models()
    yield


main = FastAPI(title="Models Service", lifespan=lifespan)


class EmbedIn(BaseModel):
    texts: list[str] = Field(max_length=MAX_TEXTS)


class RerankIn(BaseModel):
    query: str
    texts: list[str] = Field(max_length=MAX_TEXTS)


@main.get("/health")
def health_check():
    return {"status": "healthy"}


@main.post("/embed")
def embed(body: EmbedIn):
    if not body.texts:
        return {"vectors": []}
    vectors = main.state.embedder.encode(
        body.texts, batch_size=BATCH_SIZE, normalize_embeddings=True
    )
    return {"vectors": [[float(x) for x in v] for v in vectors]}


@main.post("/rerank")
def rerank(body: RerankIn):
    if not body.texts:
        return {"scores": []}
    scores = main.state.reranker.predict([(body.query, t) for t in body.texts])
    return {"scores": [float(s) for s in scores]}
