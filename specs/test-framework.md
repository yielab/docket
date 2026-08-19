# Test Framework

**Version**: 2.3.0
**Status**: Active
**Last Updated**: 2026-08-19

## Overview

Docket's test system has four blocking layers: pytest behavior, byte-for-byte CLI goldens, static
analysis, and specification validation. Docket owns its runtime; tests exercise that runtime
directly and replace only real external protocol/process boundaries.

It also ships one executable full-workflow smoke test. That test is not a fifth exhaustive layer;
it proves the separately tested components compose across real CLI subprocess and HTTP protocol
boundaries into one completed, inspectable task.

## Philosophy

### Spec-first, then test-first

Behavior changes begin in the owning current-state spec. A RED test must fail for the intended
contract before implementation, and the smallest coherent change makes it green.

### Properties every test must have

- **Hermetic state:** every test redirects `DOCKET_HOME` and any derived store to `tmp_path`.
- **No real credentials or network:** model, Telegram, MCP, and HTTP boundaries use deterministic
  fakes unless a separately-labelled environment test explicitly requires a live service.
- **Real internal path:** tests call the same core/driver functions production calls; they do not
  mock the behavior under test.
- **Atomic assertions:** persisted JSON/session/audit state is inspected after the public operation,
  including failure paths.
- **Stable output:** user-visible CLI text is pinned by pytest or a reviewed golden case.

## Test layout

```text
tests/
├── python/                 pytest behavior and contract tests
│   ├── conftest.py         shared hermetic Docket-home fixtures
│   ├── fakes.py            ChatBackend/runtime fakes
│   └── test_workflow_smoke.py  executable workflow acceptance
├── golden/
│   ├── cases/              expected CLI output
│   ├── fixtures/seed.sh    deterministic ~/.docket state
│   ├── fakes/              external executable stubs when required
│   └── run.sh              verify/update harness
└── run-all-tests.sh        local aggregate gate
```

### Full-workflow smoke

Run the observable happy-path proof with:

```bash
uv run python scripts/smoke_workflow.py
```

The command **MUST** create a temporary `DOCKET_HOME` and codebase, start only a loopback
OpenAI-compatible fake endpoint, and invoke Docket through real subprocess CLI commands. It
**MUST** exercise, display, and verify this sequence:

1. Declarative provisioning of an `agentic-product` pod.
2. Task delegation and rendering of the resolved pipeline plan.
3. Lead planning, an Implementer `write` tool call through `dispatch_tool`, and a real mechanical
   file check.
4. Reviewer verdict, a pipeline-defined human approval pause, CLI approval, exact-position resume,
   and final Tester verdict.
5. Terminal task state plus typed handoffs, isolated durable step histories, an atomic tool-call/
   tool-result pair, traces, audit chain, measured usage, and two successful run records.

The model endpoint is fake; the protocol boundary is not. The harness **MUST** receive and validate
real `/chat/completions` request shapes and never use a paid endpoint, credential, or non-loopback
network. Its final output **MUST** name each verified stage and end in one unambiguous `SMOKE PASS`
line. `--workdir <path>` preserves the otherwise-temporary world for inspection.

Test files use `test_<owned_behavior>.py`; card IDs belong in changelogs/commit history, not
permanent filenames.

## Pytest suite

### Pointing Docket at a temporary world

Use the shared `fake_home`/`isolated_docket_home` fixtures where available. A focused test that
needs custom stores may monkeypatch `docket.config` paths explicitly, but every path must remain
under `tmp_path` and be restored by pytest.

```python
def test_example(tmp_path, monkeypatch):
    state = tmp_path / ".docket"
    monkeypatch.setattr(config, "DOCKET_HOME", state)
    monkeypatch.setattr(config, "PROJECTS_DIR", state / "workspaces" / "projects")
```

For turn behavior, inject a deterministic `ChatBackend`; for driver-bound behavior, use
`tests/python/fakes.py` or a purpose-built fake implementing `RuntimeDriver`. Patch an edge adapter
only when the contract being tested ends at that external boundary.

### State safety

- Never infer test paths from the operator's real home.
- Never mutate module constants without pytest restoration.
- Never call a live model endpoint, Telegram API, MCP server, Docker daemon, or Git remote from the
  default suite.
- When testing subprocess behavior itself, create the minimum executable stub under `tmp_path` and
  prepend only that directory to `PATH`.

## Golden parity suite

`tests/golden/run.sh` seeds a deterministic fake `~/.docket`, runs the real launcher, scrubs only
unstable values, and compares stdout/stderr byte-for-byte with `tests/golden/cases/`.

```bash
bash tests/golden/run.sh verify-all
```

Use `update` only for an intentional CLI contract change. Review the diff; never regenerate a
golden merely to hide an unexpected output change.

## Static and specification gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
bash scripts/validate-specs.sh
uv run python scripts/metrics.py --check
```

ShellCheck covers the launcher, installers, scripts, and golden harness in CI. The dependency-floor
job resolves the minimum declared direct versions and runs pytest against them.

## Full validation

```bash
uv run pytest
bash tests/golden/run.sh verify-all
uv run ruff check .
uv run ruff format --check .
uv run mypy src
bash scripts/validate-specs.sh
uv run python scripts/metrics.py --check
```

Environment-dependent skips are acceptable only when the owning contract labels them optional and
the skip reason names the missing capability.

## Changelog

### Version 2.3.0 (2026-08-19)

- W22-C1 adds one observable subprocess-to-HTTP-to-runtime smoke test covering provisioning,
  dispatch, tools, mechanical/verdict/approval gates, resume, handoffs, sessions, traces, audit,
  usage, and run records in a hermetic temporary world.

### Version 2.2.0 (2026-08-19)

- W21-C1 daemon-free truth pass: replaced the pre-cutover daemon/shim instructions with Docket's
  owned runtime, `DOCKET_HOME`, `ChatBackend`, `RuntimeDriver`, and current golden harness.

### Version 2.1.0 (2026-08-04)

- Removed the dead eval harness section after its command and tests were retired.

### Version 2.0.0 (2026-06-24)

- Reorganized the Python, golden, static, and CI testing guidance.

### Version 1.0.0 (2024-01-20)

- Initial test framework documentation.
