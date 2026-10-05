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
| A retention policy for finished task worktrees | Done (W89-4) | The operator asked (2026-10-05): `docket pod <p> worktrees prune`. |
| `run:` steps and `verifyCmd` in the jail | Cut | They are the operator's own commands, from `pod apply`, and the verify gate needs the host toolchain. |
| Check recipes reading overrides from the process environment | Done (W89-7) | A `run:` step's `env:` map, not `${var}` interpolation (no shell-injection surface). |
| Phase 36's carried items (consult registry, `approve_task` scope, `question.taskId`, options in channels) | Done (W89-5, W89-8, W89-9) | See "Closed by Waves 89–90". |

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

## Live run (2026-10-05)

Run against the local llama.cpp endpoint (`127.0.0.1:8081`, 16k context,
`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`), with a throwaway `HOME`, model `local/local-model`, and a
default `docket init` pod (Lead, Implementer) on a git repo. No isolation command was run first.

- `gates status` showed `Workspace isolation: on (default)` and `Network: open (default)`;
  `doctor` named the backend a turn would use: `bwrap`.
- **Isolation by default:** a task asked the Implementer to add `square(x)` and commit it from the
  `bash` tool. It finished `done` in 2 hops (2m54s). The commit landed on the task's own branch in
  its task worktree, from inside the jail (30 `bash` results carried `sandbox: bwrap`). The host
  repository's `.git/hooks` held only the samples afterwards.
- **Network none:** after `docket gates network none`, a task ran a `python3 -c` that opens
  `http://example.com`. Inside the jail it failed with `Temporary failure in name resolution`,
  and the output was written to the task worktree. The hop then parked on an unrelated approval:
  the model improvised `export GIT_DIR=...`, and `export` is not on the curated allowlist.
- **Network none with isolation off:** the Lead hop was refused before any model call, with a
  message naming both fixes.
- Found and scheduled as P38-10: that one refusal wrote three `network.refused` audit entries 2 s
  and 4 s apart. Both posture refusals returned the retryable `daemon_error` kind, so dispatch
  retried a deterministic refusal.

### Live run, part 2: a stdio MCP server in the jail (2026-10-05)

`docket harness run` against the same endpoint, in a throwaway `DOCKET_HOME`, with a stdio test
server (`probe`, run by the repository's Python) exposing `write(path)` and `dial()` (a TCP
connect to `1.1.1.1:53`). The model was told to write one file outside the workspace, one inside,
and to dial.

- Isolation on by default, network open: the inside file was written and the outside one was not;
  `dial` returned `connected`.
- `docket gates network none`: `dial` returned `network-error 101` (`ENETUNREACH`) from inside the
  jail; the outside write still did not happen.
- The same server re-added with `--no-isolate`: both files were written. The operator's assertion
  is what turns the jail off, and nothing else does.
- Measured before P38-11: `code-intel`'s `ast-grep` server (`uvx --from git+...`) cannot start in
  the jail even with a warm cache (`Read-only file system` on `~/.cache/uv`). The recipe now
  declares it `isolate: false`; `language-intel` stays jailed, unmeasured, because its binary is
  not installed on this host.

## Closed with, and carried

Integrator corrections made while merging (each is in the card's status line on the board):
95 tests depended on the host having bwrap (now an explicit `record_isolation_off` per fixture);
a writable common `.git` let the jail plant hooks or `core.fsmonitor` (now `hooks`, `config` and
`config.worktree` are read-only overlays); the first symlink fix still followed a symlinked
directory, and its general form also closed a `..` glob selector that a smoke test had pinned as
reachable; the redaction fix renumbered a spec that two other specs cite by number.

Carried to the next phase, by name:
- `docket doctor` lists unjailed MCP servers from the global registry only, not a pod's;
  `config explain` and `recipes show --json` do not show `isolate`;
- a submodule's hooks (`.git/modules/*/hooks`) and `.git/info` are not overlaid read-only;
- docker's default image has no `git` or `python3`, so only the bwrap jail is proven to commit;
- `docker --network none` is proven by argv only, with no real-docker oracle;
- stopping `docket serve` waits for in-flight pod sweeps, with no second-signal abandon;
- the Phase 37 and 36 carried items not addressed here (worktree retention, check recipes reading
  the process environment, the four Phase 36 items) and the deferred `kind: autonomy` and
  credential minting.

## Closed by Waves 89–90 (2026-10-05)

The operator asked to close every carried item. Ten cards (W89-1..10, no phase), Sonnet workers and
one Haiku worker in isolated worktrees, one integrator. Every item above is closed except the two
deferred to triggers nothing has fired (`kind: autonomy`, credential minting):
- `doctor` lists unjailed MCP servers per pod; `config explain` and `recipes show --json` carry
  `isolate` (W89-1).
- The jail cannot write git metadata the host later runs: submodule git dirs, a linked worktree's
  `.git` file and `gitdir`/`commondir`, `info/attributes`; a missing `hooks/` dir or attributes
  file is created empty first, because the jail could otherwise create it (W89-2).
- A second stop signal makes `serve` abandon in-flight sweeps (W89-3); `worktrees prune` (W89-4);
  options in channel notifications and Telegram `/answer <task> <id>` (W89-5); a real-docker oracle
  for commit and `network none`, and a `doctor` probe of the jail image (W89-6); `env:` on `run:`
  steps (W89-7); the parked consult question persisted instead of held in process, and a harness
  consult's `taskId` is the run token (W89-8); `approve_task` across a task's later hops and all
  four approval channels (W89-9).

Integrator corrections, each found reviewing a green card: the inbox `TaskView` never carried
`question`/`brief`, so no notification ever had a question to show (the sixth unwired-machinery
instance, found by the W89-5 worker); W89-8 first carried the question base64-encoded in the token,
which reaches hop errors and the trace past redaction; W89-9 first minted a task grant for every
role's hop; W89-4 would have pruned a task `dispatch --resume` re-claims, and `git_branch_merged`
ignored git's `+` marker; W89-1 grew the shrink-only layout baseline instead of adding a test.

### Live run (2026-10-05)

Local endpoint, throwaway `HOME`, bwrap backend, `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`:
- A harness turn in a linked worktree of a repository with a submodule ran four `python3`/`git`
  calls the gate **allowed**: rewriting `.git`, writing `hooks/post-commit` and the submodule's
  `hooks/post-merge` all failed in the jail, and the host files were unchanged. The jailed
  `git commit` failed too: `Author identity unknown`. The jail passed only `PATH`, so an identity
  from `GIT_AUTHOR_*` or a non-default `HOME` (and any identity under Docker) never reached git.
  Fixed: the jail receives the operator's git identity, never a credential; re-run, the commit
  landed as `demo <demo@example.com>`. The test that should have caught it passed the identity by
  hand through `env=`.
- A pod with a consult-first Lead, two Implementer steps running `git push origin production` and
  a `run:` step with `env: {GREETING: hello}`, `approvalMode park`: the Lead's consult parked the
  task, the persisted question was taken (none left on disk), `docket inbox` showed it, and the
  operator chose the option the model had **not** recommended. Each push parked; `approve_task`
  recorded a task grant and the next hops got minted pre-grants. The model never re-issued the
  identical command (it rephrased with `cd ...`), so live reuse was not observed: exact matching
  refused the variant, as specified; reuse is proven by the integration tests. The `run:` step saw
  `hello`; the task finished `done` after 7 hops.
- `worktrees prune` kept that task's worktree: the verify command's `__pycache__/` made every
  Python task "dirty". Fixed: only tracked changes keep a worktree, untracked artifacts are counted
  and discarded; re-run, it removed the worktree and the merged branch.
- `doctor` named `probe (pod myapp)` as unjailed and, with Docker forced, warned that
  `alpine:3.20` has no `git`.
- `docket serve --dispatch` with a hop in flight survived the first SIGINT
  (`stopping: waiting for 1 pod sweep(s); signal again to abandon`) and exited 130 on the second;
  the run recorded `requestedAt`, `observedAt` and `stoppedAt`, and the task ended `cancelled`.
- A harness `--contract 1.1` consult: `question.taskId` equalled the run token; the answer resumed
  the turn to `ok`.

- The documentation capture found one more: told to run `git push origin production`, a Lead now
  consults the operator first, and `high-risk-deploy`'s `matches` (any tool's rendered call) fired
  on the question's text, so the task parked on an approval *to ask*, then again on the question.
  An `ask` on `consult` now resolves to `allow` (the consultation is the human's decision); `deny`
  still denies.

Still deferred, by trigger: `kind: autonomy` (a verifier that emits one) and per-task credential
minting (an issuer a pod needs). Not pushed.
