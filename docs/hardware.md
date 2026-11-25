# Hardware measurements (P6-07)

Measured on 2026-11-25 on a **development machine**, not on the demo machine. The numbers show what the stack needs and how fast it is on this machine; they must be measured again on the demo machine before the demo.

## Machine

| | |
|---|---|
| Processor | Intel Core i7-10750H, 12 logical processors |
| Memory | 15.7 GiB |
| Graphics card | NVIDIA GeForce GTX 1650 Ti Max-Q (not used: `llm` runs on the processor only, `gpus: all` is not set) |
| Docker Desktop limit | 7.61 GiB of memory, 12 processors |

## Method

- Memory: `docker stats --no-stream`, read right after the model answered.
- Speed: `ollama run <model> "<question>" --verbose` for the model alone (Ollama's default context, 4096), and `real_llm().chat(...)` from the `api` container for the real client (`llm.num_ctx` is 16384).
- Question used for the long measurements: « Explique en environ cent mots le rôle d'une loi de règlement. » (an ASCII version of it for the real client).
- One run per measurement: the figures are indicative, not averages.

## Memory

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

## Speed (processor only)

| Model | Loading | Generation | Measure |
|---|---|---|---|
| `qwen2.5:7b` | 18 to 72 s (cold) | 4.3 tokens/s | 97 tokens in 22 s |
| `qwen2.5:3b` | 19 s (cold), under 1 s when already in memory | 9.7 tokens/s | 210 tokens in 22 s |
| `qwen2.5:1.5b` | 3 s | 16.5 tokens/s | 59 tokens in 4 s |

Through the real client (`OllamaClient`, context 16384) with the `7b`: 31.5 s for an answer of 491 characters with the model already loaded, 88 s for the first call, which includes loading it.

The target of P6-07 is under 10 s for a simple question. A short answer of about a hundred words already takes about 30 s with the `7b` on this machine, before the search and the reading of the retrieved passages are added. On the processor alone, the target is not met with the `7b`.

## Observations

- With the `7b` and the narration model loaded together, the narration model took 8.3 s to read a 6-token prompt, against 0.5 s alone. This is one measure; it suggests the two models compete for the processor.
- The `3b` answered the long question wrongly (it described an administrative regulation instead of the law that closes a budget year). Quality in `light` mode has not been evaluated beyond this one question.

## Not measured

- The time of a complete question, from the interface to the answer: it needs the contracts set to `real`, which they are not yet in `config.yaml`.
- The narration model at 0.5B: it is not downloaded (`make models` fetches the three models of `config.yaml`).
- Use of the graphics card.
- The `light` mode with the real context (16384): the `3b` was measured with the default one.
- The memory of `models` and `ocr` while they work (embedding a document, reading a scan): only their memory at rest was read.
- The demo machine.
