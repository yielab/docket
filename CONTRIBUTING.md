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

# Run with debug mode for troubleshooting
DEBUG=1 docket <command>
```

## Code Style Guidelines

### Python Conventions

- Target Python 3.11+; type-annotate everything (the suite is checked with `mypy --strict`)
- Format and lint with `ruff` (`uv run ruff format .` / `uv run ruff check .`)
- Use meaningful names (snake_case for functions/vars, PascalCase for classes/Pydantic models)
- Keep functions focused; prefer pure functions in `core/`
- Comments explain *why* something is shaped the way it is — never what it does or when it
  arrived. No card ids, phase numbers, dates or "used to" narration; git history holds those.
  A docstring is one line unless it states a contract (what is guaranteed, what fails closed).
  `uv run python scripts/maint/comment_lint.py --check src tests` reads this rule

### Package layout (three layers: `cli/ → core/ → edges/`)

All command logic lives in the `docket` package under `src/docket/`. Dependencies point
inward only — a `cli` command may call `core` and `edges`; `core` never imports `cli`. Two
invariants matter most, both enforced by tests rather than convention alone:

1. **Every tool call goes through `core/tools.py`'s single dispatcher** (`dispatch_tool`).
   docket's governance stack — the policy engine, the approval store, the high-risk classifier,
   the audit log — only means anything if there is exactly one place a tool can execute from.
   An AST test enforces this:
   `tests/unit/core/test_tools.py::test_only_the_chokepoint_imports_the_handler_module`.
2. **docket-owned JSON goes through `edges/store.py`** (atomic write + filelock + `.bak`
   rotation + 0600 perms) — never write those files directly. The one documented exemption is
   append-only JSONL (`core/trace.py`, `core/audit.py`), which writes directly by design.

- **Commands** are Typer functions in `src/docket/cli/` — add them to `cli/__init__.py`, or to
  a `_<group>.py` module for a larger subcommand group (e.g. `cli/_gates.py`).
- **Domain logic / helpers** go in `src/docket/core/` — Pydantic models in `core/models.py`,
  plus pure services (policy resolution, sync, security, audit, trace, the turn loop, the tool
  registry, the model-endpoint port).
- **I/O and side effects** go in `src/docket/edges/`:
  - docket-owned JSON (`.docket-meta.json`, etc.) is read/written **only** through
    `edges/store.py`, per invariant 2 above.
  - the model endpoint (`edges/adapters/llm.py`), MCP client (`edges/adapters/mcp_client.py`),
    Telegram Bot API (`edges/adapters/telegram.py`), the sandboxed-exec/fetch tool handlers
    (`edges/adapters/toolbox.py`, `edges/adapters/fetch.py`), and shell-outs to `docker` / `git`
    (`edges/adapters/system.py`) each live behind their own adapter module — no other module
    should know their wire formats.
- **Tests** go in `tests/` (see [Testing](#testing)); **specs** go in `specs/`;
  **documentation** goes in `docs/`.

## Testing

All contributions must include appropriate tests:

- Tests are placed by lane, named by module, per `specs/test-framework.md` §"Lanes and
  placement": `tests/unit/` mirrors `src/docket/` one file per module, `tests/integration/`
  covers cross-module or real-process behaviour, `tests/guards/` holds AST/layout invariants,
  and `tests/agent/` holds checks on prose, release artifacts or agent hook scripts — that lane
  is budgeted, never the default suite, and runs in its own CI job
- New commands also get a spec under `specs/` and golden-parity coverage where output is frozen

For scale, so you know what you're getting into: **2,490 tests** in the default suite
(`tests/unit/`, `tests/integration/`, `tests/guards/`; the budgeted agent lane in `tests/agent/`
runs separately), **~31,060 lines** of Python in the shipped package, **28 specifications**
validated in CI, and **38 commands** in the [command reference](docs/commands.md).
`scripts/metrics.py --check` computes these from the tree on every CI run, so this paragraph
cannot silently go stale.

Run the full aggregator before submitting:

```bash
# Observable full workflow (temporary state + deterministic loopback model; no credentials)
uv run python scripts/smoke_workflow.py

# Opt-in realistic memory-backed repair with genuine inference on port 8081
uv run python scripts/smoke_workflow.py --live-model
DOCKET_RUN_LIVE_SMOKE=1 uv run pytest -q tests/integration/test_workflow_smoke.py

# Smaller live infrastructure-only scenario retained for diagnosis
uv run python scripts/smoke_workflow.py --live-model --scenario basic

# All tests (pytest + golden parity)
./tests/run-all-tests.sh

# pytest suite only (default lanes: unit, integration, guards)
uv run pytest   # 2,490-test Python suite

# agent lane only (prose, release artifacts, agent hook scripts; own CI job)
uv run pytest tests/agent

# Golden parity suite (byte-for-byte CLI output)
bash tests/golden/run.sh verify-all

# CLI reference drift check (docs/commands.md is generated from the Typer registry)
uv run python scripts/gen_cli_docs.py --check

# Docs site, strict (a dead link fails the build; mkdocs is not a project dependency)
uvx --with mkdocs-material --with 'mkdocstrings[python]' mkdocs build --strict
```

### CI gates

These all gate CI and must pass locally before opening a PR:

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy src              # strict type check
uv run pytest                # unit/integration suite
bash tests/golden/run.sh verify-all   # golden parity
./scripts/validate-specs.sh  # spec format validation
uv run python scripts/metrics.py --check            # this doc's metric-drift guard (see above)
uv run python scripts/render-doc-assets.py --check  # README screenshot/GIF drift guard
uv run python scripts/release_journey.py            # exact-wheel first-turn release rehearsal
```

## Adding a New Command

docket follows spec-driven development (see [SSD-WORKFLOW.md](SSD-WORKFLOW.md)). To add a
command:

1. Write a spec under `specs/functional/<command>.spec.md`.
2. Register the command as a Typer function in `src/docket/cli/` (in `cli/__init__.py`, or a
   `_<group>.py` module for a larger group) and wire its help into `cli/_help.py`.
3. Put domain logic in `core/` and any I/O behind `edges/` (`store.py` for docket JSON,
   `system.py` for shell-outs to `docker`/`git`).
4. Add pytest coverage in the unit file named for the module (see [Testing](#testing)), and
   golden cases if the output is frozen.
5. Run the CI gates (see [Testing](#testing)).

## Documentation

- Update relevant documentation in `docs/`
- `docs/commands.md` is generated from the Typer registry by `scripts/gen_cli_docs.py` and must
  never be hand-edited; put command prose in the command's own help string (`cli/_help.py` or the
  Typer function) and regenerate with `uv run python scripts/gen_cli_docs.py`
- Update README.md if adding major features
- Keep comments to rationale only (see [Python Conventions](#python-conventions)) — command prose
  belongs in the Typer help strings, not in code comments

## Rules that have cost this project time when ignored

Six rules, each written down because breaking it cost real work here.

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
   times, once displacing the whole environment with fixture agents. Any new `DOCKET_HOME`-derived
   constant in `config.py` must reach `_DOCKET_HOME_PATHS` in `tests/conftest.py`, and any test
   choosing its own home calls `repoint_docket_home` rather than hand-rolling a partial copy. Both
   are guarded.
5. **A gap list is a claim about the tree and decays like one.** Re-verify before scheduling work
   against it. Work has been scheduled here, and kept over better candidates, against a gap that had
   already been closed the day it was written down.
6. **Scrub every diff before committing.** Real client names, home-directory paths and usernames do
   not belong in a public repository. Commit subjects follow `Type: description` with a detailed
   body, ASCII only.

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

Examples:
```
Fix: resolve session key parsing for project names with dashes

docket scope set <id> now correctly slugifies names that contain
uppercase letters or underscores before building the session key.

Add: workflow validate subcommand
Docs: update command reference with trace and metrics entries
```

## Questions?

Feel free to open an issue for questions or discussions about potential contributions.

Thank you for contributing to docket-cli!
