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
- Add docstrings/comments for non-obvious logic

### Package layout (three layers: `cli/ → core/ → edges/`)

All command logic lives in the `docket` package under `src/docket/`. Dependencies point
inward only — a `cli` command may call `core` and `edges`; `core` never imports `cli`. Two
invariants matter most, both enforced by tests rather than convention alone:

1. **Every tool call goes through `core/tools.py`'s single dispatcher** (`dispatch_tool`).
   docket's governance stack — the policy engine, the approval store, the high-risk classifier,
   the audit log — only means anything if there is exactly one place a tool can execute from.
   An AST test enforces this:
   `tests/python/test_tool_registry.py::test_only_the_chokepoint_imports_the_handler_module`.
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

- Unit and integration tests live under `tests/python/` (pytest)
- New commands also get a spec under `specs/` and golden-parity coverage where output is frozen

Run the full aggregator before submitting:

```bash
# Observable full workflow (temporary state + deterministic loopback model; no credentials)
uv run python scripts/smoke_workflow.py

# All tests (pytest + golden parity)
./tests/run-all-tests.sh

# pytest suite only
uv run pytest

# Golden parity suite (byte-for-byte CLI output)
bash tests/golden/run.sh verify-all
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
```

## Adding a New Command

docket follows spec-driven development (see [SSD-WORKFLOW.md](SSD-WORKFLOW.md)). To add a
command:

1. Write a spec under `specs/functional/<command>.spec.md`.
2. Register the command as a Typer function in `src/docket/cli/` (in `cli/__init__.py`, or a
   `_<group>.py` module for a larger group) and wire its help into `cli/_help.py`.
3. Put domain logic in `core/` and any I/O behind `edges/` (`store.py` for docket JSON,
   `system.py` for shell-outs to `docker`/`git`).
4. Add pytest coverage under `tests/python/`, and golden cases if the output is frozen.
5. Run the CI gates (see [Testing](#testing)).

## Documentation

- Update relevant documentation in `docs/`
- Add command documentation to `docs/commands.md`
- Update README.md if adding major features
- Include inline comments/docstrings for complex logic

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
