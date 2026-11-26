# Official evaluation runs

Step by step, for the person who runs the evaluation on the demo machine. The figures of the report
come from these runs. How the scores are computed: [README.md](README.md).

Everything runs from the repository root, in a bash shell (Git Bash on Windows). Run the steps in
order, with nothing else running on the machine: the times are only comparable then.

This is the first time these steps run on the demo machine. If a command fails, a check does not
give what is written, or a result looks wrong (every question failing, scores at 0, a run much
slower than expected), stop and send the command and its full output. Do not change the script or
the stack to make it work.

## 1. Prepare the machine

```
git checkout main
git pull
git status                      # must say "nothing to commit, working tree clean"
make models                     # once per machine; skip if the models are already downloaded
docker compose down -v          # starts from empty databases: only if nothing on this stack must be kept
make up-gpu
make seed
```

`docker compose down -v` deletes the stack's databases (accounts, uploads, loaded corpus), so the
corpus is loaded once, from the current `main`. If the stack holds something that must be kept,
ask before running it.

The first `make up-gpu` builds the GPU image of the models service (embeddings and re-ranker):
it needs the internet and takes a few minutes. Check that it uses the card:

```
docker compose logs models | grep "loaded on"     # must say "models loaded on cuda"
```

Check that `.env` has `ADMIN_USERNAME` and `ADMIN_PASSWORD`: the script logs in with them.

Then one question to load the models:

```
python evaluation/run_eval.py run --ids p1-03 --no-grader --out evaluation/results/warmup.jsonl --machine "warm-up"
```

Check that the language model is on the card too:

```
docker compose exec llm ollama ps                 # the PROCESSOR column must say "100% GPU"
```

If either check fails, stop there and send the output of both commands: the models do not all fit
on the card, and the setup must be fixed first, for the demo too.

In every command below, replace `MACHINE` with the GPU, the memory and the processor, for example
`"RTX 4060 8 GB, 32 GB RAM, i7-12700H"`.

## 2. The baseline

The whole set with the current `config.yaml`, grader on:

```
python evaluation/run_eval.py run --out evaluation/results/baseline.jsonl --machine "MACHINE"
```

Look at the time of the first ten questions. If a whole run would take more than 1 h 30, stop it
(Ctrl+C) and report the time per question before going on: the plan is then cut down. A stopped run
continues where it stopped when the same command is run again.

## 3. The search settings (search only)

These runs only call `POST /search`, so they are much shorter than the full runs. For each line
of the table: set the value in `config.yaml`, restart the api, run the command.

```
docker compose restart api
docker compose ps api           # wait until it says "healthy"
```

| Run | Change in `config.yaml` | Command |
|---|---|---|
| `chars300` | none (the current values) | `python evaluation/run_eval.py run --search-only --out evaluation/results/chars300.jsonl --machine "MACHINE"` |
| `chars500` | `rerank_max_chars: 500` | same command, `--out evaluation/results/chars500.jsonl` |
| `chars2000` | `rerank_max_chars: 2000` | same command, `--out evaluation/results/chars2000.jsonl` |
| `topn10` | `rerank_max_chars: 300`, `rerank_top_n: 10` | same command, `--out evaluation/results/topn10.jsonl` |
| `topn20` | `rerank_max_chars: 300`, `rerank_top_n: 20` | same command, `--out evaluation/results/topn20.jsonl` |

After `topn20`, put `config.yaml` back: `git checkout -- config.yaml`.

## 4. The agent settings (full runs)

Same procedure, with the grader on. Each run changes one value from the original `config.yaml`;
put it back (`git checkout -- config.yaml`) before the next one.

| Run | Change in `config.yaml` | Command |
|---|---|---|
| `iter1` | `max_iterations: 1` (no reformulation) | `python evaluation/run_eval.py run --out evaluation/results/iter1.jsonl --machine "MACHINE"` |
| `sub1` | `max_sub_questions: 1` (no splitting) | `python evaluation/run_eval.py run --type multi_part --out evaluation/results/sub1.jsonl --machine "MACHINE"` |

`sub1` runs only the multi-part questions, the ones splitting is for. This keeps the run short.

## 5. The smaller model

`config.yaml` back to its original values (`git checkout -- config.yaml`). The light mode is set
when the stack starts, not in `config.yaml`:

```
MODE=light docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait
python evaluation/run_eval.py run --ids p1-03 --grader-model qwen2.5:7b --out evaluation/results/warmup-light.jsonl --machine "warm-up"
docker compose exec llm ollama ps                 # both models listed, "100% GPU"
python evaluation/run_eval.py run --out evaluation/results/light.jsonl --grader-model qwen2.5:7b --machine "MACHINE"
```

The warm-up question loads the small model and the grader, so the timed run does not include
loading them. `--grader-model qwen2.5:7b` keeps the same grader as the other runs, so only the
answers change. If `ollama ps` does not list both models on the card, stop there and send its
output.

Then back to the normal stack:

```
make up-gpu
git status                      # must be clean again
```

## 6. What to send

Zip the `evaluation/results/` folder and send it over. It should hold these eleven files:

```
baseline.jsonl  chars300.jsonl  chars500.jsonl  chars2000.jsonl  topn10.jsonl  topn20.jsonl
iter1.jsonl     sub1.jsonl      light.jsonl     warmup.jsonl    warmup-light.jsonl
```

Add a few lines with anything unusual: a GPU check that failed, an error, a run that was stopped
and started again, something else running on the machine. Do not commit the results: the report
is written from them.

Each file starts with the setup it was run with (commit, configuration, machine, GPU), so nothing
else is needed. To look at the results before sending them:

```
python evaluation/run_eval.py summary evaluation/results/baseline.jsonl
python evaluation/run_eval.py compare evaluation/results/chars300.jsonl evaluation/results/chars500.jsonl evaluation/results/chars2000.jsonl
```
