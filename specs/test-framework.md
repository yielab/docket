# Testing Framework

**Version**: 2.1.0
**Status**: Active
**Last Updated**: 2026-08-04

## Overview

This document describes how docket is tested. docket is a Python package
(`src/docket/`, layered `cli/ → core/ → edges/`); its testing stack is built on
**pytest**, a **byte-parity golden suite**, and a set of **CI-blocking static gates**
(ruff, mypy, spec validation). (A non-blocking specialist-role eval-stub harness
existed under `tests/evals/` but was dead code — wired to the deleted OpenClaw daemon
— and was removed outright, CL-J.)

docket follows spec-first / test-first discipline (SSD — see `SSD-WORKFLOW.md` and
`specs/README.md`). The behaviour described in a spec is encoded as a test before the
implementation is written; specs are the source of truth and are validated in CI.

## Philosophy

### Spec-first, then test-first

1. **Specification first** — write or update the spec (`specs/**`, RFC 2119 keywords)
   before touching code.
2. **Test from the spec** — encode the required behaviour as a failing test.
3. **Implement** — write the minimum code to make the test pass.

### Red-Green-Refactor

```
┌──────────┐   ┌──────────┐   ┌──────────┐
│   RED    │ → │  GREEN   │ → │ REFACTOR │ → (repeat)
│ failing  │   │ minimal  │   │ clean up │
│  test    │   │  pass    │   │ keep green│
└──────────┘   └──────────┘   └──────────┘
```

### Properties every test should have

- **Arrange-Act-Assert** — a clear three-part structure.
- **Independent** — no ordering dependencies; each test sets up its own world in a
  `tmp_path` and tears it down automatically.
- **Deterministic** — same result every run; no reliance on wall-clock, network, or a
  real `~/.openclaw`.
- **Fast** — the unit-level suite runs in seconds.
- **Test doubles only at the external boundary** — fake the *external* OpenClaw daemon
  at the ACL, never docket's own logic (see "Faking the daemon" below).

## Test Layout

```
tests/
├── python/                 # pytest suite (~493 tests)
│   ├── conftest.py         # shared fixtures (fake_openclaw shim on PATH)
│   ├── test_data_layer.py
│   ├── test_list_info_cost_commands.py
│   ├── test_profile_scope_models.py  # per-command coverage, named by subject
│   ├── test_m5_*.py        # doctor, gates/policy, provider, serve, system, trace/audit
│   ├── test_install.py
│   ├── test_pod_model.py / test_pod_provisioning.py
│   ├── test_portfolio_manager.py
│   ├── test_acl_no_inject.py / test_dispatch.py / test_cli_stubs.py / ...
│   └── __init__.py
├── golden/                 # byte-parity golden suite (17 frozen cases)
│   ├── run.sh              # capture / verify / verify-all / list
│   ├── cases/              # *.golden frozen outputs
│   ├── fakes/  fixtures/   # fake openclaw + seeded home for hermetic runs
│   └── scrub.py            # normalises volatile output before diffing
└── run-all-tests.sh        # aggregator: pytest + golden
```

### Naming conventions

- Test files: `test_*.py`
- Test functions: `def test_*(...)`
- A function name should describe the behaviour under test, e.g.
  `test_add_rejects_duplicate_id`, `test_scope_set_rewrites_session_key`.

## pytest Suite (`tests/python/`)

The pytest suite is the primary safety net (~493 tests). Tests are **hermetic**: they
point docket's config at temporary directories so they never read or write the real
`~/.openclaw`, and they stub the external daemon's *state-mutating* CLI calls at the ACL
boundary.

### Pointing docket at a temp world

Two equivalent approaches are used across the suite:

- **In-process** — `monkeypatch.setattr` the paths in `docket.config` (and the ACL's
  cached references) to live under `tmp_path`, then call the command function directly.
- **Subprocess** — run `python -m docket ...` with the `OPENCLAW_DIR` env var pointed at
  a temp dir, exercising the full real entry point.

In-process example (Arrange-Act-Assert, `tmp_path` + `monkeypatch`):

```python
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.edges.adapters.openclaw as _oc


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every docket path under a throwaway temp home."""
    oc_dir = tmp_path / ".openclaw"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", oc_dir / "openclaw.json", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", _cfg.CONFIG_FILE, raising=True)
    return oc_dir


def test_slugify_converts_spaces_to_dashes() -> None:
    from docket.core.utils import slugify

    # Arrange / Act
    result = slugify("My Test Project")

    # Assert
    assert result == "my-test-project"


def test_detect_stack_identifies_node(tmp_path: Path) -> None:
    from docket.core.utils import detect_stack

    # Arrange
    (tmp_path / "package.json").write_text('{"name": "test"}')

    # Act
    stack = detect_stack(tmp_path)

    # Assert
    assert stack == "Node.js"
```

> The exact import paths above (`docket.core.utils`, `docket.config`,
> `docket.edges.adapters.openclaw`) reflect the real package layout; mirror an existing
> test in the relevant `test_m*.py` wave rather than inventing new helpers.

### Faking the daemon (the honest pattern)

The OpenClaw daemon is an **external** dependency docket shells out to; CI does not
install it. The discipline here is deliberate:

- **Do not** monkeypatch docket's own dependency/health code — that would bypass the very
  logic under test.
- **Do** put a minimal *real* `openclaw` executable on PATH so read-only probes
  (`shutil.which("openclaw")`, `openclaw --version`) run their real code paths against a
  real binary. This is the `fake_openclaw` fixture in `tests/python/conftest.py` — it
  writes a tiny shim and prepends it to `PATH`, returning the bin dir so a test can remove
  it to assert the *absent* case.
- Only the daemon's *state-mutating* CLI calls (e.g. `register_agent_cli`), which would
  need a live daemon, are stubbed — and they are stubbed **at the ACL boundary**
  (`docket.edges.adapters.openclaw`), the single module that knows the OpenClaw formats.

```python
def test_doctor_finds_daemon_when_present(fake_openclaw, capsys) -> None:
    # Arrange: fake_openclaw fixture has a real shim on PATH
    from docket.cli._doctor import run_dependency_checks

    # Act
    run_dependency_checks()

    # Assert: the real which()/--version probes succeed against the shim
    assert "openclaw" in capsys.readouterr().out


def test_doctor_reports_missing_daemon(fake_openclaw, capsys) -> None:
    # Arrange: remove the shim to simulate a host without the daemon
    for f in fake_openclaw.iterdir():
        f.unlink()
    from docket.cli._doctor import run_dependency_checks

    # Act
    run_dependency_checks()

    # Assert
    assert "not found" in capsys.readouterr().out.lower()
```

## Golden Parity Suite (`tests/golden/`)

The golden suite freezes the exact user-facing output of read-only commands and diffs new
output **byte-for-byte** against the frozen copy. It is the net that catches a refactor
silently changing CLI behaviour. Runs go through a fake `openclaw` and a seeded temp home
so they are hermetic; `scrub.py` normalises volatile fragments (paths, timestamps) before
comparison.

```bash
# Verify all 17 frozen cases
bash tests/golden/run.sh verify-all

# Verify one case / list cases
bash tests/golden/run.sh verify list
bash tests/golden/run.sh list

# Re-capture a golden after an intended output change (review the diff!)
bash tests/golden/run.sh capture info myshop
```

## Running the Tests

```bash
# Full pytest suite
uv run pytest

# One file / one test
uv run pytest tests/python/test_list_info_cost_commands.py
uv run pytest tests/python/test_list_info_cost_commands.py::test_list_renders_agents

# Golden parity
bash tests/golden/run.sh verify-all

# Everything at once (pytest + golden)
bash tests/run-all-tests.sh
```

## Static Gates (CI-blocking)

These run in CI and must pass before merge:

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy src                # strict type check
./scripts/validate-specs.sh    # spec structure / RFC-2119 validation
```

## Continuous Integration

CI is defined in `.github/workflows/ci.yml` with four jobs:

- **`python`** — `ruff check`, `ruff format --check`, `mypy src`, `pytest`
- **`golden`** — `bash tests/golden/run.sh verify-all`
- **`shell`** — `shellcheck` on shell scripts + `./scripts/validate-specs.sh`
- **`macos`** — smoke run on macOS (graceful degradation without systemd)

## Best Practices

1. **Spec before code, test before implementation** — encode the spec's MUST/SHOULD as
   tests first.
2. **One behaviour per test** — a focused assertion makes failures legible.
3. **Descriptive names** — `test_<subject>_<behaviour>`.
4. **Arrange-Act-Assert** — keep the three phases visually distinct.
5. **Hermetic by construction** — isolate paths under `tmp_path`/`OPENCLAW_DIR`; never
   touch the real home.
6. **Fake only at the edge** — stub the external daemon at the ACL boundary; run docket's
   own code for real. Prefer the `fake_openclaw` shim over patching internal logic.
7. **Keep goldens honest** — only re-capture a golden when the output change is intended,
   and review the diff.

## Changelog

### Version 2.1.0 (2026-08-04)
- **CL-J — the eval-stub harness is removed.** `tests/evals/` was dead code, wired to the
  deleted OpenClaw daemon (workspace paths under `$HOME/.openclaw/...`, `openclaw agent
  --local --json`), and skipped silently instead of failing, which is why the drift went
  unnoticed. Removed the "Eval Stubs" section, the `evals/` entry from the Test Layout tree,
  and every `./tests/evals/run-evals.sh` invocation from the Running-the-Tests examples.
  `tests/run-all-tests.sh` now aggregates pytest + golden only.

### Version 2.0.0 (2026-06-24)
- Rewritten to describe the real Python/pytest test stack after the Bash→Python cutover.
- Replaced the obsolete Bash TDD framework (`.sh` tests, `assert_equals`, sourced
  helpers, Bash mock daemons, `scripts/test-coverage.sh`, `test.yml`) with the actual
  setup: pytest under `tests/python/`, the golden parity suite, eval stubs, the
  `run-all-tests.sh` aggregator, the `fake_openclaw` conftest fixture, the static gates
  (ruff/mypy/validate-specs), and the `ci.yml` job matrix.
- Documented the honest daemon-faking pattern: real shim on PATH for read-only probes;
  stub only state-mutating daemon calls at the ACL boundary.

### Version 1.0.0 (2024-01-20)
- Original (Bash-era) TDD framework specification. Superseded by 2.0.0.
