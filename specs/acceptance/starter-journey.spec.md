# Extractable Starter Journey

**Version**: 2.0.1
**Status**: Implemented — artifact-installed Python 3.11 journey tested outside the checkout
**Last Updated**: 2026-10-23

## Overview

The starter is Docket's smallest copied-outside-checkout path from an exact built artifact to an
inspectable governed mutation. It uses the installed root `docket` command and a deterministic
loopback OpenAI-compatible model; it does not import the source checkout, depend on
`docket-runtime`, or require hosted credentials.

The authoritative example lives entirely under `examples/starter/`. A user copies that directory,
installs its locked dependencies and one exact root Docket artifact into Python 3.11, and runs one
documented command:

```bash
python starter.py --workspace ./workspace
```

The command demonstrates a real approval pause twice. The first decision is denied to prove that
the target bytes do not change; the second is granted and resumes at the gated Implementer hop,
which performs the journey's only workspace mutation.

## Stories

### A new user runs one local governed change

Given a copied starter, a fresh Python 3.11 environment, and the exact root Docket wheel, a user
can run the documented command without an API key. The starter starts its own ephemeral loopback
model, provisions only the minimal project and pipeline required for the example, and asks the user
to deny one pending mutation and grant the next. It finishes with a persisted typed handoff and
prints the public inspection commands and state locators.

### An operator verifies what happened

Using the same installed `docket` executable and `DOCKET_HOME`, an operator can show the dispatch
task (its output names the runs that executed it), export the task's trace, and verify the audit
hash chain. These are root CLI contracts: the starter MUST NOT claim that `docket-runtime` owns the
CLI run registry.

## Criteria

1. `examples/starter/` MUST be self-contained and MUST include `README.md`, `starter.py`, and a
   non-empty `requirements.lock` whose installable requirements are exact-version pins. The lock
   MUST NOT resolve Docket from a package index; the root artifact is supplied explicitly.
2. The acceptance journey MUST build exactly one root `docket` wheel and one root sdist in a fresh
   artifact directory, copy only `examples/starter/` to a directory outside the checkout, create a
   fresh Python 3.11 environment, install the locked dependencies, and install the exact wheel with
   dependency resolution disabled.
3. After installation, the journey MUST clear the API-key variables (`ANTHROPIC_API_KEY`,
   `DOCKET_LLM_API_KEY`, `OPENAI_API_KEY`, `SMOKE_LOCAL_API_KEY`) and the source-override variables
   (`DOCKET_LLM_BASE_URL`, `PYTHONHOME`; `PYTHONPATH` is set empty), set package installers offline
   (`UV_OFFLINE`, `PIP_NO_INDEX`), route the proxy variables to a closed loopback address, and allow
   only the starter's ephemeral loopback model endpoint (`NO_PROXY` names loopback only). The starter
   MUST print that endpoint as `STARTER LOOPBACK <url>`; its OS-assigned port MUST NOT be 8081.
4. The public command MUST first reach a persisted `waiting_approval` state, listed by
   `docket inbox --peek` as needing approval, and print `STARTER DENIAL PAUSED <token>`. Until the
   test sends `deny` at the starter's prompt, the declared target bytes MUST remain unchanged. After
   public CLI denial (`docket task deny <token>`), it MUST print `STARTER DENIAL CONFIRMED`, leave
   those bytes unchanged, and persist the denied task as `failed` with `failureKind`
   `approval_denied`.
5. The same command MUST enqueue a fresh task with `docket task add`, reach a second persisted
   approval pause, and print `STARTER GRANT PAUSED <token>`. Until the test sends `grant`, the target
   bytes MUST remain unchanged. Public CLI grant (`docket task approve <token>`) plus resumed dispatch
   MUST mutate exactly `starter-output.txt`, changing its bytes from `starter pending\n` to
   `docket starter approved\n`. No other workspace file MAY be created, removed, or changed.
6. The deterministic model MUST issue exactly one admitted `write` call with call id
   `starter-write`, observe its matching tool result, and then return the terminal summary
   `Starter journey completed.`. The done task's persisted final hop MUST contain the complete
   `HandoffArtifact` object (`summary`, `files_changed`, `diff_ref`, `diff`, `verdict`, and
   `brief`), and its legacy `output` MUST equal the typed artifact's summary.
7. The installed public CLI MUST successfully execute `docket task show <id> --pod docket-starter
   --json`, `docket task trace <id> --pod docket-starter --export`, and `docket log verify`.
   The `show` output MUST name a succeeded run whose task ids include the completed task. The
   exported trace MUST contain one `tool_call` record and one `tool_result` record, in that order,
   both with call id `starter-write` and the same session id. The acceptance test also requires the
   matching project, the `implementer` role, the `write` tool, and an `ok`, `executed` result, and
   exactly one `approval_task_denied`, one `approval_resumed`, and two `approval_required` events
   across the two exported tasks. Audit verification MUST report `verified clean`. The starter
   prints `docket task list --pod docket-starter --json` as an inspection locator; it does not run it.
8. The starter MUST print `STARTER JOURNEY PASS` plus the target, task-list, trace, and audit
   locators, and the inspection commands. Failure MUST be bounded and actionable: the starter prints
   one `STARTER FAIL` line to stderr, carrying at most the last 2,000 characters of a failed
   command's output, with no traceback for an expected missing `docket` executable or an
   unavailable local prerequisite.
9. The complete artifact journey MUST finish within 600 seconds. Its test MUST use isolated
   `DOCKET_HOME`, home, temporary, artifact, dependency-cache, workspace, and ephemeral-port state.

## Scenarios

| Scenario | Initial state | Public action | Observable result | Durable side effect / rollback oracle |
| --- | --- | --- | --- | --- |
| Pre-approval pause | Target is `starter pending\n` | Run the documented command | `STARTER DENIAL PAUSED <token>` | Target and all other workspace bytes are unchanged |
| Denial | First token is pending | Enter `deny` | `STARTER DENIAL CONFIRMED` | Task is `failed` with `failureKind` `approval_denied`; workspace is unchanged |
| Grant | Fresh second token is pending | Enter `grant` | `STARTER JOURNEY PASS` | Exactly one target changes; done task has typed terminal handoff |
| Public inspection | Journey completed | Run installed `task show`, `task trace --export`, and `log verify` | Commands exit zero with matching identities | Run/trace/audit remain under the isolated `DOCKET_HOME` |
| Offline/source isolation | Exact artifact is installed | Run with offline/proxy guards, empty `PYTHONPATH`, no API key | Loopback journey succeeds | Imported `docket` resolves inside the venv; `docket_runtime` is absent |

The model transport is the only fake edge. Artifact building, dependency installation, the console
entry point, provider configuration, project initialization, task queue, approval transitions,
dispatch, tool execution, run registry, trace export, handoff persistence, and audit verification
all use their production paths.

## Metrics

- Artifact cardinality: exactly one root wheel and one root sdist, built once per journey.
- Supported interpreter: Python 3.11.
- Time budget: at most 600 seconds for the full owning test.
- Workspace mutation count: exactly one changed file and zero created/deleted files.
- Approval outcomes: one denied task (`failed`, `approval_denied`) with zero tool mutations, then one
  granted task with one tool mutation.
- Trace identity: exactly one `starter-write` call/result pair with no duplicate.
- Credential/network posture: zero inherited API keys and no non-loopback model endpoint after
  artifact installation.

## Implementation

- `examples/starter/starter.py`: the starter command, its deterministic loopback model, and the `STARTER ...` markers.
- `examples/starter/README.md`, `examples/starter/requirements.lock`: the copy-and-run instructions and the exact locked dependencies.
- `tests/agent/release/test_starter_journey.py`: the owning acceptance test (release lane).
- `pyproject.toml`: the `docket` console entry point (`[project.scripts]`).
- `src/docket/interfaces/cli/commands/agents.py`: `init --from`.
- `src/docket/interfaces/cli/commands/setup_model.py`: `setup provider add`, `setup model set`.
- `src/docket/interfaces/cli/commands/task.py`: `task add`, `task show`, `task trace --export`, `task list`, `task approve`, `task deny`.
- `src/docket/interfaces/cli/commands/inbox.py`: `inbox --peek`.
- `src/docket/interfaces/cli/commands/run.py`: `run --pipeline`.
- `src/docket/interfaces/cli/commands/log.py`: `log verify`.
- `src/docket/tasks/domain/task.py`: task statuses, `failureKind`, hop results.
- `src/docket/tasks/application/actions.py`: the approval gate's resume path.
- `src/docket/governance/approval.py`: approval transitions.
- `src/docket/kernel/handoff.py`: `HandoffArtifact`.
- `src/docket/observability/telemetry.py`: approval trace event names and their fields.
