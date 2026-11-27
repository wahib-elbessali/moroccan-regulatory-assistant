# Moroccan Regulatory Assistant

An agentic RAG assistant that answers questions about Moroccan regulation (laws, decrees, the Bulletin Officiel, internal circulars) from a corpus of Arabic documents.

## What it does

- Answers questions asked in Arabic, French or Darija, in standard Arabic or French.
- Splits complex questions into sub-questions, searches the corpus, checks that the passages are relevant, and searches again with other words when they are not.
- Backs every claim of the answer with a citation (document, article, page, excerpt), each one checked against the source text.
- Gives a confidence score, and says it doesn't know when the documents available to the user don't cover the question.
- Shows its reasoning live while it works.

## Access and sovereignty

- Three roles: citizens see public law and their own uploads, jurists also see internal documents, administrators manage accounts and never see document content.
- Access rules are enforced inside the search itself, before any document is retrieved.
- Everything runs locally (language models, embeddings, databases); the system works with the internet off.
- An optional web search only ever receives a generic rewording of the question, checked by a filter that blocks any text from internal documents.

## Architecture

| Part | Role |
|---|---|
| Ingestion | Extracts and cleans Arabic text (with OCR for scans) and splits documents by article |
| Retrieval | Hybrid search (vectors + BM25) with re-ranking and the access filter |
| Orchestration | The agent graph: planning, grading, reformulation, web decision |
| Answer | Writes the cited answer, verifies every claim, computes the confidence |
| Identity and access | API, authentication, roles, document rights, audit log |
| Sovereignty | Local models, web isolation, leak filter, Docker setup |
| Interface | Chat, document management and administration screens, right-to-left display |

Details: [`docs/architecture.md`](docs/architecture.md).


## Running the stack

You need Docker with Compose. The commands below are `make` targets; on Windows without `make`, run the command in the last column instead.

| Target | What it does | Without `make` |
|---|---|---|
| `make models` | Downloads every model once (language models, embeddings, re-ranker, tokenizer files, OCR) into Docker volumes. Needs internet; after it has run, the stack starts with the internet off. | `python services/download_models.py` |
| `make up` | Starts the whole stack in `local` mode and waits until every service is healthy. | `docker compose up -d --wait` |
| `make up-light` | Same, in `light` mode: a smaller language model, for modest machines. | cmd: `set MODE=light`, then `docker compose up -d --wait`, then `set MODE=`. PowerShell: `$env:MODE="light"; docker compose up -d --wait; $env:MODE=""` |
| `make up-gpu` | Same as `make up` (`local` mode), and gives the NVIDIA graphics card to the language models and to the embedding and re-ranking models, through the file `docker-compose.gpu.yml`. Needs an NVIDIA card with its driver installed and GPU support in Docker Desktop. The first `make up-gpu` builds the GPU image of the models service (needs the internet, a few GB). It ends with `make warm`, so the models are loaded onto the card (about two minutes) before the first question. | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait` |
| `make up-cloud` | **Development only, never for the demo.** Same as `make up`, in `cloud` mode: the language model is a cloud API reached through `cloud-gateway` (embeddings, re-ranking and OCR stay local). Needs `ALLOW_CLOUD_LLM=true` and `CLOUD_LLM_BASE_URL`, `CLOUD_LLM_API_KEY`, `CLOUD_LLM_MODEL` in `.env` (any OpenAI-compatible API); without both switches the api refuses to start a cloud client (`cloud mode not allowed`). | cmd: `set MODE=cloud`, then `docker compose --profile cloud up -d --wait`, then `set MODE=` |
| `make warm` | Loads the answer model and the narration model onto the card, so the first question does not time out while they load. The `up` targets run it; the models then stay loaded (`OLLAMA_KEEP_ALIVE=-1`). Run it by hand after a plain `docker compose up`. It uses `llm.num_ctx` (16384): a request with another context window would make Ollama load the model again. | `docker compose exec -T api python -m src.core.llm.warmup` |
| `make down` | Stops and removes the containers. The volumes (databases, models, uploads) are kept. | `docker compose down` |
| `make test-isolation` | Checks that only `web-search` and `searxng` can reach the internet (tests T1 to T3). The stack must be up. | `pytest tests/sovereignty/test_network_isolation.py -v` |
| `make seed` | Loads the corpus of `data/raw` through the ingestion command line, inside `api`, then marks the public documents as non-blocking for the web leak filter. The stack must be up. `make seed OWNER=<uuid>` sets the owner of the uploaded rows. | `docker compose exec api python -m src.ingestion.cli seed --owner <uuid> --raw-dir /app/data/raw`, then `docker compose exec -T api python - < scripts\leak_unblock_public.py` |

First start:

1. Copy `.env.example` to `.env` and fill in the values. `.env` is never committed.
2. `make models` (once, with internet).
3. `make up`, then `make seed`.

The gateway publishes port 3000 (interface) and port 8000 (API) on the host; every other service stays on a network with no published port. Details of the three networks: [`docs/specs/P6-sovereignty.md`](docs/specs/P6-sovereignty.md).

## Run the real application

The Compose stack builds the P7 interface and configures the API to use the real Ollama, Qdrant,
retrieval, ingestion and answer services. After creating `.env` from `.env.example` and setting
the required secrets, run `make models` once while downloads are available, then `make up-light`.
Open <http://localhost:3000> and sign in with the configured admin or an existing reader/editor
account. `config.yaml` keeps its fake defaults for local tests; Compose selects real services
without changing it.

For answers grounded in the local corpus, seed the documents with
`make seed OWNER=<existing-user-id>` and wait for ingestion to finish. Public documents are
available to readers and editors; internal documents are available to editors only.
