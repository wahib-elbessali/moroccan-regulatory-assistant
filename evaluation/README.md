# Evaluation

The evaluation set and the script that scores the system on it (F-EVA-01, F-EVA-02).

| File | What it is |
|---|---|
| `questions/p1.jsonl` … `p6.jsonl` | The questions each group wrote, one JSON object per line |
| `build_dataset.py` | Checks the group files and builds `dataset.jsonl` |
| `dataset.jsonl` | The evaluation set: 71 questions |
| `run_eval.py` | Asks the questions to a running stack and scores the answers |
| `official-runs.md` | Step by step for the runs whose figures go in the report |

## The questions

Each line has 11 fields:

| Field | Values |
|---|---|
| `id` | `p<N>-<NN>`, unique |
| `group` | `P1` … `P7` |
| `question` | the question, as a user would type it |
| `language` | `ar`, `fr` or `darija` |
| `role` | `lecteur`, `editeur` or `admin`: the user who asks |
| `use_web` | `true` or `false` |
| `type` | `simple`, `multi_part`, `french`, `darija`, `access` or `out_of_corpus` |
| `expected_status` | `answered` or `unknown` |
| `expected_sources` | `[{"source_file": "public/adala_001.pdf", "article": "المادة 12"}]`; empty for `unknown` |
| `must_not_cite` | files this user must never get, same shape; the article is not used |
| `reference_answer` | the correct answer, from the article; empty for `unknown` |

`source_file` is the `file` column of `data/raw/manifest.csv`.

## Building the set

```
python evaluation/build_dataset.py
```

The script stops and lists every problem if a line is invalid (missing field, unknown value, a file
that is not in the manifest, an id used twice, an `answered` question without sources or reference
answer). Otherwise it:

- applies the corrections found when the questions were checked against the PDFs: p4-11's
  `language` is `fr` (the question is in French), and p1-07's reference answer lists the three
  bodies of article 11;
- drops the questions several groups wrote: p3-02, p6-01 and p5-09 (same as p1-05), p4-04 and p2-02
  (same as p1-03), p5-05 (same as p3-01), p5-06 (same as p4-06), p2-09 (same as p3-03). The same
  question in another language is kept;
- writes `dataset.jsonl` and prints the counts per group, type, role, language and status.

## Running the evaluation

Start the stack and load the corpus first (`make up`, `make up-gpu` or `make up-light`, then `make seed`). Then,
from the repository root:

```
python evaluation/run_eval.py run --out evaluation/results/baseline.jsonl --machine "short description"
```

| Option | Use |
|---|---|
| `--group P2 P3` | only these groups' questions |
| `--type simple access` | only these types |
| `--ids p6-03 p6-07` | only these questions |
| `--no-grader` | skip faithfulness and relevance (faster) |
| `--search-only` | only `POST /search`: hit@10, MRR, search time and leaks; no answer, no grader (much faster) |
| `--grader-model qwen2.5:7b` | grade with another model than the answer model |
| `--compose "docker compose -p name"` | the compose command of the running stack, if not the default |

A stopped run continues where it stopped: run the same command with the same `--out`. The script
reads the admin login from `.env` and creates two test users, `eval_lecteur` and `eval_editeur`,
the first time.

The results file starts with one line describing the setup (date, git commit, files changed in
`src/` or `config.yaml`, the configuration the api runs with, mode, machine, GPU), then one line
per question. To print the tables again, or to compare runs:

```
python evaluation/run_eval.py summary evaluation/results/baseline.jsonl
python evaluation/run_eval.py compare evaluation/results/baseline.jsonl evaluation/results/tuned.jsonl
```

`summary` prints the scores overall, per type, per group and per role, and lists the questions to
look at. `compare` takes two results files or more and prints them side by side: the settings that
differ between the runs (read from the running api, not from the file on disk), the scores, and
the questions whose status, search rank or citation changed. Only the questions present in every
run are counted.

## Ablation study

Each run changes one setting of `config.yaml` and keeps everything else, so the difference in the
scores is what that setting brings. The api reads `config.yaml` when it starts:

1. change the value in `config.yaml`;
2. `docker compose restart api` and wait until it is healthy;
3. run the evaluation with its own `--out`;
4. put `config.yaml` back (`git checkout -- config.yaml`) once all the runs are done.

The settings that change only the search are run with `--search-only`; the others need the full
run. `config.yaml`'s current values are the baseline.

| Setting | Values | What it shows | Run |
|---|---|---|---|
| `retrieval.rerank_max_chars` | 300, 500, 2000 (whole article) | how much of each passage the re-ranker needs to read | `--search-only` |
| `retrieval.rerank_top_n` | 10, 16, 20 | how many fused passages are worth re-ranking | `--search-only` |
| `agents.max_iterations` | 1 (no reformulation), 3 | what reformulation brings | full |
| `agents.max_sub_questions` | 1 (no splitting), 3 | what splitting the question brings, on the multi-part questions | full |
| `mode` | `local` (7B), `light` (3B) | the cost of the smaller model | full |

Example for the re-ranker input:

```
python evaluation/run_eval.py run --search-only --out evaluation/results/chars300.jsonl --machine "..."
python evaluation/run_eval.py run --search-only --out evaluation/results/chars500.jsonl --machine "..."
python evaluation/run_eval.py run --search-only --out evaluation/results/chars2000.jsonl --machine "..."
python evaluation/run_eval.py compare evaluation/results/chars300.jsonl evaluation/results/chars500.jsonl evaluation/results/chars2000.jsonl
```

All the runs of one study are made on the same machine, one after the other, with nothing else
running: the times are only comparable then. `mode` is set by `make up` / `make up-light`, not by
`config.yaml`.

## How each question is scored

Everything goes through the HTTP API, as a real user would, with the token of the question's role.

| Score | How |
|---|---|
| `hit@10` | an expected source is in the first 10 results of `POST /search` |
| `MRR` | 1 / rank of the first expected source in those results (0 if none), averaged |
| `status ok` | the status of the `POST /ask` answer is `expected_status` |
| `answered+cited` | for questions that should be answered: the answer is `answered` and one of its citations is an expected source |
| `unknown ok` | for questions that should get "I don't know": they did |
| `faithful` | grader, 0 / 0.5 / 1: every statement of the answer is in the cited passages |
| `relevant` | grader, 0 / 0.5 / 1: the answer gives the facts of the reference answer and contradicts none |
| `leaks` | questions where a `must_not_cite` file appears in the search results or in the citations; must be 0 |
| `errors` | questions where `/search` or `/ask` failed |
| `search s` | median time of `POST /search`, in seconds |
| `s mean`, `s median` | time of the whole `/ask` answer, in seconds |

**Matching a source.** A search result or a citation matches an expected source when its file is
the expected file and its article is the expected article. Article labels are compared after
`normalize_ar`, with ordinal words read as numbers, so "المادة الأولى" and "المادة 1" match. For the
internal documents any article of the right file counts: their articles repeat the same text, so
the system cannot tell which one the question meant.

**Leaks** are checked by file only: a lecteur must get nothing at all from an internal document.

**The grader** runs inside the `api` container, because the model server is not reachable from
outside, and makes two separate calls, so that "is it true" and "is it complete" are not mixed:

- faithfulness: the answer and, for each citation, the full text of the cited article (from the
  search results, or the cited excerpt when that article is not among them). It checks only what
  the answer says, not what it leaves out;
- relevance: the question, the reference answer and the answer.

It grades only questions that should be answered and were. It is the same model that writes the
answers, which favours its own wording, and a small model makes mistakes on some answers: the
scores are for comparing runs on the same machine, not absolute values.

## Notes for running on other machines

- **Without a GPU**, the re-ranker runs on the processor: one search takes about 10 to 30 seconds
  and an answer several minutes, so run a few questions with `--ids` or `--group`, not the whole
  set. If searches fail with 504 (the gateway gives every route except `/ask` 60 seconds), add
  `proxy_read_timeout 600s;` to the `location /` block of the 8000 server in
  `services/gateway/default.conf`, locally only, and restart the gateway.
- **The first question after the stack starts is slow** (models loading). For timing, ask one
  question before the run.
- The official runs, whose figures go in the report, are made on the demo machine with the corpus
  loaded once from the current `main`: [official-runs.md](official-runs.md).
