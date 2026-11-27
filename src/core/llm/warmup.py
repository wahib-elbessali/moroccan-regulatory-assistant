"""Load the language models onto the card before the first question (``make warm``).

Ollama loads a model on its first request. Loading the answer model and the narration model takes
longer than ``agents.request_timeout_s``, so the first question after a start would fail. This
sends one short request to each model, with the context window the app uses (``llm.num_ctx``):
a request with another window would make Ollama load the model again.

The ``llm`` service keeps the models loaded (``OLLAMA_KEEP_ALIVE=-1`` in docker-compose.yml), so
this is needed once per start, not before every question.

    docker compose exec api python -m src.core.llm.warmup
"""

import sys
import time

from src.core.contracts.errors import ServiceError


def models_to_load(mode: str, model: str, model_light: str, narration_model: str) -> list[str]:
    """The answer model of ``mode`` and the narration model, each once, in that order."""
    answer = model_light if mode == "light" else model
    return list(dict.fromkeys([answer, narration_model]))


def main() -> int:
    from src.core.config import cfg

    from . import real_llm

    client = real_llm()
    names = models_to_load(cfg.mode, cfg.llm.model, cfg.llm.model_light, cfg.llm.narration_model)
    for name in names:
        started = time.perf_counter()
        try:
            client.chat([{"role": "user", "content": "ok"}], model=name, max_tokens=1)
        except ServiceError as exc:
            print(f"{name}: not loaded ({exc})", file=sys.stderr)
            return 1
        print(f"{name}: loaded in {time.perf_counter() - started:.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
