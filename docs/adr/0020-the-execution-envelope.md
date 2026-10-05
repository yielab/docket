# ADR 0020 (D-55): the execution envelope — isolation by default, a network lockdown mode, nothing unscreened or credentialed leaks in

**Question:** Phase 37 made a task's execution checkable. What it runs in is still the operator's
whole machine unless the operator turned isolation on: `bash` inherits the host environment, a
stdio MCP server starts unjailed, fetched pages reach the model unscreened, and one slow pod stalls
every other pod's sweep. What does docket change so that an agent's process runs in an envelope by
default, and what does it leave to the operator?

**Where decided:** 2026-10-05, as Phase 38. It is the outline ADR 0017 left in `TODO.md`
("Planned — Phase 38"), opened when Phase 37 closed at `25fe5252`. Three outline claims were false
or not yet decidable when re-verified (see Evidence and "Corrections to the outline").

**Evidence** (read at `25fe5252`; locators are symbol names, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| Isolation is off unless `docket gates isolate on` ran; the turn reads one boolean | `core/fleet.py::FleetSecurity.isolation_enabled` (default `False`); `edges/adapters/docket_runtime.py::_resolve_sandbox` |
| Only `bash` runs in the jail; file tools are an in-process path check | `core/tools.py` bash handler (`ctx.sandbox`); `edges/adapters/toolbox.py::resolve_within` |
| The backend order is docker, then bwrap | `edges/adapters/system.py::sandbox_availability` |
| **Measured:** the default docker image has neither `git` nor `python3` | `docker run --rm alpine:3.20 sh -c 'command -v python3 git'` prints nothing (2026-10-05) |
| **Measured:** under bwrap, `git commit` in a task worktree fails: `.git/worktrees/<t>/index.lock: Read-only file system` | `system.py::bwrap_argv` binds only the roots read-write; a worktree's admin dir lives in the main repository's `.git` |
| `gates isolate on` checks only `shutil.which("docker")`; `doctor` prints the mode string and probes nothing | `cli/_gates.py`, `cli/_doctor.py::_check_security_gates` |
| Neither backend cuts the network (`--share-net`; docker's default bridge) | `system.py::bwrap_argv`, `docker_run_argv` |
| A stdio MCP server is spawned on the host, unjailed | `edges/adapters/mcp_client.py::_stdio_params` |
| `fetch` results reach the model unscreened; MCP results are screened | `core/tools.py::_fetch_tool`; `core/mcp_tools.py::_screen_result` |
| `verifyCmd`, `run:` steps and unjailed `bash` inherit the full host environment, provider keys included | `system.py::run_verify_cmd` (`{**os.environ, **env}`); `toolbox.py::run_bash` |
| The serve sweep runs pods one after another; one blocking hop stalls the rest | `serve.py::_run_sweeps` (its own comment) |
| **Measured live (Phase 37):** `trace.redact("task=task-<uuid>")` returns `ta[REDACTED]` | `core/trace.py::_REDACT_PATTERNS` (no left boundary) |
| Nothing produces a `kind: autonomy` document, and nothing in `src/` names one | ADR 0017 §5 names the producer (an independent verifier) |

## Decision

1. **Isolation is on by default.** A fresh `DOCKET_HOME` jails every `bash` call. `docket gates
   isolate off` is the operator's explicit, audited opt-out, and it is recorded, so "never set"
   and "turned off" are different states. With isolation on and no working backend, the turn is
   refused before any model call (the existing `isolation.refused` path), and the message names
   both fixes: install bubblewrap, or `docket gates isolate off`. `docket doctor` and `docket
   gates isolate on` probe the real backend (`sandbox_availability`, daemon- and smoke-test-aware)
   instead of looking for a `docker` binary. This reverses the opt-in default of P19-9.
2. **bwrap comes first.** The default order becomes bwrap, then docker, because bwrap shows the
   host's toolchain read-only and docker's default image has none (measured).
   `DOCKET_SANDBOX_BACKEND` still forces one.
3. **A jailed `bash` can commit in its task worktree.** When a root is a git worktree, the jail
   also binds that worktree's git directory and the repository's common directory read-write
   (`git rev-parse --git-dir --git-common-dir`). Nothing else of the host becomes writable.
4. **A network lockdown mode.** `docket gates network none|open` (global) and the pod setting
   `network` (`none` only narrows) cut the jail's network: bwrap drops `--share-net`, docker runs
   `--network none`. The default stays `open`, so `pip`, `npm` and `git clone` keep working. `fetch`
   runs in docket's own process and keeps its allowlist: under `none` it is the only network path,
   and an inspectable one. `network none` with isolation off is refused at turn start, because a
   lockdown with no jail would be a setting that lies. This ships the mechanism ADR 0004 deferred.
   ADR 0004's default (open) stands.
5. **stdio MCP servers start in the same jail as `bash`:** the same backend, the turn's roots, the
   turn's network mode. A server that cannot run jailed is declared `isolate: false` by the
   operator (`docket mcp servers add --no-isolate`). That is an audited assertion, shown by
   `doctor`, like `--kind read`. HTTP MCP servers are unchanged: docket's own client talks to them.
6. **File tools stay in-process and confined.** `read`, `write`, `edit`, `glob` and `grep` are not
   moved into a subprocess jail. Their containment is `resolve_within`, which is the same boundary
   the jail's read-write binds draw. The gap is closed instead: a symlink met while `glob`/`grep`
   walk a root never leads out of the roots, and `write`/`edit` never write through a final-component
   symlink that leaves them.
7. **`fetch` results pass `pre_input`**, exactly like MCP results (ADR 0019 §2): `block` refuses
   and audits, `redact` redacts, `warn` passes and audits. One function screens both.
8. **A task's processes never see docket's credentials.** `verifyCmd`, `run:` steps and an unjailed
   `bash` get the host environment minus docket's own secrets: `DOCKET_LLM_API_KEY`, every
   credential name the provider catalog declares, `TELEGRAM_BOT_TOKEN`, and every name in the
   secret store. A jailed `bash` already gets only `PATH` and the pod's injected variables.
9. **One sweep worker per pod.** `docket serve --dispatch` sweeps each dispatchable pod in its own
   worker, with at most one sweep in flight per pod. The total is bounded by
   `DISPATCH_SWEEP_WORKERS` (default 4). A pod whose hop blocks no longer delays another pod's
   queue.
10. **The redaction pattern gets a left boundary.** `sk`, `api`, `key`, `tok` and the rest match
    only at the start of a word, so `task=` and `risk=` pass and `api_key=...` is still redacted.

## Corrections to the outline

- **"File tools and MCP servers jailed, not only `bash`."** MCP servers: yes (§5). File tools:
  no subprocess jail (§6). They never ran a process, and their path boundary is already the jail's.
  The measured gap was symlinks met during a walk, and that is what is closed.
- **"An egress lockdown mode. This reverses ADR 0004's default for autonomy-granted domains."**
  The default is not reversed. The lockdown ships as a mode (§4). "Autonomy-granted domains" needs
  a `kind: autonomy` document, which is deferred below.
- **"Ephemeral per-task credentials."** docket has no credential issuer to mint from, so a
  per-task token would be a copy of the operator's long-lived one. What ships is the measurable
  half: docket's own credentials stop reaching a task's processes (§8).

## What this reverses or amends

| Earlier decision | Now |
| --- | --- |
| P19-9: isolation is opt-in (`docket gates isolate on`) | Reversed: on by default; `isolate off` is an explicit, audited opt-out. |
| `sandbox_availability`: docker before bwrap | Reversed: bwrap first. |
| ADR 0004 (D-23): the `--network none` / `--unshare-net` lockdown is deferred | Amended: the mechanism ships as an opt-in mode; the default stays open. |
| ADR 0019 cut: `fetch` results not screened | Closed by §7. |

## Cut and deferred

| Item | Status | Trigger or reason |
| --- | --- | --- |
| A `kind: autonomy` document (domain → recipe, models, checks, authority) | Deferred | Nothing produces one. docket enforcing a document that no verifier emits is unwired machinery by construction. Trigger: a verifier that emits it. |
| Minting per-task credentials | Deferred | No issuer. Trigger: a pod that needs a scoped credential from an issuer docket can call (e.g. a GitHub App). |
| A retention policy for finished task worktrees | Deferred | Trigger: a measured disk or `git worktree list` cost. |
| `run:` steps and `verifyCmd` in the jail | Cut | They are the operator's own commands, from `pod apply`, and the verify gate needs the host toolchain. |
| Check recipes reading overrides from the process environment | Carried | Needs `${var}` in `run:`, a pipeline-format change. |
| Phase 36's carried items (consult registry, `approve_task` scope, `question.taskId`, options in channels) | Carried | ADR 0018. |

## Test discipline

- Every new jail behaviour is proven with a real backend where the host has one, and skips with a
  named reason where it does not (the `test_sandboxed_exec.py` convention). A unit test of an argv
  builder is not enough evidence for §3 or §4: the acceptance runs `git commit` and a socket
  connect inside a real bwrap.
- Default-on changes what a test gets when it writes no `fleet.json`. A test that wants no jail
  says so in its fixture. No suite-wide autouse switch turns isolation off, because that would
  hide the default the phase ships.
- The integrator owns the seams: §1 × §3 (a default-on dispatch in a task worktree commits), §4 ×
  §5 (a jailed MCP server under `network none` cannot connect out), and §7 × ADR 0019 §2 (one
  screening function, both callers).
