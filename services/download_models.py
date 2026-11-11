"""Download every model into Docker volumes so `docker compose up` works offline (P6-04).

Run once with internet access: `make models`. Downloads go through throw-away containers on
Docker's default network, so no compose service is ever attached to the egress network for this.
Model names come from config.yaml.
"""

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OLLAMA_VOLUME = "rag_ollama_models"
HF_VOLUME = "rag_hf_cache"
TOKENIZER_REPO = "Qwen/Qwen2.5-7B-Instruct"  # the Qwen 2.5 family shares one tokenizer
TOKENIZER_FILES = ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ollama_models = list(
        dict.fromkeys([cfg["llm"]["model"], cfg["llm"]["model_light"], cfg["llm"]["narration_model"]])
    )

    # 1. Images: build local ones, pull the others.
    run(["docker", "compose", "build"])
    run(["docker", "compose", "--profile", "cloud", "pull", "--ignore-buildable"])

    # 2. Ollama models, into the volume served by the `llm` service.
    pulls = " && ".join(f"ollama pull {m}" for m in ollama_models)
    script = (
        "ollama serve >/dev/null 2>&1 & "
        "until ollama list >/dev/null 2>&1; do sleep 1; done; "
        f"{pulls}"
    )
    run(
        ["docker", "run", "--rm", "-v", f"{OLLAMA_VOLUME}:/root/.ollama"]
        + ["--entrypoint", "sh", "ollama/ollama:latest", "-c", script]
    )

    # 3. bge-m3, bge-reranker-v2-m3 and the Qwen tokenizer files, into the Hugging Face cache.
    code = (
        "from huggingface_hub import snapshot_download as d\n"
        f"d({cfg['models']['embedding']!r}, ignore_patterns=['onnx/*', '*.onnx*', 'imgs/*'])\n"
        f"d({cfg['models']['reranker']!r}, ignore_patterns=['onnx/*', '*.onnx*'])\n"
        f"d({TOKENIZER_REPO!r}, allow_patterns={json.dumps(TOKENIZER_FILES)})\n"
    )
    run(
        ["docker", "run", "--rm", "-v", f"{HF_VOLUME}:/cache", "-e", "HF_HOME=/cache"]
        + ["-e", f"CODE={code}", "python:3.11-slim"]
        + ["sh", "-c", 'pip install -q huggingface_hub && python -c "$CODE"']
    )
    print("Done. `docker compose up` now works without internet.")


if __name__ == "__main__":
    main()