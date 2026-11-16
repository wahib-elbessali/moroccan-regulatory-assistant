# Contributing

How we work on this repository. Read [`docs/architecture.md`](docs/architecture.md), [`docs/specs/00-shared.md`](docs/specs/00-shared.md) and your part's spec in [`docs/specs/`](docs/specs/) first; the plan is in [`docs/schedule.md`](docs/schedule.md).

## Setup (once)

Python 3.11 or newer.

```bash
git clone <repository URL>
cd <repository folder>
git config user.name  "First Last"
git config user.email "the email of your GitHub account"
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install                 # checks run before each commit
cp .env.example .env               # then fill in the values
pytest
```

## Fakes and real implementations

Every part reaches the others only through `get_*()` (`src/core/contracts/registry.py`). `config.yaml` → `contracts:` says, for each contract, whether `get_*()` returns the fake or the real implementation. Work against the other parts' fakes until their real versions are ready; moving to the real system changes `config.yaml`, not code.

## Branches and commits

- Never commit to `main`. One branch per task, named `type/short-description`: `feat/hybrid-search`, `fix/status-transition`, `test/p5-access-requests`, `docs/p2-schedule`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`, for example `feat(retrieval): add RRF fusion`.
  - Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `style`, `build`, `ci`, `chore`, `revert`.
  - Scope: the folder or part, e.g. `ingestion`, `retrieval`, `orchestrator`, `answer`, `api`, `llm`, `ui`, `contracts`.
- Keep branches short-lived: open a pull request as soon as one requirement or test works.

## Pull requests

1. Push your branch and open a pull request into `main`, using the template.
2. The **title** follows Conventional Commits: it becomes the commit message on `main`.
3. Say which requirements (`P2-12`, …) and acceptance tests (`T5`, …) of your spec the PR covers.
4. **Review:** a code owner of the changed files must approve (see [`.github/CODEOWNERS`](.github/CODEOWNERS)). You cannot approve your own pull request, and commits pushed after an approval need a new approval.
5. **CI must be green:**

   | Check | What it runs |
   |---|---|
   | `lint` | `ruff check .` and `black --check .` |
   | `types` | `mypy`: every implementation must match its Protocol |
   | `tests` | `pytest` with coverage, with PostgreSQL and Qdrant |
   | `pr-title` | The title follows Conventional Commits |
   | `secrets` | No password, token or key in the history |
   | `policy` | Repository rules |

6. The branch must be up to date with `main`; then **Squash and merge**.

## Shared contracts

`docs/specs/00-shared.md` and `src/core/contracts/` define everything shared between parts. A change to a shared contract:

- is made in **one** pull request that updates both the document and the code;
- is discussed first with the parts that use the contract;
- is approved by the coordination team.

Each part writes its own fake (`src/core/contracts/fakes/`) and its contract test (`tests/contracts/`).

## Rules that are never broken

- No secret in the repository: secrets go in `.env`, which is never committed.
- No document text, question or password in logs, error messages or test output.
- Never filter search results by role after the search, and never put access rules in a prompt.
- Never send corpus text, titles or metadata to the web search.

## Milestones

| Tag | Day | Content |
|---|---|---|
| `v0.1.0` | 2 (Wed 11-11) | Contracts and fakes merged |
| `v0.2.0` | 5 (Sat 11-14) | Each part works end to end with fakes |
| `v0.3.0` | 8 (Mon 11-23) | Full integration, mandatory tests green |
| `v1.0.0` | Sun 11-29 | Submission |
