# Contributing to docket-cli

Thank you for your interest in contributing to docket-cli! This document provides guidelines and instructions for contributing to this project.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- A clear and descriptive title
- Steps to reproduce the issue
- Expected behavior
- Actual behavior
- Your environment (OS, Python version)
- Any relevant logs or error messages

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- A clear and descriptive title
- Detailed description of the proposed feature
- Use case and motivation
- Any implementation ideas (optional)

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the test suite (`./tests/run-all-tests.sh`)
5. Run the CI gates (lint, format, types, pytest, golden, spec validation — see [Testing](#testing))
6. Commit with descriptive messages (`git commit -m 'Add amazing feature'`)
7. Push to your branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## Development Setup

docket is a Python CLI (Typer + Rich + Pydantic). Use [`uv`](https://github.com/astral-sh/uv)
for environment management.

```bash
# Clone your fork
git clone https://github.com/YOUR-USERNAME/docket.git
cd docket

# Install the package and dev tooling (ruff, mypy, pytest) into a venv
uv sync --all-extras --dev

# Create a feature branch
git checkout -b feature/your-feature

# Make changes and test
./tests/run-all-tests.sh
```

## Code Style Guidelines

### Python Conventions

- Target Python 3.11+; type-annotate everything (the suite is checked with `mypy --strict`)
- Format and lint with `ruff` (`uv run ruff format .` / `uv run ruff check .`)
- Use meaningful names (snake_case for functions/vars, PascalCase for classes/Pydantic models)
- Keep functions focused; prefer pure functions in a context's `domain/`
- Comments explain *why* something is shaped the way it is — never what it does or when it
  arrived. No card ids, phase numbers, dates or "used to" narration; git history holds those.
  A docstring is one line unless it states a contract (what is guaranteed, what fails closed).
  `uv run python scripts/maint/comment_lint.py --check src tests` reads this rule

### Package layout (one package per business context; ADR 0030, D-66)

All command logic lives in the `docket` package under `src/docket/`. The rule new code follows
is **one package per business context, at most two levels inside it**, and the dependencies
between packages are import-linter contracts, not prose.

**The target.** `src/docket/` holds twelve context packages (`kernel`, `tasks`, `pipeline`,
`hops`, `agent`, `governance`, `sandbox`, `teams`, `models`, `observability`, `operator`,
`platform`), `interfaces/` (`cli`, `http`, `mcp`, `telegram`) and one `bootstrap.py`. Inside a
context there are at most two levels: `domain/`, `application/` and `adapters/` where the context
needs them, flat otherwise. The full tree is "Target layout" in
[ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md).

**Allowed dependencies** (the ADR's table; `tests/architecture/` enforces it from stage 2 of
Phase 46 on):

| From | May import |
|---|---|
| `kernel` | nothing in `docket` |
| `<context>/domain` | `kernel`, its own `domain` |
| `<context>/application` | `kernel`, its own `domain` and `ports`, any module of a context below it in the layer order (amended 2026-10-23) |
| `<context>/adapters`, `platform`, `sandbox` | `kernel`, `platform`'s `__init__`, the ports and domain types they implement |
| `agent` | `kernel`, `platform`'s `__init__` (amended 2026-10-23), its own modules |
| `interfaces` | `kernel`, `bootstrap`, any context (amended 2026-10-23) |
| `bootstrap` | everything |

The layer order, bottom to top (amended 2026-10-23): `platform` < `governance` < `agent` < `models`
< `observability` < `pipeline` < `teams` < `sandbox` < `operator` < `tasks` < `hops`.

So a domain package never imports an adapter, a context imports only contexts below it in that
order (an import of one above it is the violation the baseline records, and the baseline only
shrinks), and nothing imports `interfaces/`. Function-local imports of `docket.*` are
forbidden because they hide cycles; the existing ones are a baseline that only shrinks. A module
over **700 lines is a defect**, and the ceiling ratchets down to it from today's largest module.

**What holds today.** The code has moved: `cli/`, `core/` and `edges/` no longer exist, the CLI
is `interfaces/cli/` and the HTTP control plane is `interfaces/http/`, and this section is the
whole rule. The import contracts live in `tests/architecture/`.

Two invariants matter most and are enforced by tests rather than convention alone; they do not
move with the refactor:

1. **Every tool call goes through the single tool dispatcher** (`dispatch_tool`, today in
   `agent/tools/registry.py`). docket's governance stack — the policy engine, the approval store, the
   high-risk classifier, the audit log — only means anything if there is exactly one place a tool
   can execute from. An AST test enforces this:
   `tests/unit/agent/tools/test_registry.py::test_only_the_chokepoint_imports_the_handler_module`.
2. **docket-owned JSON goes through the one store module** (today `platform/store.py`: atomic write
   + filelock + `.bak` rotation + 0600 perms) — never write those files directly. The one
   documented exemption is append-only JSONL (`observability/trace.py`, `governance/audit.py`), which writes
   directly by design.

Where things go today:

- **Commands** are Typer functions in `src/docket/interfaces/cli/` — register them in
  `interfaces/cli/app/__init__.py`, with the command bodies in `interfaces/cli/commands/<group>.py`
  (e.g. `commands/pod.py`, `commands/task.py`) and the Rich output in `interfaces/cli/render/`.
- **Domain logic / helpers** go in the owning context's `domain/` or `application/` — Pydantic models
  in `teams/models.py`, plus pure services (policy resolution in `governance/`, trace in
  `observability/`, the turn loop and the tool registry in `agent/`, the model-endpoint port in
  `models/`).
- **I/O and side effects** go in a context's `adapters/`, in `platform/` or in `sandbox/`:
  - docket-owned JSON (`.docket-meta.json`, etc.) is read/written **only** through
    `platform/store.py`, per invariant 2 above.
  - the model endpoint (`models/adapters/openai_http.py`), MCP client (`agent/tools/mcp_client.py`),
    Telegram Bot API (`interfaces/telegram/client.py`), the sandboxed-exec/fetch tool handlers
    (`agent/tools/builtins/toolbox.py`, `platform/fetch.py`), and shell-outs to `docker` / `git`
    (`platform/git.py`, `platform/process.py`, `sandbox/docker.py`) each live behind their own
    adapter module — no other module should know their wire formats.
- **Tests** go in `tests/` (see [Testing](#testing)); **specs** go in `specs/`;
  **documentation** goes in `docs/`.

## Testing

All contributions must include appropriate tests:

- Tests are placed by lane, named by module, per `specs/test-framework.md` §"Lanes and
  placement": `tests/unit/` mirrors `src/docket/` one file per module, `tests/integration/<context>/`
  covers cross-module, real-socket or real-process behaviour, one folder per context, `tests/guards/` holds AST/layout invariants,
  and `tests/agent/` holds checks on prose, release artifacts or agent hook scripts — that lane
  is budgeted, never the default suite, and runs in its own CI job
  (the directories of today; ADR 0030 replaces them with a mirror of the code, lanes as pytest
  markers, and `tests/{fixtures,contracts,e2e,architecture,release}/` as the only directories
  that do not mirror a module — see that section for what holds now and what Phase 46 moves)
- New commands also get a spec under `specs/` and golden-parity coverage where output is frozen

For scale, so you know what you're getting into: **6,185 tests** in the default suite
(`tests/unit/`, `tests/integration/`, `tests/guards/`; the budgeted agent lane in `tests/agent/`
runs separately), **~53,690 lines** of Python in the shipped package, **32 specifications**
validated in CI, and **10 commands** in the [command reference](docs/commands.md).
`scripts/metrics.py --check` computes these from the tree on every CI run, so this paragraph
cannot silently go stale.

Run the full aggregator before submitting:

```bash
# Observable full workflow (temporary state + deterministic loopback model; no credentials)
uv run python scripts/smoke_workflow.py

# Opt-in realistic memory-backed repair with genuine inference on port 8081
uv run python scripts/smoke_workflow.py --live-model
DOCKET_RUN_LIVE_SMOKE=1 uv run pytest -q tests/integration/product/smoke

# Smaller live infrastructure-only scenario retained for diagnosis
uv run python scripts/smoke_workflow.py --live-model --scenario basic

# All tests (pytest + golden parity)
./tests/run-all-tests.sh

# pytest suite only (default lanes: unit, integration, guards)
uv run pytest   # 6,185-test Python suite

# agent lane only (prose, release artifacts, agent hook scripts; own CI job)
uv run pytest tests/agent

# Golden parity suite (byte-for-byte CLI output)
bash tests/golden/run.sh verify-all

# CLI reference drift check (docs/commands.md is generated from the Typer registry)
uv run python scripts/gen_cli_docs.py --check
# Recipe library drift check (docs/recipes.md is generated from the shipped recipes)
uv run python scripts/gen_recipe_docs.py --check

# Docs site, strict (a dead link fails the build; mkdocs is not a project dependency)
uvx --with mkdocs-material --with 'mkdocstrings[python]' mkdocs build --strict
```

### How much to run, and when

The same budget as ROADMAP §4 ("Definition of Done"):

- **Each commit:** `ruff check`, `ruff format --check`, `mypy src` and `pytest --co` (about 10 s).
- **While changing code:** only the tests of what you changed, by path.
- **Once per change, before merging:** the default suite in parallel (`uv run pytest -n auto --dist
  loadfile`, about a minute); fix by cause and re-run only what failed.
- **Once per phase close or release:** everything below, plus
  `scripts/maint/pytest-without-sandbox.sh` (the suite as a host with no sandbox backend sees it)
  and a real run.

A check that fails again after one fix is a finding to report, not a loop to keep iterating.

### CI gates

These all gate CI and must pass locally before opening a PR:

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy src              # strict type check
uv run pytest                # default lanes: unit, integration, guards
uv run pytest tests/agent    # agent lane (CI job `agent-lane`)
bash tests/golden/run.sh verify-all   # golden parity
./scripts/validate-specs.sh  # spec format validation
uv run python scripts/metrics.py --check            # this doc's metric-drift guard (see above)
uv run python scripts/gen_cli_docs.py --check       # docs/commands.md drift (CI job `docs`)
uv run python scripts/gen_recipe_docs.py --check    # docs/recipes.md drift (CI job `docs`)
uv run python scripts/render-doc-assets.py --check  # README screenshot/GIF drift guard (run by the agent lane)
uv run python scripts/release_journey.py            # exact-wheel first-turn release rehearsal
```

## Adding a New Command

docket follows spec-driven development (see [SSD-WORKFLOW.md](SSD-WORKFLOW.md)). To add a
command:

1. Write a spec under `specs/functional/<command>.spec.md`.
2. Register the command as a Typer function under `src/docket/interfaces/cli/` (registered in
   `interfaces/cli/app/__init__.py`, body in `interfaces/cli/commands/<group>.py`) and wire its help
   into `interfaces/cli/render/help.py`.
3. Put domain logic in the owning context and any I/O behind that context's `adapters/` or in
   `platform/` (`platform/store.py` for docket JSON, `platform/git.py` and `platform/process.py`
   for shell-outs to `git` and the host).
4. Add pytest coverage in the unit file named for the module (see [Testing](#testing)), and
   golden cases if the output is frozen.
5. Run the CI gates (see [Testing](#testing)).

## Documentation

- Update relevant documentation in `docs/`
- `docs/commands.md` is generated from the Typer registry by `scripts/gen_cli_docs.py` and must
  never be hand-edited; put command prose in the command's own help string (`interfaces/cli/render/help.py` or the
  Typer function) and regenerate with `uv run python scripts/gen_cli_docs.py`
- `docs/recipes.md` is generated from the shipped recipes by `scripts/gen_recipe_docs.py`; put
  recipe prose in the recipe's own `README.md` and `pod.yaml` `description`, then regenerate with
  `uv run python scripts/gen_recipe_docs.py`
- Update README.md if adding major features
- Keep comments to rationale only (see [Python Conventions](#python-conventions)) — command prose
  belongs in the Typer help strings, not in code comments

## Rules that have cost this project time when ignored

Seven rules, each written down because breaking it cost real work here.

1. **A guard is not evidence until you have seen it fail.** Plant the drift, watch the check go
   red, restore it, watch it go green, and put that in the pull request. Guards that verified the
   wrong set have shipped here more than once, and a guard you only ever saw pass proves nothing.
2. **Never edit a counting script or regenerate a golden to make a claim agree.** `scripts/
   metrics.py` and `scripts/validate-specs.sh` are the guards, not the claim. Regenerate a golden
   only when a change deliberately alters CLI surface, or when the old string was factually false,
   and explain the diff line by line either way.
3. **Prove "pre-existing" before claiming it.** Check the base commit out in a clean worktree and
   run there. A `git stash` restores neither deleted files nor a changed environment, so it is not
   a baseline. Run `uv sync --all-extras` first: a missing `anyio` produces three phantom mypy
   errors that are not real.
4. **Isolation is part of done.** The suite has leaked into a developer's real `~/.docket` three
   times, once displacing the whole environment with fixture agents. Every path docket writes is a
   `Home` field or property in `kernel/home.py`, every test runs inside the autouse
   `use_home` home in `tests/conftest.py`, and a test choosing its own home enters
   `use_home(Home(root))` rather than patching constants;
   `tests/guards/test_docket_home_isolation.py` checks every path the current `Home` hands out. A test must not depend on the host's sandbox either: one that turns isolation on
   stubs `sandbox_availability` or skips with a named reason when it needs a real backend, and
   `scripts/maint/pytest-without-sandbox.sh` runs the suite as a host with no usable backend
   (`DOCKET_SANDBOX_PROBE=none`, like a stock CI container). Forcing `DOCKET_SANDBOX_BACKEND=none` is not that check; it hid 40 macOS
   failures behind a fixture that deleted the variable.
5. **A gap list is a claim about the tree and decays like one.** Re-verify before scheduling work
   against it. Work has been scheduled here, and kept over better candidates, against a gap that had
   already been closed the day it was written down.
6. **Scrub every diff before committing.** Real client names, home-directory paths and usernames do
   not belong in a public repository. Commit subjects follow `Type: description` with a detailed
   body, ASCII only.

7. **Nothing is kept for the past.** docket has no users, so there is nothing from an earlier
   version to protect. A removed or renamed command, flag, alias, route, persisted shape or
   behaviour is deleted in the same change that replaces it, together with its tests, its spec
   text and its documentation. No alias table, no retirement notice, no "did you mean the old
   name", no migration, no hidden command, no deprecated no-op flag, no `_REMOVED` map. A
   retired name is an ordinary unknown command (exit 2), and `CHANGELOG.md` is the only record.
   The compatibility layers this project carried (a removed-command map, an alias table, a
   `--debug` no-op, `gates enable/disable` stubs, `editRights` on the wire) each had a writer,
   a reader in `cli/` and no consumer on the live path; they were purged on 2026-10-03 and the
   rule became a decision on 2026-10-07 (ROADMAP D-57, ADR 0022). It stands until docket has an
   installed base, which is a fact about the world and not a release number. One thing is not
   legacy: a current format that happens to be older than another (canonical policy JSON
   without `kind:`).

### Comments and docstrings

A comment answers **why**, never **when** or **from where**. Delete card ids, phase numbers, dates,
provenance, and narration of what a deleted thing used to do — git history and the roadmap hold all
of it. Keep any sentence whose loss would let someone introduce a bug: why a constant has its
value, why something fails closed, why two similar things differ deliberately. When in doubt, keep.

`scripts/maint/comment_lint.py --check <paths>` reports this, and a ratchet test holds the counts
at a committed baseline that may only fall. Its exit code covers archaeology only; the
docstring-length budget is reported but enforced separately by
`tests/guards/test_comment_hygiene.py`, so a green lint run says nothing about the budget. Rationale
placed in a `#` comment above a `def` is not counted against that budget, which is the idiom to
reach for when an explanation genuinely needs the room.

**A comment describing a constraint is not code applying it.** `TELEGRAM_REQUEST_TIMEOUT_S`
documented an invariant, was environment-overridable, and was wired to nothing.

### The README is descriptive, not a specification

It lists the features that exist. Requirements live in `specs/`, and that is what a test answers
to. Never keep or shape a test because the README mentions something. When work changes what is
true, rewrite the README sentence in the same commit and name it in the body. A `specs/`
requirement is different: change it by amending the spec, never by deleting its test.

## Commit Messages

Use a type-colon prefix followed by a short description, then an optional body with context:

- `Add:` New feature or file
- `Fix:` Bug fix
- `Docs:` Documentation changes
- `Refactor:` Code refactoring without behaviour change
- `Test:` Test updates
- `Chore:` Maintenance, dependency bumps, tooling
- `Remove:` Retiring a command, flag, file or test
- `Release:` Cutting a version or pinning its published assets

Examples:
```
Fix: resolve the pod for a project name with dashes

The pod set verb now slugifies a name that contains uppercase letters or
underscores before looking the pod up, so --pod My_App finds my-app.

Add: pod check verb
Docs: update command reference with task trace and status entries
```

## Questions?

Feel free to open an issue for questions or discussions about potential contributions.

Thank you for contributing to docket-cli!
