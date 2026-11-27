# Hardware measurements (P6-07)

Two machines: the **demo machine** (measured on 2026-11-26 and 27, first section), and a development machine without a usable graphics card (measured on 2026-11-25, from [Development machine](#development-machine) on).

## Demo machine

### Machine

| | |
|---|---|
| Laptop | Acer Nitro AN515-45 |
| Processor | AMD Ryzen 7 5800H, 16 logical processors |
| Memory | 16 GB (15.4 GiB usable) |
| Graphics card | NVIDIA GeForce RTX 3060 Laptop, 6 GB, driver 616.92 |
| Docker Desktop limit | 7.44 GiB of memory, 16 processors (WSL2) |
| Ollama | 0.40.18 |

### Mode

`light` on the graphics card (`MODE=light`, `docker-compose.gpu.yml`), with `make warm`.

`local` (`qwen2.5:7b`, context 16384) does not fit on 6 GB next to the embedding and re-ranking models (about 1.5 GB in half precision): Ollama put 22 of the 29 layers on the card, the rest ran on the processor, and the first question ended at the 60 s request limit (`agents.request_timeout_s`). The demo and the evaluation therefore run in `light` mode on this machine.

### Memory

Read with `nvidia-smi`, `ollama ps` and `docker stats --no-stream`, with both language models loaded and idle:

| | |
|---|---|
| Card | 5755 to 5961 MiB used out of 6144 MiB |
| `qwen2.5:3b` (context 16384) | 2.7 GB, 100 % on the card |
| `qwen2.5:1.5b` (narration, context 16384) | 1.5 GB, 100 % on the card |
| `llm` container | 4.27 GiB |
| `models` container | 1.52 GiB |
| `api` | 0.32 GiB; every other service under 0.1 GiB |
| Whole stack | about 6.3 GiB of the 7.44 GiB Docker may use (85 %) |

### Loading

| Model | First load after a start (`make warm`) | Already in memory |
|---|---|---|
| `qwen2.5:3b` | 97.1 s | 0.2 to 1 s |
| `qwen2.5:1.5b` | 13.5 s | 0.1 to 0.6 s |

The first load is longer than the 60 s a question may take, so before `make warm` and `OLLAMA_KEEP_ALIVE=-1` the first question after a start, or after 5 idle minutes, failed with `service_error`. With them, both models stay loaded (`ollama ps`: `UNTIL Forever`), and a question asked after 6 idle minutes was answered in 29.5 s.

### Speed (graphics card)

Measured through Ollama's `/api/chat`, context 16384, question « Explique en environ cent mots le rôle d'une loi de règlement. », models already loaded, one run each:

| Model | Generation | Measure |
|---|---|---|
| `qwen2.5:3b` | 101.8 tokens/s | 258 tokens in 2.5 s (8.5 s for the whole call) |
| `qwen2.5:1.5b` | 115.5 tokens/s | 79 tokens in 0.7 s (3.8 s for the whole call) |

### Complete questions

From `evaluation/run_eval.py` (71 questions, `light`, models loaded, contracts `real`, no grader), each question through the gateway as a user would ask it:

| Run | Commit | Search alone, mean | Answer, median | Answer, mean |
|---|---|---|---|---|
| `baseline-fixes` | `efd04dc` | 2.9 s | 13.6 s | 18.0 s |
| `baseline-checks` | `609e514` | 2.9 s | 13.0 s | 21.4 s |

The P6-07 target is under 10 s on average for a simple question: it is not met on this machine (median about 13 s). The answer itself takes a few seconds on the card; most of the time goes into the steps that call the model several times (planning, grading the passages, writing, checking each claim).

### Observations

- The disk matters. With `C:` at 98 % full, Docker Desktop stopped answering in the middle of a run (one question took 364 s, then every `docker` command failed). Windows also grew its paging file to 33.6 GB while the models ran. Keep at least 20 GB free.
- `docker compose down -v` deletes the model volumes as well as the databases; the models then have to be downloaded again (about 11 GB).
- On Windows, the connection to `localhost:8000` was reset 3 times in 71 questions during one run; `run_eval` resumes where it stopped.
- After rebuilding `ui` or `api`, restart `gateway`: nginx keeps the old addresses and answers 502.

### Not measured

- `qwen2.5:7b` entirely on the card: it does not fit in 6 GB with the other models.
- The narration model at 0.5B.
- `ocr` while reading a scanned page.

## Development machine

### Machine

| | |
|---|---|
| Processor | Intel Core i7-10750H, 12 logical processors |
| Memory | 15.7 GiB |
| Graphics card | NVIDIA GeForce GTX 1650 Ti Max-Q (not used: `llm` runs on the processor only, `gpus: all` is not set) |
| Docker Desktop limit | 7.61 GiB of memory, 12 processors |

### Method

- Memory: `docker stats --no-stream`, read right after the model answered.
- Speed: `ollama run <model> "<question>" --verbose` for the model alone (Ollama's default context, 4096), and `real_llm().chat(...)` from the `api` container for the real client (`llm.num_ctx` is 16384).
- Question used for the long measurements: « Explique en environ cent mots le rôle d'une loi de règlement. » (an ASCII version of it for the real client).
- One run per measurement: the figures are indicative, not averages.

### Memory

Whole stack (all ten services), memory used out of the 7.61 GiB Docker may use:

| State | `llm` | Whole stack |
|---|---|---|
| At rest, no model loaded | 0.33 GiB | about 1.9 GiB (25 %) |
| `qwen2.5:3b` loaded (`light` model) | 2.39 GiB | about 3.7 GiB (49 %) |
| `qwen2.5:1.5b` loaded (narration model) | 1.54 GiB | about 2.7 GiB (35 %) |
| `qwen2.5:7b` loaded (`local` model), context 4096 | 4.93 GiB | about 6.3 GiB (83 %) |
| `7b` and `1.5b` loaded together, context 4096 | 5.78 GiB | about 6.5 GiB (86 %) |
| `7b` (context 16384, as the app uses it) and `1.5b` loaded together | 5.99 GiB | about 6.4 GiB (85 %) |

The `models` service (embeddings and re-ranker) holds about 1.1 GiB at rest.

The `7b` takes 6.0 GB with the real context (16384) against 5.1 GB with the default one. When the stack came close to the limit, the memory of the other services dropped (for example `models` from 1.12 GiB to 0.26 GiB): Docker takes memory back from them, so the next call to such a service may be slower.

### Speed (processor only)

| Model | Loading | Generation | Measure |
|---|---|---|---|
| `qwen2.5:7b` | 18 to 72 s (cold) | 4.3 tokens/s | 97 tokens in 22 s |
| `qwen2.5:3b` | 19 s (cold), under 1 s when already in memory | 9.7 tokens/s | 210 tokens in 22 s |
| `qwen2.5:1.5b` | 3 s | 16.5 tokens/s | 59 tokens in 4 s |

Through the real client (`OllamaClient`, context 16384) with the `7b`: 31.5 s for an answer of 491 characters with the model already loaded, 88 s for the first call, which includes loading it.

The target of P6-07 is under 10 s for a simple question. A short answer of about a hundred words already takes about 30 s with the `7b` on this machine, before the search and the reading of the retrieved passages are added. On the processor alone, the target is not met with the `7b`.

### Observations

- With the `7b` and the narration model loaded together, the narration model took 8.3 s to read a 6-token prompt, against 0.5 s alone. This is one measure; it suggests the two models compete for the processor.
- The `3b` answered the long question wrongly (it described an administrative regulation instead of the law that closes a budget year). Quality in `light` mode has not been evaluated beyond this one question.

### Not measured

- The time of a complete question, from the interface to the answer: it needs the contracts set to `real`, which they are not yet in `config.yaml`.
- The narration model at 0.5B: it is not downloaded (`make models` fetches the three models of `config.yaml`).
- Use of the graphics card.
- The `light` mode with the real context (16384): the `3b` was measured with the default one.
- The memory of `models` and `ocr` while they work (embedding a document, reading a scan): only their memory at rest was read.
