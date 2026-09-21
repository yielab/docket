# Wave 36 worker packets — audit-found defects (opened 2026-09-19)

One start packet per card of `TODO.md` § "WAVE 36". The card is the contract (trigger, goal,
acceptance); this file is the map (where the code is, what you may touch, how to prove RED, what
to return). Read **§0 once, then only your own packet.** Do not read the other packets, the whole
board, `ROADMAP.md`, or a whole spec.

Line numbers were measured at `834321d` and drift. Re-locate every symbol with `rg -n` before
editing; the symbol name is the locator, the line number is a hint.

## 0. Rules for every worker

**Load your card, nothing else:**
`python3 .agents/skills/docket-roadmap/scripts/card_packet.py W36-C<N>`

**Isolation.** One card, one branch `w36-c<N>-<slug>`, one git worktree. Base = the commit that
opened this wave (`git log -1 --format=%h -- .agents/handoffs/wave-36-worker-packets.md` on
`main`). If your worktree was created from an older commit, rebase onto that base before starting
and compare with `git merge-base main HEAD`, never with `HEAD~N`.

**Never touch the operator's real state.** Every command that runs docket sets both variables to
a directory you created under your own temp root:

```bash
export W=$(mktemp -d) && export HOME=$W/home DOCKET_HOME=$W/home/.docket && mkdir -p $DOCKET_HOME
```

pytest already isolates `DOCKET_HOME` through autouse fixtures; use `repoint_docket_home` when a
test needs a second home. Never read or write `~/.docket`. Never call a real model endpoint: tests
use the fake drivers the neighboring tests already use.

**Order of work (AGENTS.md change contract).** 1. Read the owning spec *section* named in your
packet and the neighboring tests. 2. Amend the spec requirement text. 3. Write the RED test and
**see it fail on the base for the stated reason** (a test that fails for another reason is not
RED). 4. Implement the smallest change. 5. Focused gates, then worker gates.

**Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py` and never
prints; it raises or returns typed results and `cli/`/`serve.py` render them. Docket-owned JSON is
written only through `edges/store.py`. Every shell-out lives in `edges/adapters/`. Every tool call
goes through `core/tools.py::dispatch_tool`.

**Integrator-owned this wave — do not edit, return the text instead:**

| Path | What you return instead |
| --- | --- |
| `TODO.md`, `ROADMAP.md` | nothing; report outcome |
| `README.md`, `CHANGELOG.md` | the exact sentence / `[Unreleased]` line you would add |
| `CONTRIBUTING.md` (test counts) | nothing; the integrator re-measures |
| `specs/README.md`, and every spec's `**Version**` / `**Last Updated**` header and `## Changelog` section | one changelog line per spec you edited |
| `scripts/maint/comment-baseline.json`, function-span baseline | the measured count if it moved |

You **do** edit the requirement text, examples and Status prose of the spec sections your packet
names. Several specs are shared between cards (`pod-dispatch`, `serve-read-api`, `cli-interface`);
the header/changelog rule above is what keeps those merges clean. Stay inside your named section.

`docs/commands.md` is generated. If you change a Typer docstring or help text, run
`uv run python scripts/gen_cli_docs.py` and commit the result; the integrator regenerates it on
any merge conflict, so never hand-merge that file.

**Goldens.** `bash tests/golden/run.sh verify-all` must stay byte-identical unless your packet
says a golden changes. If it does, regenerate only the named case and list every changed line
with the reason in your return. Never regenerate to make an unexpected diff go away.

**Never** edit counting logic in `scripts/metrics.py` or `scripts/validate-specs.sh`. Never use
`git stash`. Never widen scope: an adjacent defect becomes a locator under "Later follow-ups".
If you need a forbidden path, stop and return the contention.

**Test lanes** (`specs/test-framework.md` § "Lanes and placement"): unit = one file per `src/`
module under `tests/unit/` with a `SUBJECT`; integration = cross-module or subprocess behaviour
under `tests/integration/` with an importable `SUBJECT`; a test that reads prose or builds an
artifact is agent-lane and is not needed by any card here.

**Worker gates** (all must pass before you return):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q                       # default lanes
uv run pytest -q tests/guards          # includes the 150-line function-span ratchet
bash tests/golden/run.sh verify-all
bash scripts/validate-specs.sh
uv run python scripts/gen_cli_docs.py --check
uv run python scripts/maint/comment_lint.py --check <every .py file you touched>
```

`scripts/metrics.py --check` is **expected to fail** on a branch that adds tests (the count lives
in integrator-owned `CONTRIBUTING.md`). Do not fix it; say so in the return.

**Commit.** One commit per card unless the packet says otherwise. Subject `Type: description`
(`Fix:`, `Add:`, `Remove:`, `Docs:`, `Test:`), ASCII only, a body that says what was false and
what is now true. **No AI mention and no `Co-Authored-By` trailer of any kind** — this repository
rule overrides any tool default. Before committing: `git diff --cached | command grep -nE
'/home/|/tmp/claude|@gmail'` must print nothing. Do not push.

**Return** (1,500–3,000 characters, a delta, no logs):

```text
Card / branch / commit:
Outcome: complete | partial | blocked
User-visible behavior:
Changed paths and owned functions:
Spec sections edited + one changelog line per spec:
README / CHANGELOG lines for the integrator:
RED evidence: <test node id> failed on base with <one-line reason>
Focused tests: <command> -> <result>
Worker gates: <pass | first failing gate>
Goldens changed: none | <case>: <line-by-line reason>
Missing / failed:
Pending in this card:
Later follow-ups (locators only):
Contention / merge note:
```

## 1. Batches and merge order

Scheduled by file contention. A batch starts only when the previous one is merged and green.

| Batch | Cards (parallel inside the batch) | Merge order |
| --- | --- | --- |
| 1 | C1, C2, C4, C5, C6, C7 | C1, C2, C4, C5, C7, C6 |
| 2 | C3, C8, C9, C10 | C3, C8, C9, C10 |
| 3 | C11 | — |

Function-level ownership of the hot files (nobody else may touch a function they do not own):

| File | Owner -> functions |
| --- | --- |
| `src/docket/serve.py` | C1 -> `do_GET` project-segment branches, `_handle_post_tasks`, `_handle_post_dispatch`, `_handle_post_pods` · C3 -> `_handle_post_approvals` |
| `src/docket/cli/_mcp.py` | C2 -> `run_mcp`, `_servers_*` · C4 -> `tool_approvals_grant`, `tool_approvals_deny` |
| `src/docket/cli/_agents.py` | C1 -> `_provision_pod_from_spec`, `_cmd_add_declarative` · C5 -> `run_maintain` (rebuild branch only), `_maintain_rebuild` · C8 -> the `info --json` builder |
| `src/docket/cli/__init__.py` | C2 -> `cmd_mcp` · C8 -> the `list --json` builder, `cmd_snapshot` · C9 -> the root callback (`--debug`), the `models` PRICE footer · C11 -> docstrings of `cmd_pod`, `cmd_init`, `cmd_maintain`, `cmd_scope`, `_delete_pod` |
| `specs/functional/pod-dispatch.spec.md` | C4 -> approval requirement 4 · C6 -> "Pipeline order and participation" · C7 -> Cancellation requirement 2 |
| `specs/data/serve-read-api.spec.md` | C1 -> `POST /pods` + project-segment errors · C3 -> `POST /approvals/<token>` channel text |

---

## W36-C1 — validate project ids at the core boundary

**Branch:** `w36-c1-project-id` · **Batch 1** · merges first.

**Where.**
- `src/docket/core/provisioning.py::slugify` (~L17) — the only id normaliser. Add the validator
  next to it.
- `src/docket/core/pod_provisioning.py::provision_pod` (~L635) — receives `project` verbatim and
  builds `_cfg` paths and `<project>-<role>` member ids from it. `_project_provision_lock`
  (~L428) hex-encodes the name, so the lock itself is safe; the workspace paths are not.
- `src/docket/serve.py::_handle_post_pods` (~L984) — checks only `isinstance(project, str) and
  project`. Its `except` ladder maps `BlueprintError`/`VerifyCmdError` -> 400,
  `PodAlreadyExistsError` -> 409, `PodProvisionError` -> 500.
- `src/docket/serve.py` project path segments: `do_GET` branches `/tasks/<project>` and
  `/traces/<project>`, `_handle_post_tasks`, `_handle_post_dispatch`.
- `src/docket/cli/_agents.py::_cmd_add_declarative` (~L355) reads `spec["id"]` with only
  `.strip()`; `_provision_pod_from_spec` (~L313) passes it on. `run_init` (~L112) already
  slugifies (L170) and must keep working unchanged.

**Do.**
1. `core/provisioning.py`: `class ProjectIdError(ValueError)` and
   `validate_project_id(project: str) -> str`. Rule: non-empty, at most 64 characters, matches
   `^[a-z0-9]+(?:-[a-z0-9]+)*$` (exactly the set `slugify` can emit). Returns the id, raises
   `ProjectIdError` with a message that names the rule and **does not echo more than 40
   characters** of the rejected value.
2. Call it as the first statement of `provision_pod`, before the lock and before any path is
   built. This is the fix; everything else is a friendlier error at an outer layer.
3. `serve.py`: map `ProjectIdError` -> `400` in `_handle_post_pods`; validate the path-derived
   `project` in the four other handlers -> `400 {"error": ...}`, after the auth check (an
   unauthenticated caller still gets 401 first).
4. `cli/_agents.py`: in the declarative path, an entry whose `id` fails validation is reported
   with `ui.error` and makes the command exit 1 without provisioning that entry.

**Spec.** `specs/validation/input-validation.spec.md` §1: replace the unimplemented
length-3–50 / reserved-word rules with the shipped rule and point "Reference" at
`validate_project_id`; remove §1 from the "not implemented" list in the Status prose and in the
implementation note (leave §2, §4, §5 exactly as they are — C11 owns them).
`specs/data/serve-read-api.spec.md`: add the `400` row to `POST /pods` and to the
`/tasks`, `/traces`, `/dispatch` project-segment error text.

**RED** (add to `tests/integration/test_serve_pods_endpoint.py`, following its existing server
fixture): `POST /pods {"project": "../../escaped", "path": <tmp>}` with a valid Bearer. On the
base this returns `201` and creates directories **outside** `DOCKET_HOME/workspaces`. After the
fix: `400`, and the oracle is the filesystem — assert no path containing `escaped` exists
anywhere under the test's temp root, and `fleet.json` has no such agent. Also add a unit test for
`validate_project_id` (accepts `a`, `docket-dev`, `x1-y2`; rejects `""`, `"../x"`, `"a/b"`,
`"A"`, `"a--b"`, `"-a"`, `"a-"`, a 65-character id, `"a:b"`) in the unit file for
`core/provisioning.py` (create it per the lane rule if it does not exist), and one declarative
test (`docket init --from` with a bad `id` -> exit 1, nothing provisioned).

**Non-goals.** No reserved-word list. No path validation of `location` (§2). No change to
`slugify`. No migration of existing pods (every id `slugify` produced already passes — assert
that with a property-style test over a few names). Do not touch `_handle_post_approvals`.

**Pitfalls.** `_handle_post_pods` is long; if your edit pushes it over the 150-line ceiling
(`tests/guards/test_function_span.py`), extract a small module-level helper rather than raising
the baseline. `core/` must raise, not print.

**Focused:** `uv run pytest -q tests/integration/test_serve_pods_endpoint.py tests/unit/test_serve.py tests/unit/core -k "provision or pods or project_id"`

---

## W36-C2 — make `docket mcp servers add` reachable from the real CLI

**Branch:** `w36-c2-mcp-servers-add` · **Batch 1**.

**Where.**
- `src/docket/cli/__init__.py::cmd_mcp` (~L2145): registered with
  `context_settings={"allow_extra_args": True, "ignore_unknown_options": True}` and forwards
  `ctx.args`. Click consumes the first literal `--`, so it never reaches `ctx.args`.
- `src/docket/cli/_mcp.py::_servers_add` (~L373): `if "--" not in tail:` -> error.
- `src/docket/__main__.py` (~L109) pre-processes `sys.argv` for aliases/removed commands —
  **forbidden to edit**, but it shows the raw argv is intact when `cmd_mcp` runs.
- `tests/integration/test_mcp_servers_cli.py` calls `_mcp.run_mcp("servers", [...])` with `--`
  already in the list (L103, L137, L144, L153): it never crosses the Click seam.

**Reproduce (base):**
`docket mcp servers add playwright -- npx -y @playwright/mcp@latest` -> exit 1, "Missing '--'
separator". That command is the help text's own example.

**Do.** Make the separator survive to `_servers_add`. The fix lives in `cmd_mcp` and/or
`cli/_mcp.py` only. Two acceptable shapes: (a) `cmd_mcp` recovers the argument tail from
`sys.argv` (everything after the `mcp` token) when `sys.argv` is a docket invocation, falling
back to `ctx.args`; or (b) restructure so Click does not strip it. Whichever you choose, **all
existing `run_mcp` tests stay green unchanged** and these hold through the real entry point:
- `... add s -- npx -y pkg` stores command `["npx", "-y", "pkg"]`.
- `... add s --env K=V --timeout 5 -- cmd --env X=Y` stores env `{K: V}`, timeout 5, and command
  `["cmd", "--env", "X=Y"]` (flags after `--` are the server's, verbatim).
- `... add s npx -y pkg` (no separator) -> exit 1 with the existing message.
- `... add s --` (empty command) -> exit 1.

**Spec.** `specs/functional/mcp-client.spec.md` requirement 21 contradicts itself: its first
sentence says everything after `--` is verbatim, its second says `--env`/`--timeout` after `--`
MUST be rejected. Rewrite the second sentence: those flags are rejected only when malformed or
when no `--` is present; after `--` they belong to the server command.

**RED.** New test in `tests/integration/test_mcp_servers_cli.py` that runs
`[sys.executable, "-m", "docket", "mcp", "servers", "add", "playwright", "--", "npx", "-y",
"@playwright/mcp@latest"]` as a subprocess with an isolated `HOME`/`DOCKET_HOME` env, asserts
exit 0, then asserts `load_mcp_servers()` (or the stored JSON read through `edges/store.py`)
holds the command list. Fails on base with exit 1. A `CliRunner` test alone is **not** enough:
`CliRunner` does not set `sys.argv`, so add it only in addition if your fix supports it.

**Non-goals.** No change to `mcp serve`, to the stored schema, or to `__main__.py`. Do not touch
`tool_approvals_*` in `cli/_mcp.py` (C4 owns them).

**Goldens.** `help.golden` mentions `servers add`; it must stay byte-identical.

**Focused:** `uv run pytest -q tests/integration/test_mcp_servers_cli.py`

---

## W36-C3 — HTTP may not forge an approval's channel

**Branch:** `w36-c3-approval-channel` · **Batch 2** (after C1: shares `serve.py` and the spec).

**Where.** `src/docket/serve.py::_handle_post_approvals` (~L812): `channel =
req_body.get("channel", "http")`, accepted if it is in `core/approval.py::APPROVAL_CHANNELS`
(~L37: `cli, http, mcp, telegram, timeout, tack`). So an HTTP caller can record a decision as
`cli`, `telegram`, `mcp` — or a **grant** as `timeout`, which
`specs/data/serve-read-api.spec.md` (~L128) says only ever pairs with `denied`.

**Do.** In `serve.py`, define the set of channels the HTTP transport may claim:
`{"http", "tack"}` (module-level constant, with a one-line comment: the transport is HTTP; `tack`
is the one named HTTP client). Anything else -> `400 {"error": "Unrecognised channel: ..."}`
before any approval state changes. Default stays `"http"`. Do **not** change
`APPROVAL_CHANNELS` in core: the other values are legitimately written by their own surfaces.

**Spec.** `specs/data/serve-read-api.spec.md`, the `POST /approvals/<token>` section (~L480 and
~L529): the accepted body values become `http | tack`; keep the metric's label set unchanged.

**RED.** In `tests/unit/test_serve.py` next to the existing channel tests: a pending approval,
`POST /approvals/<token> {"action": "grant", "channel": "timeout"}` -> on base `200` and the
audit entry carries `channel=timeout`; after the fix `400`, the approval is **still pending**
(oracle: `approval_get(token)["state"] == "pending"`) and no `approval.*` audit entry was
written. Repeat for `"cli"`. Keep a positive test for `"tack"` and for the default.

**Check first.** `rg -n '"channel"' tests` — if an existing test posts `channel: "cli"` or
`"telegram"` over HTTP, it encoded the bug; change it and say so in the return.

**Non-goals.** No auth change, no new channel, no change to CLI/MCP/Telegram paths.

**Focused:** `uv run pytest -q tests/unit/test_serve.py tests/unit/test_serve__auth.py tests/unit/core/test_approval.py`

---

## W36-C4 — an MCP grant or deny resolves the dispatch task it gated

**Branch:** `w36-c4-mcp-approval-resume` · **Batch 1**.

**Where.** `src/docket/cli/_mcp.py::tool_approvals_grant` / `tool_approvals_deny` (~L156–180).
Both call `_approval.approval_grant/deny(token, channel="mcp")` and return; neither calls
`core/dispatch.py::resolve_waiting_approval` (~L1990). The three other channels do:
`cli/_approve.py` (L68–78, **including the `ApprovalNoop` branch**), `cli/_deny.py` (L39–45),
`serve.py::_handle_post_approvals`, `core/telegram.py` (~L197, L202). Effect: a pod-dispatch task
in `waiting_approval` that is decided over MCP stays `waiting_approval` forever — a grant does
not return it to `pending`, a deny does not fail it.

**Do.** Mirror `cli/_approve.py` exactly: call `resolve_waiting_approval(token, "granted" |
"denied")` after a successful decision **and** in the `ApprovalNoop` branch before re-raising as
`McpToolError`. Fix both docstrings ("Identical to `docket approve`" must become true).

**Spec.** `specs/functional/pod-dispatch.spec.md`, approval requirement 4 (the list of callers of
`resolve_waiting_approval`): add the MCP tools. `specs/api/mcp-server.spec.md`, the
`approvals_grant` / `approvals_deny` tool descriptions: state that a gated dispatch task resumes
or fails. Requirement text only; no header/changelog.

**RED.** In `tests/integration/test_mcp_server.py`: build the same `waiting_approval` fixture the
CLI/HTTP resume tests use (`rg -n 'resolve_waiting_approval|waiting_approval' tests` to find
it), call `tool_approvals_grant(token)`, assert the task's status is `pending` with the gate
override recorded; second test, `tool_approvals_deny(token)` -> task `failed`,
`failureKind == "approval_denied"`. Both fail on base (status stays `waiting_approval`).

**Non-goals.** Do not touch `run_mcp`/`_servers_*` (C2). No change to `core/dispatch.py`.

**Focused:** `uv run pytest -q tests/integration/test_mcp_server.py`

---

## W36-C5 — `maintain rebuild` never deletes memory and refuses a pod member

**Branch:** `w36-c5-maintain-rebuild` · **Batch 1**.

**Where.** `src/docket/cli/_agents.py::_maintain_rebuild` (~L1199) and its call in
`run_maintain` (~L913, currently ignores a return value). Today it: backs up five top-level
files (not `memory/`), regenerates through the **legacy flat-agent** `_create_workspace`
(~L481), then `unlink`s every `memory/*.md` — no distillation, no copy. For a pod member that
also replaces the role prompt (e.g. Reviewer) with the generic template, writes a `TOOLS.md` a
Lead must not have, writes `agent:<id>:default` into SOUL.md and resets `HEARTBEAT.md`.
`clean`/`reset` next to it show the project's rule: memory is never bare-deleted.

**Do.**
1. Delete the `memory/*.md` unlink loop. Rebuild regenerates templates; it has no reason to
   remove logs. `MEMORY.md` stays as it is (it is backed up and not regenerated).
2. Refuse a pod member: if the agent's meta carries a `pod` key (written by
   `core/pod_provisioning.py` ~L325) or a non-empty pod `role`, print a `ui.error` that says
   rebuild supports only legacy flat agents and that a pod member's files are owned by pod
   provisioning, and return exit 1 **before** the confirmation prompt and before any write.
3. `_maintain_rebuild` returns `int`; `run_maintain` returns it.
4. Preserve the current `HEARTBEAT.md` dispatch block? No — out of scope; a flat agent has none.

**Spec.** `specs/functional/agent-lifecycle.spec.md` § "rebuild - Complete Rebuild" (~L168) and
the destructive-commands paragraph (~L199–201): rebuild backs up, regenerates the template
files of a **legacy flat agent**, never touches `memory/`, and refuses a pod member with exit 1.
Remove the claims that it does "everything from reset" and generates a new session key.

**RED.** New integration tests (extend `tests/integration/test_auth_context_maintain_keys_add.py`
if its fixtures fit, otherwise a new `tests/integration/test_maintain_rebuild.py`,
`SUBJECT = "docket.cli._agents"`): (a) flat agent with `memory/2026-01-01.md`; run rebuild with
stdin patched as a TTY and the id typed; assert the log file still exists with identical bytes —
fails on base (file deleted). (b) a provisioned pod member; rebuild -> exit 1, SOUL.md bytes
unchanged, no `.backup-*` directory created — fails on base (returns 0 and rewrites).

**Non-goals.** No role-aware re-render for pod members (follow-up; name
`pod_provisioning._write_member_workspace` as the locator). No change to `clean`/`reset`.
Do not touch `_provision_pod_from_spec`/`_cmd_add_declarative` (C1) or the info JSON (C8).

**Help text.** `docket maintain --help` lives in `cli/__init__.py::cmd_maintain` — C11 owns that
docstring. Return the sentence you need changed; do not edit it.

**Focused:** `uv run pytest -q tests/integration -k "maintain"`

---

## W36-C6 — dispatch runs the pod's blueprint pipeline

**Branch:** `w36-c6-blueprint-pipeline` · **Batch 1**, merged **last** (behaviour change).

**Where.**
- `src/docket/core/dispatch.py::effective_pipeline` (~L374): with `spec is None` it loads
  `_pipeline.load_pipeline(None).spec` — always `core/pipeline.py::default_pipeline()` — and
  only patches the reviewer rework budget. Nothing on the dispatch path reads a blueprint.
- `src/docket/core/blueprints.py`: `BUILTIN_BLUEPRINTS` (~L196–236) attaches
  `_research_pipeline()`, `_content_pipeline()`, `_ops_pipeline()`; `software` and
  `agentic-product` attach `default_pipeline()`. Module docstring (L5) says "attached but not
  executed".
- `core/pod_provisioning.py` (~L350) records `meta["blueprint"] = <name>` on the members it
  provisions. Read it for the **Lead**: `_fleet.meta_get(_pod.member_id(project, "lead"),
  "blueprint", "")`.
- Callers that pass `None`: `docket pod <p> dispatch`, `docket pipeline plan|run` without
  `--file` (`cli/_pipeline.py` renders `effective_pipeline`), `POST /dispatch/<p>`, the sweep,
  schedules, Telegram `/delegate`.

**Do.** In `effective_pipeline`, when `spec is None`: resolve the Lead's `blueprint` meta; if it
names a built-in (or user) blueprint, start from that blueprint's `default_pipeline`; if the key
is absent, empty or unknown, start from `default_pipeline()` exactly as today (**zero change for
every existing `software` pod and every pre-blueprint pod**). Then apply the existing
rework-budget patch unchanged (it already iterates any `VerdictGate` with a rework edge, so the
Critic -> Writer edge gets the pod's `maxReworkCycles` too — assert that). Look the blueprint up
with `core/blueprints.py::get_blueprint(name)` (~L269; it raises `BlueprintError` on an unknown
name — catch that and fall back); do not duplicate the registry. Check for an
import cycle (`dispatch` -> `blueprints` -> `pipeline`/`archetypes`): import lazily inside the
function if one appears. Update the `blueprints.py` module docstring line to the truth.

**Spec.** `specs/functional/pod-blueprints.spec.md`: delete the "Known gap" paragraph (~L41–47)
and the matching note (~L275); state that a pod dispatched without a caller-supplied spec runs
its blueprint's `defaultPipeline`. `specs/functional/pod-dispatch.spec.md` § "Pipeline order and
participation": the resolution order is caller spec -> Lead's blueprint pipeline -> built-in
default. Requirement text only.

**RED.** `tests/unit/core/test_dispatch.py` (or the file that already tests
`effective_pipeline`; `rg -n effective_pipeline tests`): provision a `research` pod in the
isolated home, call `effective_pipeline(project, None)`, assert the step roles are
`lead, researcher, analyst, writer, critic` — on base they are `lead, implementer, reviewer,
tester`. Plus: `software` pod -> identical object/steps as before; Lead meta with
`blueprint: "nope"` -> built-in default, no raise; a pod whose Lead has `maxReworkCycles = 3`
under `content` -> the critic gate's rework `max_cycles == 3`. One integration assertion in
`tests/integration/test_pipeline_cli.py`: `docket pipeline plan <research-pod>` lists the five
research steps with none "skipped — role not in pod".

**Non-goals.** No new CLI flag, no pipeline export command, no change to `--file` precedence,
no change to gate semantics or to `core/orchestrator.py`. The live dispatch of a real `ops` pod
(ApprovalGate -> `waiting_approval`) against the local model is **integrator** evidence, not
yours; but do add a fake-driver test that an `ops` dispatch reaches `waiting_approval` at the
approval step if the existing fixtures make that cheap — otherwise name it a follow-up.

**Return for the integrator.** A `CHANGELOG [Unreleased] ### Changed` line: non-`software` pods
now run their blueprint's roles and gates on dispatch, which means more hops and more tokens
than the Lead-only behaviour they had.

**Focused:** `uv run pytest -q tests/unit/core/test_dispatch.py tests/unit/core/test_blueprints.py tests/unit/core/test_pipeline__spec.py tests/integration/test_pipeline_cli.py`

---

## W36-C7 — a timed-out verify command leaves no orphan

**Branch:** `w36-c7-verify-process-group` · **Batch 1**.

**Where.** `src/docket/edges/adapters/system.py::run_verify_cmd` (~L264): after the high-risk
refusal it runs `subprocess.run(cmd, shell=True, cwd=..., capture_output=True, text=True,
timeout=timeout)`. On timeout Python kills only the `sh` child. Measured on base:
`run_verify_cmd("sleep 6 & wait", ".", timeout=1)` returns at 1.0 s and `sleep 6` is still
alive afterwards. `src/docket/edges/adapters/toolbox.py` already has the project's
process-group kill (`_kill_group`, used by `run_bash`, ~L347–366) — read it and follow the same
shape; do not import a private name across modules if the layering test objects, copy the
four-line pattern instead and say so.

**Do.** Replace `subprocess.run` with `subprocess.Popen(..., start_new_session=True)` +
`communicate(timeout=timeout)`; on `TimeoutExpired` kill the whole group
(`os.killpg(proc.pid, SIGKILL)`, tolerate `ProcessLookupError`), reap it, and return the same
`(False, "[verify timed out after {timeout}s]")` string as today. Output truncation
(`_VERIFY_MAX_OUTPUT`), the refusal path, `FileNotFoundError`/`OSError` handling and the return
type stay byte-identical.

**Spec.** `specs/functional/pod-dispatch.spec.md`, Cancellation requirement 2: it currently
claims any verification command runs in its own session **and** that cancelling kills it.
Make it true and no more: the verify command runs in its own session and its whole group is
killed on **timeout**; `docket runs cancel` does not interrupt an in-flight verify command (its
pid is not registered — `DocketDriver.run_turn` ignores `on_spawn`), so a cancelled run ends
when the verify command returns or times out. Name that as a known limit in the same
requirement.

**RED.** In `tests/integration/test_verify_gate.py` (or `test_retries_and_timeouts.py`, whichever
already exercises the timeout): run `run_verify_cmd` with a command that backgrounds a child
which writes its own pid to a temp file and sleeps 30 s, `timeout=1`; after return, poll up to
2 s for `os.kill(pid, 0)` to raise `ProcessLookupError`. On base the child survives. Use a
unique marker/pid file, never `pgrep` by name. Skip on non-POSIX if the file already has such a
marker.

**Non-goals.** No pid registration, no `on_spawn` plumbing, no change to `runs cancel`
(follow-up locator: `core/dispatch.py::_on_spawn` ~L1054).

**Focused:** `uv run pytest -q tests/integration/test_verify_gate.py tests/integration/test_retries_and_timeouts.py tests/integration/test_high_risk_enforcement.py tests/guards/test_no_subprocess_in_core.py`

---

## W36-C8 — CLI `--json` emits the types its spec and `/status.json` already use

**Branch:** `w36-c8-cli-json-shapes` · **Batch 2**.

**Where.** `budgetUsd` is **stored** as a string by every writer (`cli/__init__.py` ~L926,
`cli/_agents.py` ~L646, `core/pod_provisioning.py` ~L355) — leave storage alone. Emitters:
- `cli/__init__.py` ~L162 (`list --json`): `"budgetUsd": raw.get("budgetUsd", "")` -> string.
- `cli/_agents.py` ~L718 (`info --json`): same.
- `cli/__init__.py::cmd_snapshot` ~L2289 and ~L2312: `"lastActivity": last_activity(...)` ->
  `"—"` when there is no log (`core/memory.py::last_activity` ~L76).
- Already correct, use as the model: `serve.py` ~L63–66 (`float | None`) and
  `serve.py::_last_activity_or_never`; `cli/_cost.py` ~L72.

**Do.** One small pure helper for "stored budget -> `float | None`" in `core/` (next to
`pod_provisioning.parse_budget_usd` if it fits, otherwise `core/utils.py`), used by the two CLI
emitters **and** by `serve.py`/`_cost.py` only if that is a one-line swap with identical output
(otherwise leave those two alone — `serve.py` is not yours to restructure). `snapshot` emits
`"never"` for no activity, matching `/status.json`. Human-readable tables keep `—`.

**Spec.** `specs/data/cli-json-shapes.spec.md`: `list`/`info` `budgetUsd` is `number | null`;
snapshot `lastActivity` is `YYYY-MM-DD | "never"`. `specs/data/docket-meta.spec.md`: state that
`budgetUsd` is persisted as a string and emitted as a number (one sentence; fix the `5` example).

**Goldens — expected to change:** `tests/golden/cases/readonly/list_--json.golden` and
`info_myshop_--json.golden` (and a snapshot case if one exists). The old output contradicted the
spec, which is the allowed reason. Regenerate **only** those cases and list each changed line.

**RED.** Unit/integration assertions that `json.loads(list --json)` has
`isinstance(budgetUsd, (int, float)) or budgetUsd is None` for an agent with a budget and one
without; `snapshot` for an agent with no memory logs has `lastActivity == "never"`
(`tests/integration/test_edit_snapshot.py` is the neighbor).

**Non-goals.** No storage migration, no new keys, no change to `/status.json`.

**Focused:** `uv run pytest -q tests/integration/test_edit_snapshot.py tests/unit/test_serve__read_api.py -k "json or snapshot or budget"` then the golden suite.

---

## W36-C9 — retire two claims nothing backs: `--debug` and the PRICE override

**Branch:** `w36-c9-inert-claims` · **Batch 2**.

**Where.**
- `cli/__init__.py` root callback ~L94: `--debug` does `os.environ["DEBUG"] = "1"`.
  `rg -n 'DEBUG' src/` finds no reader. `cli/_help.py` ~L125: "`--debug  Verbose mode — or set
  DEBUG=1 in env`" (pinned by `tests/golden/cases/readonly/help.golden`).
  `scripts/gen_cli_docs.py` ~L314 and ~L635 document `DEBUG` as "reserved".
- `cli/__init__.py` ~L1330: the `docket models` footer says "override in docket-models.json".
  `core/models_policy.py::load_registry` reads `default`, `roles`, `rankAnchors` and legacy
  `profiles` only — no pricing key (pinned by `models.golden` line ~21).

**Do.**
1. `--debug`: keep the option **accepted** so existing scripts do not start exiting 2, but make
   it `hidden=True`, stop writing the environment variable, and remove the line from
   `cli/_help.py`. Remove the `DEBUG` row/mention from `scripts/gen_cli_docs.py`'s environment
   table (that is documentation data, not counting logic) and regenerate `docs/commands.md`.
2. Models footer: drop the "override in docket-models.json" clause; keep the "estimate from a
   snapshot (as of DATE)" part.

**Spec.** `specs/api/cli-interface.spec.md` Global options: `--debug` is a deprecated, hidden
no-op. `specs/functional/model-profiles.spec.md`: only if it still promises a pricing overlay
(`rg -n -i 'pricing.*overrid|override.*pric' specs/functional/model-profiles.spec.md`).

**Goldens — expected to change:** `help.golden` (one line removed), `models.golden` (footer
line). Reason: both strings were factually false. List the lines.

**RED.** A unit test that invoking the root callback with `--debug` leaves `os.environ` without
`DEBUG` (fails on base) and still exits 0; the golden diff is the oracle for the text.

**Non-goals.** No verbose mode is being built. Do not touch `cmd_mcp`, `cmd_snapshot`, the list
JSON builder or any command docstring (C2, C8, C11).

**Focused:** `uv run pytest -q tests/unit/cli tests/unit/test_cli_stubs.py` then goldens and `gen_cli_docs --check`.

---

## W36-C10 — budget warnings read the same estimate the dispatch gate does

**Branch:** `w36-c10-budget-warnings` · **Batch 2**.

**Where.** `src/docket/cli/_doctor.py::_check_budget` (~L219): computes `pct` from the
**recorded** cost in its `cost` argument. `DocketDriver` records `cost_usd = 0.0` by design, so
the `>= 80%` warning and the `over budget` error can never fire. The dispatch gate does not have
this problem: `core/dispatch.py::pod_gating_cost` (~L470–490) falls back to the token-based
estimate and labels it (`~$X (estimated — no cost recorded)`, ~L910/927). `cli/_cost.py` has the
runaway **cost** threshold check (~L218–221) with the same blind spot; its turn-count check is
fine.

**Do.** `_check_budget` and the `_cost.py` cost-threshold warning use the same gating figure the
dispatch gate uses, and print it with the same `~$… (estimated — no cost recorded)` label
whenever the figure is an estimate. **Never print an estimate as spend** and never relabel it.
Reuse `pod_gating_cost` (or the helper underneath it) — do not write a second estimator. If
`_check_budget`'s callers hand it per-agent recorded cost, change what they pass rather than
recomputing inside.

**Spec.** `specs/functional/cost-tracking.spec.md`, Enforcement requirement 5 (the sentence the
2026-09-19 audit added saying the warnings never fire): replace with the shipped behaviour.

**RED.** `tests/unit/cli/test__doctor.py`: an agent with `budgetUsd = "0.01"`, recorded cost 0,
and enough measured tokens on a priced model that the estimate exceeds the cap -> `_check_budget`
reports over budget with the estimated label and returns a non-zero issue count. On base it
reports nothing. Mirror for the 80% warning.

**Non-goals.** No change to the dispatch gate, to `MODEL_PRICING`, to `docket cost`'s table
layout, or to `cost --json`. No dollar-savings language anywhere.

**Goldens.** `cost.golden` must stay byte-identical (the seed has no budget breach); if it
moves, stop and return the diff instead of regenerating.

**Focused:** `uv run pytest -q tests/unit/cli/test__doctor.py tests/integration -k "cost or budget"`

---

## W36-C11 — help-text and spec sweep for what the audit left in prose

**Branch:** `w36-c11-text-sweep` · **Batch 3** (after everything; it edits docstrings in the
hottest file). Docstrings and spec prose only: **no behaviour change**. The integrator strips
docstrings from both revisions and compares `ast.dump`; any code difference rejects the branch.

**Items** (each verified false on 2026-09-19; re-verify before editing, behaviour may have
changed in batches 1–2):

| Where | False today | Truth |
| --- | --- | --- |
| `cli/__init__.py::cmd_pod` docstring | pods are "created by `docket add`" | created by `docket init`; `add <role>` extends one |
| `cli/__init__.py::cmd_init` docstring | a workdir blueprint's directory is auto-provisioned under `~/.docket/workspaces/pods/<project>/` "if omitted" | `run_init` always passes the cwd as the location; auto-provisioning happens only via `--from` without `workDir` and `POST /pods` without `path` |
| `cli/__init__.py::cmd_maintain` docstring | `sessions` "archive large/old session data"; `check` covers "fleet registration" | `sessions` reports sizes and never trims; `check` does not re-register — list what `_maintain_check` really inspects. Add C5's rebuild sentence (pod members refused, memory untouched) |
| `cli/__init__.py::cmd_scope` docstring | says it updates `SOUL.md` | it prints a hint; it does not rewrite the file |
| `cli/__init__.py::_delete_pod` docstring | "One gateway restart at the end" | there is no gateway; also bring it under the 3-line budget (it is the one `long-def-doc` finding in this file) |
| `core/agent_loop.py` "Durability" docstring | the user message is appended before any model call | the compaction summariser may call the model first |

**Specs.**
- `specs/validation/input-validation.spec.md` §2, §4, §5: mark each "Deferred — no measured
  need" with the reason (session keys are URL-quoted before becoming a path,
  `core/session.py::_session_dir`; nothing parses a session key back). Status prose stays
  `Partial` and lists only what is truly unimplemented after C1.
- `specs/functional/model-profiles.spec.md` "User registry overlay" requirements 1 and 3: amend
  to the shipped behaviour (unknown role and corrupt registry fall back silently, as
  `load_registry`'s docstring says). Do **not** add warnings — that is behaviour.
- `specs/acceptance/user-stories.md`: the MON-001/SEC-001/COM-001 remainders and the Metrics
  section describe unbuilt capabilities with no ROADMAP card; mark them "not scheduled" per
  `specs/README.md`'s prime rule, do not delete the stories.

Regenerate `docs/commands.md`. `help.golden` must stay byte-identical (`cli/_help.py` is not in
scope); if a command's `--help` is pinned by a golden, say so and stop.

**RED.** Not applicable (prose). Evidence instead: for each row, the `rg`/`--help` command that
shows the old claim and the code locator that contradicts it.

**Non-goals.** No code. No `README.md`, no `docs/*.md` guides (already aligned by 834321d).

**Focused:** `uv run python scripts/gen_cli_docs.py --check && bash scripts/validate-specs.sh && uv run python scripts/maint/comment_lint.py --check src/docket/cli/__init__.py src/docket/core/agent_loop.py`

---

## Integrator checklist

1. Per merge: confirm declared ownership (`git diff --stat <base>..<branch>` lists only owned
   paths), RED evidence, then merge in the order of §1. On a `docs/commands.md` conflict,
   regenerate.
2. Per batch, after the last merge: bump `**Version**`/`**Last Updated**` and add the changelog
   entry once per touched spec from the workers' lines; sync `specs/README.md`
   (`scripts/maint/check_spec_index.py`); add `CHANGELOG.md [Unreleased]` entries; apply README
   sentences (known limits: MCP approvals, blueprints); re-measure `CONTRIBUTING.md` counts
   (`scripts/metrics.py --check`); lower ratchet baselines if counts fell.
3. Batch gates: ruff, format, mypy, `pytest`, `pytest tests/agent`, `tests/guards`, golden 18,
   `validate-specs`, `check_spec_index`, `gen_cli_docs --check`, `metrics --check`,
   `split_board check`.
4. C6 live evidence: provision a `research` pod and an `ops` pod under a throwaway `HOME`
   against the local llama.cpp endpoint (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`), dispatch once
   each, record hop count and that the `ops` run reaches `waiting_approval`.
5. **Publication order.** C1's RED test documents a traversal in an authenticated, loopback-only
   route. Push the board and C1 together, or C1 first; do not leave the card public for long
   without its fix.
6. Close: amend `ROADMAP.md` §3's two stale rules (README "≤ 150 lines", guards "≤ 80 lines")
   and `TODO.md` usage rule 5's gate list, update the status table row, archive the section with
   `scripts/maint/split_board.py archive`, and refresh the gitignored `CLAUDE.md` (fifth
   unwired-machinery instance closed; `--debug` candidate closed).
