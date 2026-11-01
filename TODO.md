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
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> **ACTIVE: Phase 57** (D-79, [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md), accepted 2026-11-01). Before it, Phase 56 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md) decisions 13-16) closed
> 2026-10-30: an external service is declared, not programmed; a pod keeps records; one judge; one home layout; the
> four team shapes. Its section is archived and what it leaves open is under "Phase 56" in the follow-ups below.
> Decisions 15-16 of the ADR were accepted by the maintainer the same day. Phase 55
> closed 2026-10-30; Phases 52 to 54 closed 2026-10-29. The integration branch is `develop`. A new phase starts from
> a measured trigger or a maintainer request.

## How work runs on this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane takes about 5 min.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◆ PHASE 57 — what docket gives a manager in the plan of record (ACTIVE; ADR 0037 accepted 2026-11-01)

> **Trigger:** scoped request, Tack's ADR 0034 "What this asks of docket" (accepted 2026-11-01),
> six additive pulls. The decisions and the two departures from the request are in
> [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md):
> - no `/messages` route, because a turn is an escalation (ADR 0032);
> - no `placement: host`, because a lights-out pod reaches Tack through a declared service
>   (ADR 0024).
>
> The ADR was accepted by the maintainer on 2026-11-01.
>
> **Rules of the phase:**
> - The HTTP API stays `"6"`.
> - A card amends its own section of a spec, spec first.
> - The integrator owns, at merge:
>   - each spec's `Version`/`Last Updated` line;
>   - the `FEATURES` tuple in `interfaces/http/routes/health.py`. P57-3 creates it. The integrator
>     adds each other card's feature name at that card's merge; a card names its feature but does
>     not edit the tuple.
> - The report to Tack, per card: the commit, the exact field and route shapes, and the feature
>   name. The integrator writes it.
>
> **Order:**
> - Wave 1 runs four lanes that share no file:
>   - A: P57-1;
>   - B: P57-2;
>   - C: P57-3, then P57-4, then P57-5;
>   - D: P57-6.
>
>   The exception is `tasks/domain/task.py`. P57-1 and P57-2 each add one field to it, on distinct
>   lines, and the integrator merges A before B.
> - Wave 2 runs P57-7, then P57-8. They need P57-1 (`compose.py`, `record.py`) and P57-4
>   (`exchange.py`) merged first.
> - Opus plans, integrates and reviews the P57-7/P57-8 diff. It is not a worker.

### P57-1 — `current` on a running task

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0037 decision 1 (Tack ask 1).
- **Goal:** while a hop runs, its task carries
  `current: {stepId, role, member, model, startedAt, cycle}`. The field is absent, not null, at every
  other time.
- **Writing and clearing it:**
  - It is written to the record where `hop_started` is emitted (`hops/application/compose.py`
    ~564-581), with the same values, through `TaskRepository.update`.
  - It is cleared where `hop_finished` is emitted (`tasks/application/record.py`
    `persist_hop_and_trace` ~513).
  - `tasks/domain/state.py::decide` (~90-148) adds `current` to `drop` on every move out of
    `running`.
- **Non-goals:**
  - no route change: both routes already serialize through `routes/health.py::_with_token_budget`;
  - no in-memory registry;
  - no served model (that stays on `hop_finished`).
- **Spec:** `specs/api/operator-api.spec.md`, the task shape. Add the field, when it is present,
  and that `model` is the planned model.
- **Change:**
  - `tasks/domain/task.py`: a `CurrentHop` model and the field, with alias + `exclude_if` as
    `max_tokens` does (~241);
  - `state.py`;
  - `compose.py`;
  - `record.py`;
  - feature name `taskCurrent` (the integrator adds it).
- **Acceptance (RED first):**
  - `tests/unit/tasks/domain/test_state.py`: `decide` from `running` to each settle status drops
    `current`.
  - `tests/integration/interfaces/test_serve_tasks_endpoint.py`, a new test:
    - a fake chat port reads `GET /tasks/<pod>/<id>` and the list from inside the turn;
    - both carry `current` with the step, role, member, model and `cycle: 0`;
    - `current` is absent before claim and after `done`;
    - a gate that sends the step back once shows `cycle: 1` on the second hop.
  - The fixture `tests/fixtures/task-records/` loads unchanged.
- **Gate:**
  - the touched unit files and the one integration file, under `timeout 120`;
  - `tests/architecture` (3 s);
  - `tests/e2e -n auto` (42 s; the wire changes).

### P57-2 — a cursor over every task a pod holds

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0037 decision 2 (Tack ask 2).
- **The counter:** the task file `{"tasks": [...]}` gains a counter, and every task carries `rev`.
  - `tasks/application/json_store.py`'s locked `read_modify_write` (~28) compares each task's dump
    (without `rev`) before and after `fn`.
  - A changed or new task gets the next counter value, so every writer is covered at the one place.
- **The route:** `GET /tasks/<pod>?updatedSince=<n>` answers `{"tasks": [...], "next": "<n>"}`:
  - the tasks with `rev > n`, in `rev` order;
  - `next` is the highest `rev` returned, or `n` itself when nothing changed;
  - it combines with the `status` and `externalRef` filters (`routes/tasks.py::_filter_tasks` ~75);
  - a non-integer cursor answers 400, `code: bad_cursor`;
  - without `updatedSince`, the response stays byte for byte what it is today.
- **Non-goals:**
  - a timestamp cursor;
  - tombstones (ADR 0037, "Not decided");
  - migrating a task file that has no counter (no compatibility; the first write stamps the tasks
    it changes).
- **Spec:**
  - `specs/api/operator-api.spec.md`: the list route and `rev`;
  - `specs/data/serve-read-api.spec.md`: a "Task cursor" section beside the traces cursor. Say
    "latest state once", not "every event".
- **Change:**
  - `tasks/domain/task.py` (`rev`);
  - `tasks/application/json_store.py`;
  - `interfaces/http/routes/tasks.py`;
  - feature name `taskCursor` (the integrator adds it).
- **Acceptance (RED first):**
  - `tests/unit/tasks/application/test_json_store.py`:
    - an unchanged write stamps nothing;
    - two changed tasks get consecutive values.
  - `tests/integration/interfaces/test_serve_tasks_endpoint.py`:
    - one task enqueued by the routine path (`tasks/application/routines.py` ~211) and one by the
      CLI path (`interfaces/cli/commands/task.py` ~189);
    - `updatedSince=0` returns both, once, with `channel` `routine` and `cli`;
    - polling `next` returns `[]` with the same `next`;
    - moving one task's status makes only it reappear;
    - `updatedSince=abc` answers 400 `bad_cursor`.
- **Gate:** the two files, `tests/architecture`, `tests/e2e -n auto`.

### P57-3 — pod memory over HTTP, read only, and the `features` list

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** behaviour + spec

- **Trigger:** ADR 0037 decision 3 (Tack ask 3), and the probe list of the Decision preamble.
- **The memory route:** `GET /pods/<pod>/memory` answers `{"entries": [...]}`.
  - It returns `teams/memory.py::list_entries(pod, status="accepted")` (~473), mapped through
    `MemoryEntry.to_dict()` (~132).
  - It sits behind the serve token. An unknown pod answers 404.
  - The route row goes before the `/pods/<pod>` catch-all in `interfaces/http/routes/table.py`
    (~42-46), shaped like the `/corrections` row.
  - The handler is a copy of the pattern in `routes/pods.py::get_pod_corrections` (~60).
- **The `features` list:**
  - `interfaces/http/routes/health.py` gains `FEATURES: tuple[str, ...] = ("podMemory",)`;
  - `build_status` (~59-80) and `/health` (`interfaces/http/server.py` ~63-78) both answer
    `"features": list(FEATURES)`.
- **Non-goals:** pending or refused entries over HTTP; writes.
- **Spec:**
  - `specs/api/operator-api.spec.md`: the route, and `features` with its rule (a name appears in
    the commit that makes it work);
  - `specs/data/serve-read-api.spec.md`: `/status.json`.
- **Acceptance (RED first):** a new file
  `tests/integration/interfaces/test_serve_pod_memory.py`, modelled on
  `test_serve_pods_corrections.py`:
  - a pod with one accepted, one pending and one refused entry returns exactly the accepted one,
    equal to the CLI's element;
  - no token gets 401;
  - an unknown pod gets 404;
  - `/status.json` and `/health` list `podMemory`.
- **Gate:** the new file plus `tests/unit/interfaces/http/test_routing.py`,
  `tests/unit/interfaces/http/routes/test_health.py`, `tests/architecture`, `tests/e2e -n auto`.

### P57-4 — a read-scoped serve token

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0037 decision 5, HTTP half (Tack ask 5).
- **Goal:** `DOCKET_SERVE_READ_TOKEN`, read in `bootstrap.py` (~213), is a second token on
  `ServerPlan` and on `HttpExchange` (`interfaces/http/exchange.py` ~29).
  - `authorize` (`interfaces/http/auth.py` ~21) takes the method, which `server.py::_route`
    (~296-305) passes.
  - Answers by token and method:

    | Token | Method | Answer |
    | --- | --- | --- |
    | serve token | any | allowed |
    | read token | `GET`/`HEAD` | allowed |
    | read token | `POST` | 403, `code: read_scope` |
    | anything else | any | 401 |

  - A read token equal to the serve token is refused at start.
  - `_send_refusal` (`exchange.py` ~68) passes a `DocketError`'s `code` to the wire. P57-7 needs
    this.
- **Non-goals:**
  - a token file for the read token;
  - scopes beyond read and full;
  - auth on `/status.json`, `/metrics` and `/health`, which stay open.
- **Spec:**
  - `specs/api/operator-api.spec.md`: auth;
  - `docs/CONFIGURATION.md`: the variable;
  - `specs/api/cli-interface.spec.md`, if `start` documents its environment.
- **Change:** `bootstrap.py`, `interfaces/http/auth.py`, `exchange.py`, `server.py`,
  feature name `readScope` (the integrator adds it).
- **Acceptance (RED first):** `tests/integration/interfaces/test_server__bearer_auth.py`:
  - for every row of `POST_ROUTES`, the read token gets 403 `read_scope` and nothing is written
    (the task file is unchanged);
  - for every authenticated `GET` row, the read token gets what the serve token gets;
  - a wrong token gets 401.
  - `tests/unit/test_bootstrap.py`: equal tokens are refused.
- **Gate:** the two files, `tests/architecture`, `tests/e2e -n auto`.

### P57-5 — `docket start --mcp --read-only`

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

- **Trigger:** ADR 0037 decision 5, MCP half.
- **The `retry` split:** in `interfaces/cli/commands/mcp.py`, `retry_task_id` leaves `tool_queue`
  (~89) for a new write tool `retry`. The full server lists twelve tools.
- **The flag:**
  - `--read-only` (`interfaces/cli/commands/service.py::cmd_start` ~64-112) is refused without
    `--mcp`.
  - It passes `read_only=True` to `serve_stdio`/`_build_server` (~230-271), which then registers
    only `status`, `pods`, `queue`, `runs`, `inbox`, `escalations` and `cost`.
  - The stderr list and the `instructions` string (~249) follow the registered set.
- **Non-goals:** a caller check inside `resolve`.
- **Spec:**
  - `specs/api/mcp-server.spec.md`: the tool list and read-only mode;
  - `specs/api/cli-interface.spec.md`: the flag;
  - goldens and `docs/commands.md` via `scripts/gen_cli_docs.py`.
- **Acceptance (RED first):** `tests/integration/interfaces/test_mcp_server.py`:
  - `tools/list` on a read-only server returns exactly the seven names;
  - calling `resolve` is an unknown tool;
  - the full server lists twelve, and `retry` re-queues a failed task.
  - `tests/unit/kernel/test_service.py`: `--read-only` without `--mcp` is refused.
- **Gate:** the two files, `tests/architecture`, goldens (4 s), `gen_cli_docs.py --check`.

### P57-6 — a lights-out pod reaches a loopback service; a jailed MCP server does not

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** tests + spec

- **Trigger:** ADR 0037 decision 6 (Tack ask 6). Measure first, then prove the shape that fits.
- **Goal:** two tests.
  1. *The measurement.* `tests/integration/sandbox/test_mcp_jail_network.py`, skipped without
     Landlock, modelled on `tests/integration/agent/test_mcp_stdio_root.py`:
     - a stdio MCP server whose tool connects to a listener on `127.0.0.1:<free port>`;
     - `mcp_client` with `StdioLaunch(sandbox="auto", network=False, ...)` gets the tool's EPERM
       error and the listener receives nothing;
     - with `network=True` (the control) the listener receives the bytes.
  2. *The fitting shape.* `tests/integration/hops/test_lights_out_service.py`:
     - a pod that passes the lights-out profile (`hops/gates/profile.py` ~50-65: isolation on,
       network `none`, `consultMode: decide`) declares a `kind: service` with
       `baseUrl: http://127.0.0.1:<port>` and `hosts: ["127.0.0.1"]`;
     - a turn's `svc__<name>__<op>` call reaches the listener and is audited;
     - a second service on `127.0.0.2` with no `hosts` entry is refused by the perimeter
       (`platform/service_http.py::_connector` ~98-125), and the refusal is audited.
- **Non-goals:**
  - `placement: host`;
  - a per-port perimeter;
  - an in-process HTTP MCP client (ADR 0037, "Not decided").
- **Spec:**
  - `specs/functional/mcp-client.spec.md` (~40): one sentence. A stdio server shares the turn's
    network, so under network `none` it reaches no TCP address, loopback included.
  - `specs/functional/service-client.spec.md`: one sentence. A service is how a lights-out pod
    reaches a local HTTP API.
- **Gate:** the two new files, `tests/architecture`.

### P57-7 — a conversation task: the option, the `turn` escalation, how it resolves

**Status:** TODO (after P57-4) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + contract

- **Trigger:** ADR 0037 decision 4 (Tack ask 4), first half.
- **Creating one:**
  - `POST /tasks/<pod>` accepts `conversation: {maxTurns}`, validated in `tasks/domain/options.py`
    (`maxTurns`: `StrictInt`, 1-20; the constant is `MAX_CONVERSATION_TURNS`). The field joins
    `_TASK_OPTION_FIELDS` (`interfaces/http/routes/task_create.py` ~20-31).
  - It is stored on `TaskRecord` and answered as `conversation: {maxTurns, turns}`. `turns` is a
    computed field: the task's finished hops of its one step.
  - A pipeline of more than one step (`resolve_pipeline_steps`) answers 400,
    `code: conversation_needs_one_step`.
- **The `turn` escalation:**
  - `EscalationKind` (`kernel/operator_contract.py` ~255) gains `turn`, and the operator-v2 schemas
    are regenerated (`scripts/gen_operator_schemas.py`).
  - `tasks/application/escalations.py` gains `open_for_turn(task, step, answer)`:
    - the options are `reply` (content `{text: string}`) and `close`;
    - the record names its kind's `whenNobody` and an expiry that closes it.
  - In `resolve` (~538), `reply` re-queues the task as a consult does (`_receive_question` ~455).
  - `close`, and the expiry sweep (`tasks/application/escalation_sweep.py` ~39-57), move the task
    to `done`.
  - `EscalationNotPending` carries `code = "escalation_not_pending"`.
- **Non-goals:**
  - running the turn (P57-8);
  - a `/messages` route;
  - a new task status.
- **Spec:**
  - `specs/functional/operator-loop.spec.md` §11 (the kind, its options, its expiry);
  - `specs/api/operator-api.spec.md` (the create body, the wire field, the 409 code);
  - `specs/api/a2a-binding.spec.md`: one line, `message/send` resolves a `turn` like any pending
    escalation.
- **Acceptance (RED first):**
  - `tests/unit/tasks/domain/test_options.py`: `maxTurns` 0, 21 and `"3"` are refused.
  - `tests/integration/tasks/test_escalation_turn.py`:
    - a `turn` opened on a `waiting_input` task resolves with `reply` to `pending`;
    - resolving with `close` moves it to `done`;
    - an expired `turn` moves it to `done`, not `blocked`;
    - a second resolve gets `EscalationNotPending` with its code.
  - `tests/integration/interfaces/test_serve_escalation_resolve.py`: that 409 carries
    `code: escalation_not_pending`.
  - `tests/contracts/`: the regenerated schema.
- **Gate:**
  - the files;
  - `gen_operator_schemas.py --check` (or its test);
  - `tests/architecture`;
  - `tests/e2e -n auto`.

### P57-8 — a conversation task runs turn by turn

**Status:** TODO (after P57-1 and P57-7) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0037 decision 4, second half.
- **When a turn's hop succeeds** on a conversation task with `turns < maxTurns`, the executor
  (`hops/application/executor.py` ~304-433, the outcome loop ~355):
  - records the hop `parked=True`, so `replay_pipeline_position` (`tasks/application/record.py`
    ~101) re-enters the same step unchanged;
  - calls `open_for_turn` with the hop's answer;
  - ends `waiting_input`.
- **On the turn that reaches `maxTurns`** the task ends `done`.
- **The reply as the next turn's note:** `tasks/application/answers.py::consult_note` (~65) also
  renders the resolved `turn`'s `text` as the note, and `consult_note_delivered` stamps it. The
  step's history (`kernel/ids.py::step_session_key`) brings the earlier turns.
- **The token limit:** `hops/domain/gate_decisions.py::decide_task_tokens` (~277) ends a
  conversation task with at least one turn `done`, not `failed` with `budget`.
- **Non-goals:**
  - multi-step conversations;
  - a reply mid-turn;
  - changing a consult.
- **Spec:**
  - `specs/functional/pod-dispatch.spec.md`: a conversation task's outcome;
  - `specs/functional/session-history.spec.md`: one sentence, turns share the step's history.
- **Acceptance (RED first):** `tests/integration/hops/test_conversation_task.py`, with a recording
  fake chat port:
  - `maxTurns: 3`, then reply, reply;
  - the three model requests carry the earlier turns' user and assistant messages;
  - three hops, each with `usage`;
  - after turn 3 the task is `done` with no pending escalation;
  - a reply to turn 2's escalation gets 409 `escalation_not_pending`;
  - a task whose `maxTokens` runs out after turn 1 is `done`;
  - a non-conversation task's ok hop still advances (regression).
  - E2E: `tests/e2e/test_plan_of_record_over_http.py` gains one conversation over HTTP: create,
    reply via `POST /escalations/<id>`, close.
  - feature name `conversation` (the integrator adds it).
- **Gate:**
  - the new file;
  - `tests/unit/hops/application/test_executor.py`;
  - `tests/unit/tasks/application/test_record.py`;
  - `tests/architecture`;
  - `tests/e2e -n auto`.
- **Phase close (integrator):**
  - the full gate list of `CLAUDE.md`'s testing budget;
  - one real run on the live home: a three-turn conversation on `app-dev`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first two belong to the later cards
that already own the files.
- *Specs that lag.* `trace-store.spec.md` items 30-32 say every `process_*` payload carries `pgid`; MCP events carry
  none. `audit.spec.md` (~line 77) omits `pod.network_widen` / `pod.network_narrow`. P55-12 or the next card that
  edits either spec.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_consult_wait.py::TestAnsweredInPlace::test_an_option_answer_goes_back_to_the_model_in_the_same_turn`,
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Phase 55 Wave 2, P55-3.* The `outward` recipe's policy `ask` names one tool, `mcp__outbox__send`
  (`when.tool` matches an exact name), so a send tool of another name is not asked about: a kind predicate or a default
  `ask` for every `send` tool belongs with P55-4. `--kind` stays an operator assertion, not verified against the server.
  A pipeline step that runs a role from the pod's existing registry (not in the applied directory) is not checked by
  the read/act rule.
- *Phase 55 Wave 2, P55-6.* `docket task show` "Waiting on you", the foreground `run` progress view and Telegram
  `/status` do not special-case a `wait`. `serve-read-api.spec.md` (the `kind` label list) and `a2a-binding.spec.md`
  (`escalationKind`) still list five kinds. `docket_escalations_total` counts a probe-resolved wait as `by=person`. A
  `stale_claim` between wake and claim drops the wait, so the next claim parks the step again. A monitor-only `docket
  start` never runs a probe (only a dispatching sweep does). Tack's maintainer is told: `wait` is an additive
  `EscalationKind`, `machine` an additive `EscalationPolicy`, the task is `waiting_input` with a2a state `WORKING`, a
  timed-out wait with no route is `blocked` / `wait_expired`, and `POST /escalations/<id>` `{optionId: "resume"}` ends
  it early. The e2e lane took 344 s once on this host against about 42 s measured before; its slowest tests are 13 s,
  so it was host load, not a test; re-measure if it repeats.
- *Phase 55 Wave 3.*
  - P55-2: the refusal golden is not added. `tests/golden/run.sh` derives the command from the case id and
    `setup model set` validates the model id (it contains `/`) before the role; a CLI unit test in
    `tests/unit/interfaces/cli/commands/test_setup_model.py` plus checking the role first would fix both. The refusal
    hint and `setup model list` name only the ten built-in roles; `known_role_names()` reads every overlay per call.
  - P55-4: `task show --json` carries no `call` (deliberate). The `Authorization` redaction pattern needs a token of
    about 20 characters after "Bearer". `outward` and `call` are additive to `operator-v2`; tell Tack's maintainer.
  - P55-9: `docs/CONFIGURATION.md` and `kernel/layout.py` do not list `docket-routines.json`;
    `pod-blueprints.spec.md` omits `routines/` from the `pod update` list; the recipe summary line does not name
    routines; cron day-of-month and day-of-week are ANDed, as in the existing parser; `tzdata` is not a declared
    dependency; no `--tz`-aware `HH:MM` form. A routine fires only under `docket start --dispatch`.
    A routine skip is traced as `step_skipped` because `EVENT_TYPES` is closed.
- *Phase 55 Wave 4.*
  - P55-10, a gap in the flow: nothing user-facing stores a secret under an arbitrary name such as `crm` (provider add
    and notify write only their own names; `setup_notify.store_secret` is the one writer), so a `secret:crm` reference
    needs `secrets.json` or the keyring edited by hand. Recommended: a `docket setup secret set <name>` command that
    reads the value from stdin or a prompt and never echoes it; needs the maintainer's go as a card. Sessions and the
    model's own reply carry raw tool output (the model sees it); not checked. `setup --fix` (not bare `setup`) carries
    the literal-credential warning; there is no CLI golden for `--secret` (run.sh replays readonly cases only).
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas.
  - A flake, once: `test_consult_wait.py::TestAnsweredInPlace::test_an_answer_by_the_task_goes_through_the_same_record`
    failed in the full run and passed alone (the file's other test is already on the list above).
  - Phase 56 Wave 2 merge run (2026-10-30), both passed alone: `test_consult_wait.py::TestAnsweredInPlace::
    test_a_decline_tells_the_model_to_decide_itself` (a third test of that class, so the class now has three flakes
    under load: that is its trigger), and `tests/integration/product/test_runtime_execution_envelope.py`, 8 setup
    errors from `uv build` exiting 2 in a parallel worker.
- *Declarative external services (became Phase 56, closed 2026-10-30).* The maintainer wants a pod to reach
  an external service from a `kind: service` document or commands (base URL, auth from the secret store, operations as
  read/send tools through `dispatch_tool`), with no program written per service and no more MCP implementation work. It
  reverses ADR 0036's "no native HTTP tool": written as decision 13 in the amendment of
  [ADR 0036](docs/adr/0036-a-pod-works-outward.md) (proposed 2026-10-30, not accepted; no new ADR). Sketch and open
  questions in `internal-docs/design/site-credentials-for-a-pod.md` (Addendum). Scope accepted 2026-10-30: Phase 56.
- *To investigate, important: a pod logging in to a site nobody configured.* Per-service MCP bridges and `secret:<name>`
  are fixed when a server is registered; a task that ends in a `send` at a new site that needs a login has no per-site
  credential the model never sees. Raised by the maintainer 2026-10-30. Analysis, seven open questions and a suggested
  path (ADR first, then `docket setup secret set`, then a per-site grant like the network grant, then a real run with a
  throwaway account) are in `internal-docs/design/site-credentials-for-a-pod.md`. No card yet.
- *Phase 56 close (the real run and the gates, 2026-10-30).*
  - Real evidence: `tests/live/test_hacker_news_live.py` (`DOCKET_RUN_LIVE_HN=1`) ran the `hacker-news` recipe against
    `hn.algolia.com` and the local model; the fourth run passed (see P56-22 in the archive). The write path of a declared
    service (park, approve, one `POST`) against a real model was **not** repeated at this close; the deterministic e2e
    (`tests/e2e/test_declared_service.py`, a scripted model) covers it. A run with the real model is the trigger for
    the first service that sends.
  - The role prompt's "end your reply with `## Memory`" line made a local model run `echo` through `bash`, and the
    gate parked the task for an approval nobody was there to give. The `hacker-news` steps say to run no command; the
    prompt in `builtin_roles.py` is unchanged (trigger: a second pod where a model does the same).
  - P56-10 left: a producer of git evidence for a non-implementer role. The `operate` and `routine` pods are workdir
    pods with no commits, so nothing would read it (trigger: a git-backed pod whose non-implementer step commits what
    a later step needs).
  - Tack's runner sends `"blueprint": "software"` in `POST /pods` and must send `build`.
  - `summarize_recipe` does not count a recipe's `services/`; `gen_recipe_docs._brings` and
    `pod_config_library._brings` are two near-duplicates. The `captured` column of `stories` holds the day a story
    was posted (the model has no clock); the row's `_at` is the capture time.
  - Prose still behind the code: the MCP client text ("workdir blueprint such as research"),
    `README.md` line 11 ("research, content or outward work"), `builtin_roles.py:68` ("forward-compat"), and
    `config-format.spec.md` (~line 115, `load_pipeline(text)`); `_blueprint_pipeline` loads a registry only to call
    `load_pipeline(None, ...)`; `conversations.load` returns an empty registry for an invalid file.
  - Records port (P56-23, merged): a second backend is one adapter module, one line in
    `bootstrap._open_records` and one `BACKENDS` entry in the conformance suite; a remote one needs the ADR
    amendment on `send` first, and S3 is an export destination, not a backend. `teams/records.py` quotes a set name
    in ANSI double quotes (each backend would quote its own); `ReadLimits` serves `read` and `export` though
    `export` honours only `timeout_s` (a possible `ExportLimits`).
  - Live Hacker News on Anthropic: the recipe ran on `claude-haiku-5-5` with Langfuse export (digest 218.9k tokens,
    weekly report 111.1k) and `tests/live` now takes `DOCKET_LIVE_HN_PROVIDER=anthropic`, but that lane was not run
    with a real key (setup only checked with a fake one). A fake key makes the run wait out its timeout instead of
    failing on the 401 at once.
  - Records and services: `pod update` does not check that a `rec__<set>` allow-list entry names a declared set;
    real PostgREST documents carry no `operationId`; `setup service list` shows secret names; the `ask-before-send` custom message is not shown
    for service sends; service results are not screened as untrusted; `pod records --csv` overwrites silently; the
    idempotency key also hashes path and query arguments; `pod-blueprints.spec.md` should list `services/`.
  - Code: `setup_model_credentials._write_credential` duplicates store logic; `config_docs.py` imports itself;
    `_read_until_deadline` is duplicated; `decided_approval` sits in `escalations.py`.
  - Flakes under load, each passes alone: the `test_consult_wait` decline test and the `uv build` in
    `test_runtime_execution_envelope`.
- *Phase 55 close (the repeated real run, 2026-10-30).* `docket run` does not wake a `wait` whose time has passed
  ("No pending tasks"); only the dispatch service's sweep does, as the spec says; a person expecting `run` to finish
  it is surprised (trigger: a second report). In one fresh home `setup provider add local ...` left the roles on
  `anthropic/*` until `setup model preset local` ran; an earlier fresh home applied the preset by itself: reproduce
  before a card. A stdio MCP server under isolation needs its script, interpreter and venv readable, and fails with
  `mcp_client.unavailable: ExceptionGroup` while python's "Permission denied" goes only to stderr (trigger: the next
  operator who meets it). P55-14 keys its note by task and role, not step, and splits the approval's `action` on
  `; call=` rather than reading a typed field; `task show --json` carries no `approval_unused`. P55-13 adds no trace
  line when the surface drops a role-named built-in (the closed event set has none that fits).
- *Live evidence, P55-5 (2026-10-30).* A real Playwright MCP server (0.0.83, headless system Chrome) driven through
  docket's MCP layer against a local page: under `lifetime: hop` navigate, snapshot and click by ref keep one session
  (the click ran, the page title changed); under `call` the snapshot after a navigate is `about:blank` and no ref
  exists. Not a model-driven pod run. That server's click argument is `target`, not `ref`.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **A per-pod `fetch` allowlist** (`kernel/home.py:278`, one list for the machine). Trigger: two pods
  on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`: a subject is a
  repository path; a workdir pod's "the client prefers a formal tone" has no home). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

**Standard teams and records (deferred from Phase 56, 2026-10-30; analysis in
`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8 and
`capa-de-datos-para-docket-2026-10-30.es.md`).**

- **A pod without a Lead member.** Not a blocker, so not a card: the Lead is the pod's *anchor record*
  (its workspace holds the queue, `teams/settings.py:21-26`, the settings and budget, `:29`,
  `teams/member_workspace.py:214`; `pre_input` is evaluated and session events traced as `"lead"`,
  `tasks/application/queue.py:72`, `governance/approval.py:73`), but no pipeline step has to use it: the
  `outward` recipe's pipeline already runs researcher, writer, critic, actor. Making the pod the subject is
  a persisted-state change (the queue's and settings' location). Trigger: a measured cost of the idle Lead
  member (its workspace, its row in `status`), or a pod whose operator refuses a Lead at all.
- **Measuring the three-role full pod against the four-role one** (P56-15 ships the change on the
  maintainer's request; this is the evidence it did not wait for). Trigger: a maintainer go, since the
  comparison spends hosted-model tokens on `app-dev`: the same tasks under both rosters, measured tokens
  and escaped defects.
- **A port for docket's task store** (`TaskRepository` takes the concrete `JsonTaskStore`,
  `tasks/application/repository.py:48`). Not business data, and a port with one implementation is the
  "unwired machinery" this project refuses. Trigger: a queue the one file cannot carry (measured).

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `app-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P53-4 (which absorbed P52-5) acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.
- **`scripts/render-doc-assets.py:275` prints a made-up approval token** (`token=apr-...`) and the
  `waiting_approval` line, shapes Phase 51 removed. Trigger: the maintainer re-captures the README
  assets (a classifier-refused step); then render the escalation id and `waiting_input`.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **A tool deny per team member** (a read-only researcher): `tool_profile` is prose, the only denial is
  the pod-wide `deniedTools`. Trigger: a recipe or pod that needs one member without write tools.
- **Delete the old-layout reader** (`kernel/layout.py::is_legacy` and the legacy branches of `Home`).
  Trigger: the next minor release. First move what still seeds or reads an old-layout home:
  `tests/support/home.py` and `pods.py`, and the old paths named in `scripts/gen_cli_docs.py`,
  `scripts/render-doc-assets.py` and `docs/commands.md`.
- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P52-12, a wait on a machine is an escalation.** Absorbed by P55-6 (ADR 0036 decision 5): a `wait` step is
  an escalation of kind `wait` the sweep settles on time or on a probe; the wait on a machine is one case of it.
- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts. `smoke_workflow.py` calls an interpreter running a script (`PYTHONPATH=src python3
  x.py`) opaque on purpose: it can read any file, so the private-path check fails closed; `VAR=x` alone is parsed.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
