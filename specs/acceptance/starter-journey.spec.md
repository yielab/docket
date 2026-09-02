# Extractable Starter Journey

**Version**: 0.1.0
**Status**: Specified — RED acceptance evidence; starter implementation pending
**Last Updated**: 2026-09-02

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

Using the same installed `docket` executable and `DOCKET_HOME`, an operator can list and show the
dispatch run, export the project's trace, and verify the audit hash chain. These are root CLI
contracts: the starter MUST NOT claim that `docket-runtime` owns the CLI run registry.

## Criteria

1. `examples/starter/` MUST be self-contained and MUST include `README.md`, `starter.py`, and a
   non-empty `requirements.lock` whose installable requirements are exact-version pins. The lock
   MUST NOT resolve Docket from a package index; the root artifact is supplied explicitly.
2. The acceptance journey MUST build exactly one root `docket` wheel and one root sdist in a fresh
   artifact directory, copy only `examples/starter/` to a directory outside the checkout, create a
   fresh Python 3.11 environment, install the locked dependencies, and install the exact wheel with
   dependency resolution disabled.
3. After installation, the journey MUST clear API-key and source-override variables, set package
   installers offline, route any accidental proxy traffic to a closed loopback address, and allow
   only the starter's ephemeral loopback model endpoint. The starter MUST print that endpoint as
   `STARTER LOOPBACK <url>`; its OS-assigned port MUST NOT be 8081.
4. The public command MUST first reach a persisted `waiting_approval` state and print
   `STARTER DENIAL PAUSED`. Until the test sends `deny`, the declared target bytes MUST remain
   unchanged. After public CLI denial, it MUST print `STARTER DENIAL CONFIRMED`, leave those bytes
   unchanged, and persist a terminal `approval_denied` task.
5. The same command MUST enqueue a fresh task, reach a second persisted approval pause, and print
   `STARTER GRANT PAUSED`. Until the test sends `grant`, the target bytes MUST remain unchanged.
   Public CLI grant plus resumed dispatch MUST mutate exactly `starter-output.txt`, changing its
   bytes from `starter pending\n` to `docket starter approved\n`. No other workspace file MAY be
   created, removed, or changed.
6. The deterministic model MUST issue exactly one admitted `write` call with call id
   `starter-write`, observe its matching tool result, and then return the terminal summary
   `Starter journey completed.`. The done task's persisted final hop MUST contain the complete
   `HandoffArtifact` object (`summary`, `files_changed`, `diff_ref`, `verdict`, and `notes`), and its
   legacy `output` MUST equal the typed artifact's summary.
7. The installed public CLI MUST successfully execute `docket runs list --project docket-starter
   --json`, `docket runs show <id> --json`, `docket trace export docket-starter`, and
   `docket audit verify`. List/show MUST agree on a successful run that names the completed task;
   the exported trace MUST contain one adjacent `tool_call`/`tool_result` pair with matching
   project, session, role, tool, and call id; audit verification MUST report a clean chain.
8. The starter MUST print `STARTER JOURNEY PASS` plus the target, task-list, trace, and audit
   locators. Failure MUST be bounded and actionable, with no traceback for an expected missing
   dependency or unavailable local prerequisite.
9. The complete artifact journey MUST finish within 600 seconds. Its test MUST use isolated
   `DOCKET_HOME`, home, temporary, artifact, dependency-cache, workspace, and ephemeral-port state.

## Scenarios

| Scenario | Initial state | Public action | Observable result | Durable side effect / rollback oracle |
| --- | --- | --- | --- | --- |
| RED / missing starter | `examples/starter/` absent | Run the owning pytest | Explicit missing-starter assertion | No build, install, or user state occurs |
| Pre-approval pause | Target is `starter pending\n` | Run the documented command | `STARTER DENIAL PAUSED` | Target and all other workspace bytes are unchanged |
| Denial | First token is pending | Enter `deny` | `STARTER DENIAL CONFIRMED` | Task is `approval_denied`; workspace is unchanged |
| Grant | Fresh second token is pending | Enter `grant` | `STARTER JOURNEY PASS` | Exactly one target changes; done task has typed terminal handoff |
| Public inspection | Journey completed | Run installed `runs`, `trace`, and `audit` commands | Commands exit zero with matching identities | Run/trace/audit remain under the isolated `DOCKET_HOME` |
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
- Approval outcomes: one denied task with zero tool mutations, then one granted task with one tool
  mutation.
- Trace identity: exactly one `starter-write` call/result pair with no orphan or duplicate.
- Credential/network posture: zero inherited API keys and no non-loopback model endpoint after
  artifact installation.

## Changelog

### Version 0.1.0 (2026-09-02)

- Specified the RED contract for a copied-outside-checkout, root-artifact-installed Python 3.11
  starter with live deny/grant byte oracles, persisted typed handoff, paired trace identity, public
  run inspection, and public audit verification.
- Kept the starter on the root `docket` CLI boundary; the separate `docket-runtime` facade neither
  participates in this journey nor owns the CLI run registry.
