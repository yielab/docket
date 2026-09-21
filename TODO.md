# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> ## ◉ ACTIVE BOARD — WAVE 36 (2026-09-19): eleven defects the documentation audit found in code
>
> **Wave 36 is the active section below.** The 2026-09-19 documentation audit (`5fb2b42`,
> `834321d`) aligned every doc and spec with `v0.2.0-beta.3` and left the places where the *code*
> was the wrong side for a second pass. That pass re-verified each one by running it and found
> three more. Eleven one-worker cards in three batches scheduled by file contention; worker start
> packets are in [.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md).
> `ROADMAP.md`, this file, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md` counts, `specs/README.md`
> and every spec's version header and changelog stay integrator-owned.
>
> **`v0.2.0-beta.3` was published on 2026-09-18** from `release.yml`; cutting the next beta stays
> a maintainer action, not a card. Every numbered phase 0–25 is complete. Waves 33 to 35 and
> Wave 29 are archived in [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).
> Wiring or retiring `docket gates enable/disable` remains an open maintainer decision recorded in
> `specs/functional/security-gates.spec.md`; it is not in this wave.
>
> **Measured, not scheduled:**
> `tests/integration/test_agent_loop.py::TestCooperativeRunCancellation::test_cancellation_after_concurrent_approval_grant_never_runs_handler`
> failed once in three full-suite runs under the load of seven concurrent suites and passed
> twenty of twenty in isolation; it waits on three 5-second deadlines. Same shape as W34-C5. A new
> wave starts from bounded triage, not from this note. Also measured by the Wave 36 triage and
> **not** scheduled, for want of a measured need: an entry point that runs a turn for an org
> specialist (Portfolio Manager, manager); registering a verify command's pid so `runs cancel`
> can interrupt it; a role-aware `maintain rebuild` for pod members.
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · the card's own spec updated with a version bump +
   changelog entry, **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---


## ◉ WAVE 36 ACTIVE (2026-09-19) — eleven defects the documentation audit found in code

**Measured at `834321d` (all gates green, main pushed).** The documentation audit fixed every
place where prose was wrong and listed thirteen where spec and code disagreed. Each was then
re-verified against the live path, most by running it under a throwaway `DOCKET_HOME`. Two
turned out not to be defects (`tack` is an audit label on the HTTP transport, not a fifth
channel; `/status.json` already emits numeric budgets). Three new ones surfaced: `provision_pod`
builds workspace paths from an unvalidated project string (reproduced through the function
`POST /pods` calls), `docket mcp servers add` rejects its own help example because Click eats the
`--` separator before `cmd_mcp` sees it (reproduced), and `POST /approvals/<token>` lets the HTTP
caller name any channel, including a grant tagged `timeout`.

**Worker packets.** Locators, allowed and forbidden paths, RED tests, focused gates and the
return format for every card are in
[.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md). A worker
loads its card with `card_packet.py W36-C<N>`, reads that file's §0 and its own packet, and
nothing else.

**Rules for every card.** Spec requirement text first, then a RED test seen failing on the base
for the stated reason, then the smallest change. Workers never edit `TODO.md`, `ROADMAP.md`,
`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `specs/README.md`, or any spec's version header
and changelog section: they return the line and the integrator applies it once per batch. That
is what lets three cards share `pod-dispatch.spec.md`. `scripts/metrics.py --check` is expected
to fail on a branch that adds tests; every other gate must pass.

**Contention and batches.** A batch starts when the previous one is merged and green.

| Batch | Cards | Merge order | Why this batch |
| --- | --- | --- | --- |
| 1 | C1, C2, C4, C5, C6, C7 | C1, C2, C4, C5, C7, C6 | disjoint functions; C6 last because it changes behaviour |
| 2 | C3, C8, C9, C10 | C3, C8, C9, C10 | C3 shares `serve.py` and `serve-read-api.spec.md` with C1; C8 and C9 share `cli/__init__.py` with C2 |
| 3 | C11 | — | docstrings in the hottest file; must describe what batches 1 and 2 shipped |

Hot files are owned at function level (full table in the packets file): `serve.py`
(C1 every project-taking handler, C3 `_handle_post_approvals`), `cli/_mcp.py` (C2 `_servers_*`,
C4 `tool_approvals_*`), `cli/_agents.py` (C1 declarative path, C5 `_maintain_rebuild`, C8 info
JSON), `cli/__init__.py` (C2 `cmd_mcp`, C8 list JSON and `cmd_snapshot`, C9 root callback and
models footer, C11 five docstrings).

**Publication order.** C1's RED test documents a traversal in a Bearer-authenticated,
loopback-only route. The integrator pushes this board together with C1, or C1 first.

### W36-C1 — validate project ids at the core provisioning boundary

**Status:** DONE (2026-09-21, merged a46782c) · **Size:** M · **Owner:** one worker · **Batch:** 1

**Trigger (deterministic reproduction):** `core/pod_provisioning.py::provision_pod("../../x",
"software", location=<dir>)` under a throwaway home succeeds and creates `x/`, `x-lead/` and
`x-implementer/` at the `DOCKET_HOME` root, outside `workspaces/`. `serve.py::_handle_post_pods`
checks only that `project` is a non-empty string; only `cli/_agents.py::run_init` slugifies.
`input-validation.spec.md` §1 has had no implementing function (spec Status: Partial).

**Goal:** one `validate_project_id` in `core/provisioning.py`, enforced as the first statement of
`provision_pod`, mapped to `400` by every `serve.py` handler that takes a project, and to exit 1
by the declarative `docket init --from` path.

**Non-goals:** reserved-word list, `location` path validation (§2), changing `slugify`,
migrating existing pods.

**Owns:** `core/provisioning.py`, `core/pod_provisioning.py::provision_pod`, `serve.py`
(`_handle_post_pods`, `_handle_post_tasks`, `_handle_post_dispatch`, the `/tasks/` and `/traces/`
`do_GET` branches), `cli/_agents.py::_cmd_add_declarative` and `_provision_pod_from_spec`,
`input-validation.spec.md` §1, `serve-read-api.spec.md` (`POST /pods` and project-segment errors).

**Acceptance / oracle:** `POST /pods {"project": "../../escaped", ...}` with a valid Bearer
returns `400`; the filesystem is the oracle — no path containing `escaped` exists under the
test's temp root and `fleet.json` has no such agent. Every id `slugify` can emit still
provisions. A declarative spec with a bad `id` exits 1 and provisions nothing.

**RED:** the `POST /pods` test returns `201` and creates the directories on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_serve_pods_endpoint.py tests/unit/test_serve.py`, then the worker gates.

### W36-C2 — make `docket mcp servers add` reachable from the real CLI

**Status:** DONE (2026-09-21, merged c68dcbd) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (deterministic reproduction):** `docket mcp servers add playwright -- npx -y
@playwright/mcp@latest` — the help text's own example — exits 1 with "Missing '--' separator".
Click consumes the `--` before `cli/__init__.py::cmd_mcp` reads `ctx.args`.
`tests/integration/test_mcp_servers_cli.py` calls `_mcp.run_mcp` with `--` already in the list,
so no test crosses the seam. No external MCP server can be configured from the CLI today.

**Goal:** the separator reaches `cli/_mcp.py::_servers_add` through the real entry point; flags
after `--` belong to the server command verbatim.

**Non-goals:** `mcp serve`, the stored schema, `__main__.py`.

**Owns:** `cli/__init__.py::cmd_mcp`, `cli/_mcp.py` (`run_mcp`, `_servers_*`),
`tests/integration/test_mcp_servers_cli.py`, `mcp-client.spec.md` requirement 21 (which
contradicts itself and is rewritten).

**Acceptance / oracle:** a subprocess `python -m docket mcp servers add …` with an isolated
home exits 0 and `load_mcp_servers()` holds `["npx", "-y", "@playwright/mcp@latest"]`; `--env`
before `--` is parsed, after `--` is stored verbatim; a missing separator and an empty command
still exit 1. Every existing `run_mcp` test passes unchanged; `help.golden` is byte-identical.

**RED:** the subprocess test exits 1 on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_mcp_servers_cli.py`, then the worker gates.

### W36-C3 — HTTP may not forge an approval's channel

**Status:** DONE (2026-09-21, merged 9ffbf95) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `serve.py::_handle_post_approvals` accepts any `channel` in
`core/approval.py::APPROVAL_CHANNELS`, so a Bearer holder can record a decision in the
hash-chained audit log as `cli`, `telegram` or `mcp`, or a **grant** as `timeout` — which
`serve-read-api.spec.md` says only ever pairs with `denied`.

**Goal:** the HTTP transport may claim only `http` (default) or `tack`; anything else is `400`
before any approval state changes.

**Non-goals:** changing `APPROVAL_CHANNELS`, auth, or any other channel's path.

**Owns:** `serve.py::_handle_post_approvals`, `tests/unit/test_serve.py` channel tests,
`serve-read-api.spec.md` `POST /approvals/<token>` text.

**Acceptance / oracle:** `{"action": "grant", "channel": "timeout"}` and `"cli"` return `400`,
`approval_get(token)["state"]` is still `pending`, and no `approval.*` audit entry was written;
`"tack"` and the default still work.

**RED:** the `timeout` grant returns `200` and writes `channel=timeout` on the base.

**Focused validation:** `uv run pytest -q tests/unit/test_serve.py tests/unit/core/test_approval.py`, then the worker gates.

### W36-C4 — an MCP grant or deny resolves the dispatch task it gated

**Status:** DONE (2026-09-21, merged 7de7219) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (read on the live path):** `cli/_mcp.py::tool_approvals_grant` and `_deny` never call
`core/dispatch.py::resolve_waiting_approval`; the CLI, HTTP and Telegram paths all do. A
`waiting_approval` task decided over MCP stays there forever. Contradicts
`security-gates.spec.md` requirement 2 and the docstrings' own "Identical to `docket approve`".

**Goal:** mirror `cli/_approve.py` and `cli/_deny.py` exactly, including the `ApprovalNoop` branch.

**Non-goals:** `core/dispatch.py`, the `_servers_*` half of `cli/_mcp.py`.

**Owns:** `cli/_mcp.py::tool_approvals_grant`, `tool_approvals_deny`;
`tests/integration/test_mcp_server.py`; `pod-dispatch.spec.md` approval requirement 4;
`mcp-server.spec.md` approvals tool text.

**Acceptance / oracle:** from a `waiting_approval` fixture, `tool_approvals_grant(token)` leaves
the task `pending` with the gate override recorded; `tool_approvals_deny(token)` leaves it
`failed` with `failureKind == "approval_denied"`.

**RED:** both tasks stay `waiting_approval` on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_mcp_server.py`, then the worker gates.

### W36-C5 — `maintain rebuild` never deletes memory and refuses a pod member

**Status:** DONE (2026-09-21, merged e434d57) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (read on the live path):** `cli/_agents.py::_maintain_rebuild` backs up five top-level
files, regenerates through the legacy flat-agent `_create_workspace`, then unlinks every
`memory/*.md` with no distillation and no copy — against the rule `clean` and `reset` enforce.
For a pod member it also replaces the role prompt with the generic template, writes a
`TOOLS.md` a Lead must not have, and resets `HEARTBEAT.md`.

**Goal:** rebuild never touches `memory/`; a pod member (meta carries `pod`) is refused with
exit 1 before the prompt and before any write; the function returns its exit code.

**Non-goals:** a role-aware re-render for pod members (follow-up), `clean`/`reset`.

**Owns:** `cli/_agents.py::_maintain_rebuild` and the rebuild branch of `run_maintain`; a
maintain integration test; `agent-lifecycle.spec.md` rebuild section.

**Acceptance / oracle:** a flat agent's `memory/2026-01-01.md` has identical bytes after a
confirmed rebuild; a pod member's rebuild exits 1 with `SOUL.md` bytes unchanged and no
`.backup-*` directory created.

**RED:** the log file is gone and the pod member's rebuild returns 0 on the base.

**Focused validation:** `uv run pytest -q tests/integration -k maintain`, then the worker gates.

### W36-C6 — dispatch runs the pod's blueprint pipeline

**Status:** DONE (2026-09-21, merged f26376d + e1bc9c2) · **Size:** M · **Owner:** one worker · **Batch:** 1

**Trigger (fifth unwired-machinery instance):** `core/dispatch.py::effective_pipeline(project,
None)` always returns `core/pipeline.py::default_pipeline()`. Nothing on the dispatch path reads
the `blueprint` meta that provisioning records, so a `research`, `content` or `ops` pod runs
only its Lead while `docket init --help` promises "Critic gates the final step". No command
exports a blueprint pipeline for `--file`, so there is no workaround.

**Goal:** with no caller-supplied spec, start from the Lead's blueprint `default_pipeline`
(`core/blueprints.py::get_blueprint`), falling back to the built-in default when the key is
absent or unknown, then apply the existing rework-budget patch.

**Non-goals:** new flags, a pipeline export command, `--file` precedence, gate semantics,
`core/orchestrator.py`.

**Owns:** `core/dispatch.py::effective_pipeline`, `core/blueprints.py` module docstring, the
unit tests for both, one assertion in `tests/integration/test_pipeline_cli.py`,
`pod-blueprints.spec.md` (delete the known-gap text), `pod-dispatch.spec.md` "Pipeline order and
participation".

**Acceptance / oracle:** a `research` pod resolves to `lead, researcher, analyst, writer,
critic`; a `software` pod and a pod with no or an unknown `blueprint` resolve exactly as before;
the pod's `maxReworkCycles` reaches the Critic's rework edge; `docket pipeline plan` on a
research pod lists no step as "skipped — role not in pod".

**RED:** the research pod resolves to `lead, implementer, reviewer, tester` on the base.

**Behaviour change:** non-`software` pods run more hops and spend more tokens. The worker
returns the `CHANGELOG` line; the integrator records one live `research` and one live `ops`
dispatch against the local endpoint before closing the wave.

**Focused validation:** `uv run pytest -q tests/unit/core/test_dispatch.py tests/unit/core/test_blueprints.py tests/integration/test_pipeline_cli.py`, then the worker gates.

### W36-C7 — a timed-out verify command leaves no orphan

**Status:** DONE (2026-09-21, merged e39ef34) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (measured):** `edges/adapters/system.py::run_verify_cmd("sleep 6 & wait", ".",
timeout=1)` returns at 1.0 s and the `sleep` is still alive afterwards: `subprocess.run(shell=True,
timeout=…)` kills only the shell. `pod-dispatch.spec.md` Cancellation requirement 2 claims the
command runs in its own session and that cancelling kills its group; neither is true.

**Goal:** run the verify command in its own session and kill the whole group on timeout, with
the return value, truncation and refusal path byte-identical. Narrow the spec to what ships.

**Non-goals:** registering the pid, `on_spawn` plumbing, `docket runs cancel`.

**Owns:** `edges/adapters/system.py::run_verify_cmd`, the verify-gate integration tests,
`pod-dispatch.spec.md` Cancellation requirement 2.

**Acceptance / oracle:** a verify command that backgrounds a child writing its pid to a temp
file, run with `timeout=1`: within 2 s of return `os.kill(pid, 0)` raises `ProcessLookupError`.

**RED:** the child is alive on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_verify_gate.py tests/integration/test_retries_and_timeouts.py tests/guards/test_no_subprocess_in_core.py`, then the worker gates.

### W36-C8 — CLI `--json` emits the types its spec and `/status.json` already use

**Status:** DONE (2026-09-21, merged e8745bc) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `list --json` and `info --json` emit `budgetUsd` as the
stored string; `snapshot` emits `lastActivity: "—"`. `cli-json-shapes.spec.md`, `/status.json`
and `cost --json` all use `number | null` and `"never"`.

**Goal:** one pure helper for "stored budget to `float | None`"; the two CLI emitters use it;
`snapshot` emits `"never"`. Storage and human tables are unchanged.

**Non-goals:** storage migration, new keys, `/status.json`.

**Owns:** the `list --json` builder and `cmd_snapshot` in `cli/__init__.py`, the `info --json`
builder in `cli/_agents.py`, `cli-json-shapes.spec.md`, one sentence in `docket-meta.spec.md`.

**Acceptance / oracle:** parsed output has a numeric or null `budgetUsd` for an agent with and
without a budget; an agent with no logs has `lastActivity == "never"`.

**Goldens that change, with the reason stated line by line:** `list_--json.golden`,
`info_myshop_--json.golden` — the old output contradicted the spec.

**Focused validation:** `uv run pytest -q tests/integration/test_edit_snapshot.py`, the golden suite, then the worker gates.

### W36-C9 — retire two claims nothing backs: `--debug` and the PRICE override

**Status:** DONE (2026-09-21, merged 9517c5f) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `--debug` sets `os.environ["DEBUG"]` and `rg DEBUG src/`
finds no reader, while `cli/_help.py` calls it "Verbose mode". The `docket models` footer says
prices can be overridden in `docket-models.json`; `models_policy.load_registry` reads no pricing key.

**Goal:** `--debug` stays accepted as a hidden no-op that writes nothing, and leaves the help
and the generated environment table; the models footer loses the override clause.

**Non-goals:** building a verbose mode or a pricing overlay.

**Owns:** the root callback and the models footer in `cli/__init__.py`, `cli/_help.py`, the
`DEBUG` rows in `scripts/gen_cli_docs.py`, `cli-interface.spec.md` Global options.

**Acceptance / oracle:** invoking the root callback with `--debug` exits 0 and leaves
`os.environ` without `DEBUG`; `docs/commands.md` regenerated.

**Goldens that change:** `help.golden` (one line), `models.golden` (footer) — both strings were false.

**Focused validation:** `uv run pytest -q tests/unit/cli`, the golden suite, `gen_cli_docs --check`, then the worker gates.

### W36-C10 — budget warnings read the same estimate the dispatch gate does

**Status:** DONE (2026-09-21, merged 37301e9) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `cli/_doctor.py::_check_budget` and the cost-threshold
warning in `cli/_cost.py` compare the budget with **recorded** cost, which `DocketDriver` always
reports as `0.0`, so they can never fire. The dispatch gate uses
`core/dispatch.py::pod_gating_cost`, which falls back to a labelled estimate.

**Goal:** both warnings use the gating figure and print it with the existing
`~$… (estimated — no cost recorded)` label. An estimate is never printed as spend.

**Non-goals:** the dispatch gate, `MODEL_PRICING`, the `docket cost` table, `cost --json`.

**Owns:** `cli/_doctor.py::_check_budget` and its caller, the cost-threshold warning in
`cli/_cost.py`, `tests/unit/cli/test__doctor.py`, `cost-tracking.spec.md` Enforcement requirement 5.

**Acceptance / oracle:** an agent with a `0.01` cap, zero recorded cost and measured tokens whose
estimate exceeds the cap is reported over budget with the estimated label and a non-zero issue
count; `cost.golden` is byte-identical.

**RED:** `_check_budget` reports nothing on the base.

**Focused validation:** `uv run pytest -q tests/unit/cli/test__doctor.py`, then the worker gates.

### W36-C11 — help-text and spec sweep for what the audit left in prose

**Status:** READY (batches 1 and 2 merged 2026-09-21) · **Size:** S · **Owner:** one worker · **Batch:** 3

**Trigger (verified 2026-09-19):** five docstrings and three spec passages still state things
the code does not do: `cmd_pod` ("created by `docket add`"), `cmd_init` (workdir auto-provision
"if omitted"), `cmd_maintain` (`sessions` "archive", `check` "fleet registration"), `cmd_scope`
(updates `SOUL.md`), `_delete_pod` (gateway restart), `core/agent_loop.py` "Durability";
`input-validation.spec.md` §2/§4/§5, `model-profiles.spec.md` overlay requirements 1 and 3,
and the unscheduled remainders in `user-stories.md`.

**Goal:** prose matches the code as it stands after batches 1 and 2. Docstrings and spec text
only.

**Non-goals:** any code change, `README.md`, the `docs/` guides.

**Owns:** the five docstrings in `cli/__init__.py`, one in `core/agent_loop.py`, the three spec
passages, regenerated `docs/commands.md`.

**Acceptance / oracle:** the integrator's docstring-stripped `ast.dump` comparison reports
`SAME`; `help.golden` byte-identical; `comment_lint.py --check src/docket/cli/__init__.py`
reports zero `long-def-doc`.

**Focused validation:** `gen_cli_docs.py --check`, `validate-specs.sh`, `comment_lint.py --check` on both files, then the worker gates.
