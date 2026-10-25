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
> **Active: Phase 51** (D-72, [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md)),
> opened 2026-10-25 at the maintainer's request. Phase 50 closed the same day (D-71). The
> integration branch is `plan/phase-46-structure` until the maintainer merges it.
> **Planned: Phase 52** (D-73, [ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md)),
> cut by file ownership; its Wave A shares no file with Phase 51's open cards.

## ▶ PHASE 51 ACTIVE — one escalation: ask, resolve, decide (D-72, ADR 0032)

> Opened 2026-10-25 by the maintainer. The reasoning and the measurements are in
> [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md). P51-1 and P51-2 are ready;
> P51-3..P51-6 follow in wave order; P51-7 (A2A facade) and P51-8 (per-task level) were approved by
> the maintainer on 2026-10-25 and follow P51-5/P51-6; P51-9 (retire the old shapes) follows P51-8.

### How a Phase 51 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR) with `Last Updated` and the
  `specs/README.md` row in the same commit.
- Names below are binding. `Escalation` is the concept (ADR 0032, decided; do not invent a
  second name). `Decision` is taken by `kernel/gate.py`.
- Wire vocabulary is A2A/MCP where one exists: `accept|decline|cancel`, `requestedSchema`,
  `INPUT_REQUIRED`. `optionId` travels in `content` until P51-5 lifts it.
- Docket-owned JSON goes through `platform/store.py`. The trace stays append-only JSONL.
- No CLI command string inside a contract model. Each surface prints its own.
- Every card: focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files, and the e2e
  lane (`uv run pytest tests/e2e -n auto`). Contract cards also run
  `scripts/gen_operator_schemas.py --check`.
- Read bounded: `python3 .agents/skills/docket-roadmap/scripts/card_packet.py P51-<n>`, ADR 0032, the
  owning specs the card names. A worktree has no `internal-docs/`.
- Workers in `.claude/worktrees/p51-<n>`, Sonnet, one card per worktree. Delta-only handoff with
  the end-of-work control summary.

**Waves (by file contention)**

| Wave | Cards | Why this order |
| --- | --- | --- |
| A | P51-1 ∥ P51-2 | P51-1 touches `consult.py`/`profile.py`; P51-2 adds the store and projections |
| B | P51-3 ∥ P51-4 | both read the record P51-2 wrote; P51-3 owns `observability/`, P51-4 owns `interfaces/` |
| C | P51-5 | the verb; needs the view (P51-4) and events (P51-3) |
| D | P51-6 ∥ P51-7 | continuation-on-claim owns `hops/`; the A2A facade owns `interfaces/http/` |
| E | P51-8 | the level table; needs P51-6 (policy applied at creation and on claim) |
| F | P51-9 | retirement; follows P51-8, no external trigger |

### P51-1 — a consult the pod decides alone (`consultMode: decide`)

**Status:** DONE (merged 2026-10-25, 939f2af4) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger (measured 2026-10-25):** after Phase A, `basic` live eval 0/3: the Lead consults
  "Where should the Implementer create smoke-artifact.txt?" with the right recommendation and the
  task parks. A Reviewer (read-only) consulted "Should I run the unit tests now?". Text alone does
  not stop it (the maintainer's tool-contract audit of 2026-10-25). Under `lights-out`
  nothing forbids a consult, so an "L5" pod still waits for a person.
- **Goal:** a pod setting makes a recommended consult resolve in the turn, audited; `lights-out`
  requires it.
- **Non-goals:** the escalation record (P51-2); a `role` dimension; consults without a
  recommendation (the schema already requires one).
- **Spec:** `operator-loop.spec.md` "Consult" items 5–6 (+ item 7 "Decide"); `security-gates.spec.md`
  "Profiles" (new lights-out requirement). `config-format.spec.md` pod settings table.
- **Change:**
  - `teams/pod_settings.py`: `consult_mode: Literal["park","decide"] = "park"`, alias
    `consultMode`, settable by `docket pod set consultMode decide`.
  - `agent/tools/registry.py::ToolContext`: `consult_mode: str = "park"`; `hops/application/driver.py`
    fills it from the pod settings (same place `max_consultations` is read).
  - `tasks/application/consult.py::run`: when `ctx.consult_park and ctx.consult_mode == "decide"`:
    trace `question_asked` with `mode: "decided"` and `decidedOptionId`; audit
    `consult.decided` (`project task role questionId optionId`, never the message); return
    `ConsultOutcome(True, content=DECIDED.format(option_id, label))` with
    `DECIDED = "no operator on duty; your recommendation stands: option {id} ({label}). Continue."`.
    Budget still decrements.
  - `hops/application/builtin_tools.py::consult_description(remaining, parks, decides)`: the
    effect sentence is derived: parks → today's text; decides → "Asking returns at once with your
    recommendation applied; prefer deciding in your reply without the tool."
  - `hops/gates/profile.py::lights_out_violations`: `Facts.consult_mode`; violation
    `("consult", "a consultation would wait for a person", "docket pod set consultMode decide")`.
  - `hops/application/compose.py`: nothing; the reply text is the tool result.
- **Acceptance:**
  - e2e `tests/e2e/test_consult_decided.py`: pod `consultMode decide`, FakeModel Implementer calls
    `consult` then writes the fix → statuses `pending, running?, done` with no `waiting_input`;
    the Implementer's second request carries the `DECIDED` text as the tool result; trace has
    `question_asked` with `mode == "decided"`; audit has `consult.decided`; `inbox` is empty;
    `assert_audit_covers_tool_calls`.
  - e2e: same pod with `park` still parks (existing `test_a_question_from_the_model_waits_for_an_answer`
    unchanged).
  - integration `tests/integration/hops/gates/test_profile.py`: lights-out facts with
    `consult_mode="park"` → the new violation; `"decide"` → none; `docket setup --fix` prints it.
  - unit `tests/unit/hops/application/test_builtin_tools.py`: the three description variants.
  - Manual (not CI): `scripts/maint/live_eval.py` on `basic` and `memory-maintenance`, local
    endpoint, `-n 3`, compared with the 2026-10-25 after-A evals kept by the maintainer.
- **Contention:** `consult.py`, `builtin_tools.py`, `profile.py`, `pod_settings.py`. Not P51-2's
  files.

### P51-2 — the escalation record behind the store

**Status:** DONE (merged 2026-10-25, 87a59c90) · **Size:** L · **Model:** Sonnet · **Kind:** refactor + spec

- **Trigger (measured):** the task carries seven fields that all mean "what the outside told this
  task" (`tasks/domain/task.py:236-260`: `approvalToken`, `question`, `consultAnswer`, `answers`,
  `pregrants`, `taskGrants`, `gateOverridePipelineIndex`). The inbox is a scan of every task of
  every pod plus every approval (`operator/inbox.py::build_inbox`) with 7 callers, polled by Tack
  every 2 s per attempt. The inbox JSON lost a consult's options on 2026-10-18 (Tack fixture
  `inbox-waiting-input-options.json`) and nothing pins the route.
- **Goal:** one durable record per escalation, written by the store, created wherever a pause is
  created today; the task lists ids; the old fields are projections of the record.
- **Non-goals:** new routes or renders (P51-4); events (P51-3); changing how a resolution is
  applied (P51-6). Nothing outside the process changes shape in this card.
- **Spec:** `docket-store.spec.md` (new file family), `operator-loop.spec.md` new area
  "Escalations" (record fields, states, `seq`), `pod-dispatch.spec.md` (parked hop names the
  escalation id).
- **Change:**
  - `kernel/operator_contract.py`: `EscalationKind = Literal["approval","consult","input","gate",
    "check_changed"]`; `Escalation(BaseModel)` with `id` (`esc-<12hex>`), `task`, `pod`, `step`,
    `role`, `kind`, `caused_by` (`callId`|hop id), `prompt` (redacted at creation, the same
    `_redact` approvals use), `options: list[Option]`, `recommendation`, `requested_schema|None`,
    `asked_at`, `expires_at`, `on_expiry: Literal["deny","block"]`, `policy:
    Literal["person","recommendation","deny","fail"]`, `state: Literal["pending","resolved",
    "expired","decided"]`, `resolution: Resolution|None` (`option_id`, `content`, `by`, `channel`,
    `at`), `seq: int`, `legacy: dict` (`token` or `questionId`, so old surfaces keep working).
  - `platform/store.py`: `escalations_dir` under `Home`; `write_escalation`, `read_escalation`,
    `list_escalations(state=None, since_seq=None)`, `next_escalation_seq()` (one counter file,
    under the store lock). Mode 0600 like `consult-parked/`.
  - `tasks/application/escalations.py` (new): `open_escalation(...) -> Escalation` and
    `attach(task, escalation)` which appends the id to `TaskRecord.escalations: list[str]` AND
    keeps writing the legacy field (`approvalToken`/`question`) from the record. Callers:
    `governance/gate.py::_park` and the `wait` path, `tasks/application/record.py` consult park
    conversion, `hops/application/steps.py::_run_input_step`, `hops/gates/pre_hop.py::_park_if_check_changed`.
    Kind `approval` options are `approve_once|approve_task|deny`; `consult` = model options +
    `decline`; `input`/`gate` = `decline` + `requested_schema`.
  - `operator/inbox.py::build_inbox`: unchanged output, but `needsYou` is built from
    `list_escalations("pending")` joined to its task, not from the scan; the scan remains only for
    `failed/doneSince/running`.
  - Expiry sweeps (`approval_sweep_expired`, `sweep_expired_questions`) also mark the record
    `expired`.
- **Acceptance:**
  - unit `tests/unit/platform/test_store.py`: round-trip, `seq` monotonic across two writes,
    `list_escalations(since_seq=)` exact.
  - integration `tests/integration/tasks/test_escalations.py`: each of the five creation sites
    produces one record with the right `kind`, `options`, `on_expiry`, and the task's
    `escalations` holds its id; the legacy field equals the projection.
  - e2e: the whole lane green unchanged (`test_operator_in_the_loop.py` is the oracle that nothing
    visible moved).
  - `tests/architecture` green (record in kernel, store in platform, opener in tasks).
- **Contention:** `gate.py`, `record.py`, `steps.py`, `pre_hop.py`, `inbox.py`, `store.py`,
  `task.py`. Not P51-1's files.

### P51-3 — one event family and metrics folded from it

**Status:** DONE (merged 2026-10-25, 8571e7a9)· **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** five pause events with five payloads (`approval_requested`, `question_asked` with
  the whole question, `input_requested`, `input_answered`, `input_expired`); metrics scrape
  `task.answers` × audit log (`tasks/application/escalation.py`) and cannot tell a policy decision
  from a human one; no span measures the wait.
- **Goal:** `escalation_asked|delivered|resolved|expired|decided` with one payload, a span whose
  duration is the wait, and `/metrics` folded from the events.
- **Non-goals:** removing the five old events (P51-9 after Tack moves off them); OTel semconv
  work beyond attributes.
- **Spec:** `trace-store.spec.md` (event types + payload), `observability-export.spec.md` (span
  `escalation`, attributes `docket.escalation.{id,kind,policy,by,channel,level}`),
  `operator-loop.spec.md` area 7 item 5 (points at the new family), `serve-read-api.spec.md`
  `/metrics` lines.
- **Change:** `observability/trace.py::EVENT_TYPES`; emitters next to each `open_escalation` /
  resolution / expiry / policy decision; `prompt` only at export level `conversation`;
  `observability/projection.py`: open span at `escalation_asked`, close at
  `resolved|expired|decided`, parent = the hop span; `interfaces/http/routes/metrics.py`:
  `docket_escalations_total{kind,outcome,by}` and `docket_escalation_wait_seconds_{sum,count}{kind}`
  computed from trace events; `tasks/application/escalation.py` deleted, its two counters kept
  only if a consumer exists (grep `escalation_rate`; Tack reads `/metrics`? verify, else delete).
- **Acceptance:** unit tests on the projection (one span per escalation, duration, attributes);
  integration on `/metrics` with a parked-then-answered task; e2e `test_operator_in_the_loop`
  skeleton gains the new events beside the old; export privacy test: `minimal` carries no prompt.
- **Contention:** `observability/*`, `routes/metrics.py`. Not P51-4's files.

### P51-4 — one view, one render, every surface shows the same escalation

**Status:** DONE (merged 2026-10-25, 9ffd6f6a)· **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `docket run` renders approvals in place and nothing for a question
  (`render/progress.py::_RENDERABLE_EVENT_TYPES`); `task show` never prints the question
  (`task_render.py::_render_show`); Telegram `/status` prints no question and no option ids;
  `state`/`command` exist only in the CLI JSON (`commands/inbox.py::_json_view`); `GET /inbox`
  has no contract test on the real route.
- **Goal:** `EscalationView` in the contract with affordances; one render function; `inbox`,
  `task show`, the progress view, Telegram and notifications use it; `GET /escalations` and
  `escalations[]` on `GET /inbox`.
- **Non-goals:** resolving (P51-5); prompting in place for questions (P51-6, needs the wait path).
- **Spec:** `operator-loop.spec.md` areas 5, 6 item 11, 10 item 2; `operator-api.spec.md`
  (`GET /escalations?since=<seq>&pod=&task=`), `cli-json-shapes.spec.md`, `telegram-integration.spec.md`
  `/status`, `cli-interface.spec.md` `task show`.
- **Change:**
  - `kernel/operator_contract.py::EscalationView`: record fields minus `legacy`, plus `state`
    and `affordances: {options, acceptsText: bool, resolveUrl: "/escalations/<id>"}`. No command
    strings.
  - `operator/render.py` (new): `render_escalation(view, level) -> RenderedEscalation(title,
    prompt|None, options: list[(id,label,recommended)], expires_at)`; `level` applies the three
    content levels; option **ids** always present.
  - Consumers: `commands/inbox.py` (prints its `docket task answer <id> --option <x>` line from
    the rendered options), `commands/task_render.py::_render_show` (section `Waiting on you`),
    `render/progress.py` (renders `escalation_asked`, line `⏸ <role> asks: <title> · options a,b
    · docket task answer <id> --option <a>`), `telegram/bot.py::_handle_status` (adds `options:
    a, b (recommended a)` and `reply: /answer <id> <option>`), `operator/notify.py::render_text`
    (uses the same renderer).
  - `interfaces/http/routes/escalations.py` (new) + `table.py` row; `GET /inbox` adds
    `escalations[]` (additive; `needsYou` unchanged for Tack).
  - MCP: `escalations(since=None)` tool added; `inbox` unchanged.
- **Acceptance:** golden-free contract test `tests/contracts/test_escalation_http.py`: park a real
  consult through the harness, GET `/inbox` and `/escalations`, compare to
  `tests/fixtures/operator-v1.1/escalation-consult.json` (options, recommendation, state, seq);
  unit tests for `render_escalation` at the three levels (ids present at `minimal`, prompt
  absent); CLI tests for `task show` and `inbox` output; progress test with a scripted trace;
  Telegram `/status` test; e2e lane green.
- **Contention:** `interfaces/*`, `operator/notify.py`, `operator_contract.py` (additive). Not
  P51-3's files.

### P51-5 — one verb: `resolve`

**Status:** DONE (merged 2026-10-25, f7a1551e)· **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** three answer vocabularies (`grant/deny`+`approve_once/approve_task`;
  `accept/decline/cancel`+`optionId` in `content`; memory `approve/refuse`), two "resolved once"
  rules (`ApprovalConflict`, `AnswerError("is not waiting_input")`), four surfaces each mapping
  errors by hand (`task_control.py`, `mcp.py`, `bot.py`, `task.py`).
- **Goal:** `resolve(id, option_id, content, *, by, channel)` is the only entry; every surface
  calls it; old routes/tools/verbs delegate.
- **Non-goals:** moving continuations to dispatch (P51-6): in this card `resolve` still calls
  today's continuations (`approval_grant`+`resolve_waiting_approval`, `_answer_consult`,
  `_apply_route_outcome`) behind one function. A2A (P51-7).
- **Spec:** `operator-loop.spec.md` new area "Resolve" replacing areas 7.1 and 10; `operator-api.spec.md`
  `POST /escalations/<id>` body `{optionId, content?, actor?}` and error table (404 unknown, 409
  not pending, 422 schema/option/policy); `mcp-server.spec.md` `resolve`; `telegram-integration.spec.md`
  `/answer <id> <option|text>`; `cli-interface.spec.md` `task answer` absorbs `approve|deny`.
- **Change:** `tasks/application/escalations.py::resolve` (validate option ∈ options, content vs
  `requested_schema`, `pre_input` screen, write `resolution`+`state`, audit
  `escalation.resolve`, emit `escalation_resolved`, dispatch to the kind's continuation);
  `cancel` accepted as an alias of `decline` and documented as such; `POST /escalations/<id>`;
  MCP `resolve`; `task answer <ref> --option approve_once|approve_task|deny` works on an
  `approval`; `task approve|deny`, `POST /approvals/<token>`, `POST /tasks/<id>/answer`,
  MCP `approvals_grant|deny|task_answer`, Telegram `/approve|/deny` become thin adapters
  (lookup by `legacy.token`/`questionId` → `resolve`).
- **Acceptance:** one table test per kind (initial record → `resolve` → task status + legacy
  side effects identical to today's oracles in `tests/e2e/test_operator_in_the_loop.py`);
  idempotence: second `resolve` → 409 on HTTP, `McpToolError` on MCP, warning exit 0 on the CLI
  (today's CLI behaviour kept); e2e lane green; Telegram `/answer <id> <text>` on an options
  question replies with the ids.
- **Contention:** everything P51-4 touched plus `answers.py`, `actions.py`. Serial.

### P51-6 — dispatch applies the resolution; `wait` prompts questions in place

**Status:** PARTIAL (merged 2026-10-25, 1453d372): consult and input resolutions are applied at claim and a consult is answered in place; approvals, gates and check_changed still apply their follow-up inside `resolve` (deferring them breaks `approved_ready`, which reads pregrants and gateOverridePipelineIndex); left: move them, then `task answer` for an in-turn consult and the per-task consult budget under wait· **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `answer_task` takes the pod task-list lock and resolves the full pipeline to
  answer (`answers.py` docstring on the deadlock); consults park even under `wait` with a TTY
  because they never had a record to wait on (`consult.py::run`).
- **Goal:** `resolve` writes and emits only; the claim path reads the task's resolved escalations
  and materialises pre-grants / consult note / `on:` route; a consult under `wait` on a TTY uses
  the approval wait path and the progress prompt.
- **Non-goals:** deleting the legacy fields (P51-9).
- **Spec:** `pod-dispatch.spec.md` "Parked approvals", "Operator input steps and answers",
  "Consult" (resume reads escalations); `operator-loop.spec.md` area 2 item 3 (wait applies to
  consults).
- **Change:** `hops/application/compose.py::_compose_hop` and `executor._resolve_resume_state`
  read `task.escalations` → records with `state in (resolved, decided)` not yet applied
  (`applied_at` field added to `Resolution`); `resolve` drops the continuation calls;
  `governance/gate.py::_wait` reused by `consult.py` when `approval_mode == "wait"` and
  `ctx.consult_park`; `render/progress.py` prompt line gains `[1..n] option  [d]ecline  [Enter]
  keep waiting` for `kind != approval`.
- **Acceptance:** e2e `test_operator_in_the_loop.py` unchanged and green (the oracle); new e2e
  `test_a_question_is_answered_in_place.py` (TTY via `script`/pty, FakeModel consult, answer
  `1`, task `done` without `waiting_input`); unit: `resolve` performs no `TaskRepository.update`
  of hops/pipeline; `tests/architecture` green.
- **Contention:** `hops/*`, `gate.py`, `consult.py`, `progress.py`. Not P51-7's.

### P51-7 — the A2A facade (ADR 0016 §9 trigger fired: Tack is the named client)

**Status:** DONE (merged 2026-10-25, e2258f5e)· **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec + ADR

- **Trigger:** ADR 0016 deferred the A2A binding "until a named A2A client will call docket".
  Tack calls docket and today builds its decision card from three shapes with a workaround
  (`crates/tack-runner/src/harness/docket.rs::consult_question`, fixtures README "Where a parked
  question's options live").
- **Goal:** `message/send`, `tasks/get`, `tasks/cancel`, push-notification config and an agent
  card over the existing records; a task in `INPUT_REQUIRED` carries the escalation as a
  `DataPart` (MCP elicitation + the `operator-v1.1` extension with its `$id`); a `message/send`
  with the result `DataPart` calls `resolve`.
- **Non-goals:** streaming (`message/stream`); replacing the operator routes; auth beyond the
  existing Bearer token.
- **Spec:** new `specs/api/a2a-binding.spec.md`; `operator-api.spec.md` cross-reference; ADR 0032
  records the decision and the extension declaration.
- **Change:** `interfaces/http/routes/a2a.py` (JSON-RPC 2.0 over `POST /a2a`), agent card at
  `GET /.well-known/agent.json` (name, skills = pods, capabilities `pushNotifications: true`,
  extensions = the v1.1 `$id`); push config stored as a `kind: channel` `webhook` entry scoped
  to the task (reuses `operator/adapters/webhook.py`); mapping table `status ↔ TaskState` is the
  existing `a2a_state`.
- **Acceptance:** contract tests with recorded JSON-RPC exchanges (`tests/contracts/a2a/*.json`):
  send task → `SUBMITTED`; park consult → `tasks/get` shows `INPUT_REQUIRED` with the DataPart;
  `message/send` with `{action: accept, content: {optionId}}` → `WORKING`/`COMPLETED`; push
  received on a local listener; e2e `test_plan_of_record_over_http.py` gains an A2A variant.
- **Contention:** `interfaces/http/*`, `operator/channel.py`. Not P51-6's.

### P51-8 — the level travels with the task; the table is a document

**Status:** DONE (merged 2026-10-25, eb55a12d)· **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `lights-out` has four requirements, none about pauses (`profile.py::lights_out_violations`);
  Tack computes a level per task (`tack-core::autonomy::level_for`) that docket never receives;
  L4 and L5 are indistinguishable in docket; two expiry sweeps with two outcomes.
- **Goal:** `autonomy: L3|L4|L5` on `POST /tasks` and `task add --autonomy` (narrows only; pod
  profile is the ceiling: `attended` ≤ L3, `lights-out` ≤ L5, default L3/L4); the `kind: autonomy`
  document holds the table kind × level → `policy` + `on_expiry`; policy evaluated at
  `open_escalation` and recorded; one expiry sweep.
- **Non-goals:** Tack's domain → level mapping; a `role` dimension (follow-up with trigger: a
  second measurement showing read-only roles consulting).
- **Spec:** `security-gates.spec.md` "Profiles" (+ "Autonomy"), `config-format.spec.md`
  (`kind: autonomy`, built-in document `templates/autonomy/default.yaml` = design doc 7.5 table),
  `operator-api.spec.md` (`autonomy` field, 422 above ceiling), `pipeline-format.spec.md`
  (`validate` refuses `input` steps for a pod whose ceiling allows L4+ unless the task level is
  L3 — state the exact rule), `operator-loop.spec.md` (policy, `on_expiry`).
- **Change:** `TaskRecord.autonomy`; `teams/autonomy.py` (load document, `policy_for(kind, level)`);
  `open_escalation` consults it: `recommendation` → resolve immediately (`state: decided`,
  P51-1's path generalised; `consultMode` becomes the alias of row `consult`), `deny` → the
  `approval_unavailable` denial with `failureKind: needs_human`, `fail` (gate) → task `failed`
  `needs_human`; `approvalMode` kept as the alias of row `approval`; `sweep_escalations()`
  replaces both sweeps using `on_expiry`; `escalation.decided` added to `EVENT_KINDS` so
  channels can subscribe; metrics gain `level`.
- **Acceptance:** table test over kind × level (15 cells) on `policy_for`; e2e
  `test_lights_out_and_budget.py` gains: L5 task + policy `ask` → `failed needs_human` within one
  sweep, no `waiting_*`; L4 task + consult → `done` with `escalation_decided`; L3 task on a
  lights-out pod → parks as today; `POST /tasks` with L5 on an attended pod → 422; `validate`
  refusal message for an `input` step; expiry test moves from two files to one.
- **Contention:** `profile.py`, `pod_settings.py`, `escalations.py`, `task_create.py`,
  `pipeline/domain/*`. Serial after P51-6.

### P51-11 — close the loose ends P51-2..P51-7 left outside their files

**Status:** DONE (merged 2026-10-25, b23082f9) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + docs

- **Trigger (measured in the integration reviews of 2026-10-25):** each item was found by a worker
  who stopped at its card boundary.
- **Goal:** six independent fixes, none touching `tasks/application/escalations.py`, `consult.py`,
  `profile.py` or `pod_settings.py` (P51-8's files).
- **Items:**
  1. **Retention.** `list_escalations` reads every record file on each `GET /inbox` (Tack polls it
     every 2 s) and nothing prunes them. Settled records (`resolved|expired|decided`) move out of
     the directory the inbox scans and are deleted by the same retention that prunes traces. The
     pending scan must not read a settled file. Spec: `docket-store`.
  2. **`queue.py` enqueue with `require_approval`.** It creates an approval and parks the task but
     opens no escalation (`tasks/application/queue.py`, search `require_approval`). It opens one
     through `open_for_approval` like the other five pause sites.
  3. **The A2A push channel.** `a2a-<task>` channels (`interfaces/http/routes/a2a_push.py`) are never
     deleted and show in `docket setup notify`. Remove a task's channel when the task is terminal
     (done, failed, aborted), in the service sweep.
  4. **`docket task answer` for an in-turn consult.** `interfaces/cli/commands/task.py::_question_of`
     refuses a consult that is being answered inside the turn; answer it through `resolve` like the
     prompt, HTTP and MCP do.
  5. **Docs.** `docs/DOCKET.md`, `docs/troubleshooting.md`, `docs/SECURITY-SIMPLE.md` and
     `docs/WORKFLOW-GUIDE.md` still tell the operator `/answer <task-id>` and `task approve <token>`
     as the only way; say `task answer <escalation-id> --option ...` first, the old verbs second.
     `docs/CONFIGURATION.md` and `docs/DOCKET.md` list `escalations/` among the files under Home.
  6. **Privacy listing.** `governance/privacy.py::_CLASS_ATTRIBUTES["prompts"]` omits
     `docket.escalation.prompt`, so the "leaves this host" listing is incomplete. Add it, with a
     test that every exported prompt attribute is listed.
- **Non-goals:** moving the approval continuation out of `resolve`, `escalation_delivered`, the
  record of a pod-decided consult and the consult budget (all P51-9, after P51-8).
- **Acceptance:** one failing-first test per item 1 to 4 and 6 (retention: after settling N records
  the pending scan opens zero settled files and a retention pass deletes the old ones; queue: a
  `require_approval` enqueue yields one `approval` escalation and the inbox lists it once; push: the
  channel is gone after the task is `done`; task answer: an in-turn consult is answered and the
  record is `resolved`); docs verified with a grep that no sentence names a verb that does not exist.
- **Contention:** `platform/store.py` (settled directory), `operator/inbox.py`, `queue.py`,
  `a2a_push.py`, `commands/task.py`, `governance/privacy.py`, the four docs. Not P51-8's files.

### P51-12 — the live smoke can run with the jail on

**Status:** DONE (merged 2026-10-25, fd33d8b4) · **Size:** S · **Model:** Sonnet · **Kind:** tooling (scripts only, no `src/`)

- **Trigger (measured 2026-10-25):** two live evals (local model and a remote one, 0/3 each) parked
  on an approval because the model ran `xxd` to read the artifact's bytes. The smoke runs
  `docket setup sandbox off` (`scripts/smoke_workflow.py`, search `"sandbox", "off"`), and with the
  jail off the command allowlist applies. `docket init` turns the jail on where Landlock or Seatbelt
  is detected, and inside a working jail the allowlist stands down (security-gates), so the eval
  measured a configuration the product does not default to.
- **Goal:** `smoke_workflow.py --live-model` gains `--sandbox on|off` (default `off`, unchanged);
  `on` runs `docket setup sandbox on` (or leaves `init`'s recorded choice) and fails fast with a
  one-line reason when no backend is available; `scripts/maint/live_eval.py` passes it through.
- **Non-goals:** any change under `src/`; making `on` the default (a separate decision once an eval
  with the jail on passes).
- **Acceptance:** tests for the argument rules and for the exact `setup` command run before the
  pipeline (copy the style of the P51-10 tests in `tests/integration/product/smoke/`); the default
  command line stays byte-identical; `live_eval.py --dry-run` prints the flag.
- **Contention:** `scripts/smoke_workflow.py`, `scripts/maint/live_eval.py` and their tests.

### P51-9 — retire the old shapes

**Status:** TODO (needs P51-8; no external trigger: Tack adapts to docket, decided by the maintainer 2026-10-25) · **Size:** M · **Model:** Sonnet · **Kind:** deletion + spec

- **Also (left by P51-6 and P51-3, decided here because the deletions force the question):**
  move the approval, gate and `check_changed` follow-up (`approval_grant`, pre-grants, gate override,
  task grants) out of `resolve` into the claim path; give `escalation_delivered` a real emitter or
  delete it (no event without a writer); store a record for a pod-decided consult or drop its
  `decided_consult` id; count in-turn consults in the task's consult budget; make the
  `SECURITY-SIMPLE.md` / `CONFIGURATION.md` sentence say `resolve` is the shared function; make
  `docket task prune --traces` call `prune_settled_escalations`; add `level` to the A2A DataPart.
- **Goal:** delete the seven task fields (keep `escalations[]`), `ApprovalView` from `needsYou`,
  `POST /approvals/<token>`, `POST /tasks/<id>/answer`, MCP `approvals_*`/`task_answer`, the five
  old trace events, `resolve_waiting_approval` and `answer_task`; contract `operator-v2`;
  `gen_operator_schemas.py` regenerated (allowed: a contract bump, not a golden hide).
- **Acceptance:** suite green; `tests/architecture`; baselines only shrink;
  the e2e lane rewritten against the new shapes only; Tack's fixture capture script re-run by the
  Tack maintainer against this build (note in the handoff, not a docket test).

---

### P51-10 — the live eval runs with `consultMode` and against a remote provider

**Status:** DONE (merged 2026-10-25, 940536fa) · **Size:** M · **Model:** Sonnet · **Kind:** tooling (scripts only, no `src/`)

- **Trigger (maintainer request 2026-10-25):** run the live eval against Anthropic as well as the
  local model, and measure `consultMode decide` (P51-1). Today `scripts/smoke_workflow.py` never
  sets `consultMode` (the basic scenario still parks on a consult) and accepts only a loopback
  endpoint (`_loopback_endpoint`).
- **Goal:** `smoke_workflow.py --live-model` gains `--consult-mode park|decide` (default `park`,
  applied with `docket pod set` on the smoke pod) and `--provider <name> --allow-remote` to use a
  built-in remote provider such as `anthropic` with `--model`; `scripts/maint/live_eval.py` passes
  both through.
- **Non-goals:** any change under `src/`; a remote run in CI (a real model never gates CI); the
  default behaviour (no flag means loopback and `park`, unchanged).
- **Change:**
  - The key comes from the environment (`ANTHROPIC_API_KEY`) or, when unset, is read at run time
    from the operator's `$DOCKET_HOME`-independent default `~/.docket/secrets.json`. It is never
    written to `--out`, a run log, a trace copy or a kept world (`--keep-worlds` must scrub it);
    a test proves a canary key does not appear anywhere under `--out`.
  - `--provider` without `--allow-remote` exits 2 with a one-line reason; the endpoint printed in
    the banner says `remote: <provider>`, not `(loopback only)`.
  - The existing loopback-only test stays and still passes for the default path.
- **Acceptance:** unit/integration tests under `tests/` for the argument rules (remote needs the
  flag, default stays loopback, `--consult-mode` reaches `pod set`), the canary-key scrub test,
  `live_eval.py --dry-run` printing both flags; `uv run ruff check . && uv run ruff format --check
  . && uv run --all-extras mypy src`, `tests/guards`, `tests/e2e`. No live call is made by the
  worker; the coordinator runs the live evals.
- **Contention:** `scripts/smoke_workflow.py`, `scripts/maint/live_eval.py` and their tests. Not
  P51-5's files.

**Notes for Tack (not docket cards)**

- Pause the attempt clock while the task is `INPUT_REQUIRED`; the deadline is the escalation's
  `expiresAt`. Today the attempt timeout turns a legitimate L3 wait into `timeout`.
- Subscribe (`webhook` channel / A2A push) instead of polling `/inbox` every 2 s per attempt.
- Send `autonomy` per task from `level_for`; map `failureKind: needs_human` to "re-route at L3".
- After P51-7: one A2A client replaces `approval_question`, `held_approval_question`,
  `consult_question` and the task-view workaround.

## ○ PHASE 52 PLANNED — the harness adapts to the model by data, and pays for context once (D-73, ADR 0033)

> Planned 2026-10-25 by the maintainer from a code audit against a harness-engineering survey
> ([ADR 0033](docs/adr/0033-the-harness-adapts-to-the-model-by-data.md) holds the findings and the
> refusals). Cards are cut by **file ownership**, not by technique: everything one worker would
> change in the same files is one card, so no file is edited twice across the phase. Wave A may
> start beside Phase 51's remaining cards: no Phase 52 card edits `hops/application/dispatch*`,
> `tasks/`, `operator/` or `interfaces/http/` (P52-1 writes only `observability/`; `/metrics`
> reads the fold).

### How a Phase 52 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR) with `Last Updated` and the
  `specs/README.md` row in the same commit.
- **Read bounded, to spend little:** `card_packet.py P52-<n>`, ADR 0033 §"Decision" (one screen),
  the spec section the card names, the files it names. Nothing else: not the ADR's findings, not
  another card, not a spec directory. A worktree has no `internal-docs/`.
- **Measure with what exists, free first.** The replay bench
  (`scripts/maint/context_replay.py tests/fixtures/context-replay --policy <name>`) costs nothing
  and is the oracle for bytes and counted tokens; a card that changes what the model sees adds its
  `--policy` and reports the table before/after. The live eval (`scripts/maint/live_eval.py -n 3`,
  local endpoint, `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`) runs **once per wave by the integrator**, not
  per card; the remote provider once at the phase close, after a go.
- **Every card:** focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files. The e2e lane
  only on cards that change a tool's output or the wire (P52-2, P52-3, P52-7, P52-8).
- **Integrator seams:** P52-2 and P52-3 both bump `agent-loop.spec.md`; the integrator renumbers at
  merge (as in Phase 44). The full default suite runs once per merge, `--lf` after.
- Workers in `.claude/worktrees/p52-<n>`, one card per worktree. **Model per card** is on the
  card: Sonnet for behaviour in `src/`, Haiku for data-only cards. Delta-only handoff with the
  end-of-work control summary.

**Waves (by file contention)**

| Wave | Cards | Why this order |
| --- | --- | --- |
| A | P52-1 ∥ P52-2 ∥ P52-3 ∥ P52-6 (∥ P52-4 once unblocked) | disjoint owners: `observability/`+bench · `kernel/text.py`+toolbox+`session.py` · request/wire/catalog · recipes · `governance/` |
| B | P52-5 ∥ P52-7 ∥ P52-8 | P52-5 needs P52-1's re-read figure; P52-7 continues P52-3's files; P52-8 continues P52-2's files |

### P52-1 — the numbers: cache hits, tokens per accepted task, re-reads

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** observability + script

- **Trigger:** maintainer request (ADR 0033 §Decision 5). No cache-hit ratio exists; `task show`
  prints usage per model but not per accepted task; the Phase 44 follow-up "measure which calls
  repeat before cutting anything" never ran because its measurement was framed as a paid live run.
  The recorded traces already hold the answer.
- **Goal:** three figures, read-only on data docket already records. (1) `cache_hit =
  cachedTokens / inputTokens` on every `llm_call` event and folded per task and per role in the
  metrics fold `observability/` keeps (the `/metrics` route reads it unchanged). (2) `tokens per
  accepted task`: counted tokens of tasks that ended `done`, as a line of `docket log --summary`
  and a metrics key. (3) `context_replay.py --repeats`: per step, the `read`/`grep`/`glob` calls
  whose canonical arguments repeat; per task, the files the Implementer read that the Lead had
  read.
- **Non-goals:** dollars; alerting; any change to what the model sees.
- **Spec:** `trace-store.spec.md` (3.2.0 → 3.3.0: `cache_hit` is derived, not stored);
  `serve-read-api.spec.md` (4.2.0 → 4.3.0: the two metrics keys); `cost-tracking.spec.md` only if
  a sentence there names the per-task figure.
- **Change:** `observability/` metrics fold (one function per figure); `interfaces/cli/commands/log*`
  renders the summary line; `scripts/maint/context_replay.py` gains `--repeats` (a table: step,
  repeated calls, re-read files, bytes they cost at the measured ratio).
- **Acceptance:** fixture `tests/fixtures/traces` (an `llm_call` with `cachedTokens` > 0) →
  `GET /metrics` shows `cacheHit` for that task's role; a task record `done` with usage →
  `docket log --summary` prints `tokens per accepted task`; `context_replay.py
  tests/fixtures/context-replay --repeats` prints a non-empty table and the JSON form lists at least
  one repeated `read` (the committed implementer fixture has one). Oracle: the numbers equal a
  hand-computed value from the fixture, asserted in `tests/unit/observability/` and
  `tests/integration/observability/`. The private replay copies are run by the integrator and the
  figure recorded on P52-5's trigger line.
- **Contention:** `observability/` and the bench script only. Serial with nothing.

### P52-2 — tool results the model can use

**Status:** TODO · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033 findings, verified 2026-10-25: `kernel/text.py::cut_output` keeps the head
  only; `toolbox.py` merges stderr into stdout (`:419`) and hints only on exit 126 (`:472-473`);
  `edit` says only "not found" (`:188-197`); no ANSI or repeated-line normalization anywhere; the
  condensation window (`agent/session.py:65-69`) lets one 20 KB grep evict a 1.2 KB README that
  is then re-read (Phase 44 close note).
- **Goal, in order (a park leaves the rest visible):**
  1. `cut_output` for `bash` and `verify` keeps head and tail (40/60) with the marker between
     them; `read` keeps head-only (the head is right there).
  2. Lossless normalization before the cut: strip ANSI escapes, resolve `\r` progress lines to
     their last state, collapse consecutive identical lines to `line  [x N]`.
  3. On exit ≠ 0, stderr first, then stdout; a fixed table of known causes: 126 (today's text),
     127 (`not on PATH inside the jail or not in allowCommands`).
  4. `edit` "not found" lists the three closest lines (`difflib`, ratio ≥ 0.6) with "the text
     must match exactly; copy it from `read` without the line-number prefix". Never auto-apply.
  5. Condensation: a tool result under 1,500 chars is never condensed while a larger one in the
     same step is whole (monotone: never condenses more than today).
- **Non-goals:** the artifact store (P52-8); timestamps or pids replaced; any change to `read`'s
  window; a second normalization pass elsewhere.
- **Spec:** `agent-loop.spec.md` (3.2.0 → 3.3.0, tool-output section: head+tail, normalization,
  error order); `session-history.spec.md` (1.9.2 → 1.10.0, the small-results rule beside
  requirement 31).
- **Change:** `kernel/text.py` (`cut_output` gains a `tail` share; a new `normalize_output`),
  `agent/tools/builtins/toolbox.py` (`bash`, `edit`), `hops/application/verify_tool.py`,
  `agent/session.py::condense_history`.
- **Acceptance:** a `bash` whose output is 20 lines of progress + a pytest summary at the tail →
  the result shows the summary after the marker; an output with ANSI colour and 50 identical lines
  → one line with `[x 50]`; `edit` with a near-miss `old_string` → the error names the closest
  line; a step with one 20 KB grep then a 1 KB read → the read survives condensation. Oracles:
  `tests/unit/kernel/test_text.py`, `tests/unit/agent/tools/builtins/`,
  `tests/integration/agent/test_session_condensation*`; the bench `--policy p52-2` reports bytes
  per step before/after on `tests/fixtures/context-replay` (no step worse). Lane e2e green.
- **Contention:** the toolbox, `kernel/text.py`, `session.py`. P52-8 continues these files after
  this merges.

### P52-3 — one request shape: a stable prefix and sampling from the catalog

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `agent/loop_request.py:139-153` appends the finalization instruction to the system
  message, so the turn's last (longest) request misses the cached prefix; `LoopConfig.temperature`
  (`agent/loop_types.py:64`) has no writer (unwired machinery, the eighth); `top_p` does not exist;
  the local endpoint reports 1.0 inherited while the model card asks 0.7/0.8 in non-thinking mode.
- **Goal:** (1) finalization is a trailing `user` message, request-only as today, the system
  message untouched; (2) a catalog row may declare `sampling: {temperature, topP}`; the driver
  passes it into `LoopConfig` and the wire sends both only when declared; the trace's `llm_call`
  records what was sent.
- **Non-goals:** the profile (P52-7); `tool_choice`; reasoning; any default when the row declares
  nothing (the endpoint's own stays).
- **Spec:** `agent-loop.spec.md` (finalization shape; sampling passthrough);
  `model-profiles.spec.md` (5.0.3 → 5.1.0, the `sampling` fields on a catalog row).
- **Change:** `agent/loop_request.py::_finalization_messages`, `agent/loop_types.py` (`top_p`),
  `models/catalog.py` (row fields), `models/adapters/openai_wire.py::build_payload`,
  `hops/application/driver.py` (LoopConfig construction), `agent/loop_trace.py` (record).
- **Acceptance:** a turn that exhausts its budget → the finalization request's first message is
  byte-identical to the previous request's (oracle: `tests/integration/agent/test_loop_*` compares
  the two captured payloads); a provider doc with `sampling` → the payload carries `temperature`
  and `top_p`, and without it carries neither (`tests/unit/models/adapters/test_openai_wire.py`);
  `docket status` or `task show` unchanged. Lane e2e green.
- **Contention:** `agent-loop.spec.md` with P52-2 (integrator renumbers). Files disjoint from
  every Wave A card.

### P52-4 — a command the lexer cannot parse is refused, not asked

**Status:** BLOCKED (needs maintainer go: a parse failure stops being an `ask`) · **Size:** S ·
**Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** `governance/security.py:353-440` with `command_lexer.py:162-169`: a `shlex`
  `ValueError` (an unclosed quote) yields `ask: command could not be parsed`, which parks the
  task for a person. The model's syntax error becomes human waiting time; with `consultMode`
  irrelevant here, a lights-out pod stalls on a typo.
- **Goal:** the parse failure is `REFUSED [syntax]: <lexer message>; fix the quoting and call
  again`. Nothing runs, as today. The opaque markers (`$(`, backticks, `${`, `eval`, `exec`) and
  the unclosed heredoc keep asking: they are risk, not syntax.
- **Non-goals:** `bash -n`; any change to SAFE_BINS or `allowCommands`; the denial counter (a
  refusal still counts toward the three-denials stop).
- **Spec:** `security-gates.spec.md` (1.6.0 → 1.7.0, the classifier table row).
- **Change:** `governance/security.py::classify_command` (one branch), the policy corpus row.
- **Acceptance:** `bash` with `echo "unclosed` → `REFUSED [syntax]` and no escalation record, no
  audit `approval` entry (oracle: `tests/integration/governance/test_security*` plus the audit
  oracle from `tests/support/e2e_oracles.py`); the 310-row corpus unchanged except the parse rows.
- **Contention:** `governance/` only.

### P52-5 — the Lead's locators: the code it found reaches the Implementer

**Status:** BLOCKED (needs P52-1's re-read figure on the private replay copies) · **Size:** L ·
**Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger (to be filled by the integrator from P52-1):** source `context_replay.py --repeats`
  on the recorded implementer steps; metric: share of the Implementer's `read` calls on files the
  Lead had already read; window: the recorded steps; threshold: ≥ 30 %; observed: _pending_.
  Context: Phase 44 closed with Implementers at 0.77/0.80 sent ratio "from longer trajectories";
  `TaskBrief.context` is prose (`kernel/brief.py:24-38`), so the Lead's reads are lost.
- **Goal:** the Lead may put locators `path:<file>#L<a>-<b>` in `context`; `_hop_message`
  (`hops/application/compose.py:181`) reads each range from the task worktree, fresh, and renders
  a `## Code the Lead located` section inside the Implementer's budget share
  (`agent/context.py:148-157`); ranges that do not fit stay as bare locators; an invalid locator
  is listed as such. The Lead's hop instruction asks for locators (`teams/builtin_roles.py:82-109`).
- **Non-goals:** a viewer role; sub-agents; any model call in the composition; locators in
  handoffs other than the Lead's.
- **Spec:** `pod-dispatch.spec.md` (10.7.0 → 10.8.0, "Bounded hop prompts");
  `role-archetypes.spec.md` (4.1.0 → 4.2.0, the Lead's instruction).
- **Change:** `kernel/brief.py` (validate the locator form), `hops/application/compose.py`
  (extraction + section), `agent/context.py` (share), `teams/builtin_roles.py` (instruction text).
- **Acceptance:** a brief with two locators, one valid and one past EOF → the Implementer's
  message holds the valid range's lines and names the invalid one; with a 200-token share → the
  first range whole, the second as a bare locator (oracle: `tests/integration/hops/test_compose*`);
  the starter example and `tests/agent/release/test_starter_journey.py` keep their field set
  (locators live inside `context`, no new field). Bench: `--policy p52-5` on the implementer
  fixtures reports re-reads before/after.
- **Contention:** `compose.py` is shared with P51-6's continuation work if that card is still open;
  claim after it merges.

### P52-6 — recipes for the pod as a viewer/editor team

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** data + tests

- **Trigger:** ADR 0033 §Decision 4: the pod already separates exploration from editing; no recipe
  shows the three shapes the survey's level matrix asks for. `researcher` is `strong` by default
  (`teams/builtin_roles.py:243-247`), so a cheap exploration must say so.
- **Goal:** three recipes under `templates/recipes/`, each with its `README.md` sentence and
  validated by the existing recipe tests: (a) `explore-then-edit`: `researcher`
  (`modelClass: cheap`, read-only) → `implementer` → `reviewer`; (b) `strong-plan-cheap-edit`:
  `lead` on `strong`, `implementer` on `cheap`, `verifyCmd` gate with `on: {fail: {goto:
  implementer, max: 1}}`; (c) `parallel-explore`: a `parallel` group of two cheap researchers
  with disjoint instructions → join → implementer, plus `on: {fail: {goto: lead, max: 1}}` from
  the implementer's step back to the Lead.
- **Non-goals:** code; a new role; a sub-agent tool; claims about savings in the README.
- **Spec:** none (recipes are data; `pipeline-format.spec.md` 4.1.0 already allows every field).
- **Change:** `templates/recipes/<name>/pipeline.yaml` + `README.md` × 3; the recipe index test's
  expected list.
- **Acceptance:** `docket pod apply <recipe>` on a fresh home loads each without a validation
  error (oracle: the recipe lane's existing parametrized test picks them up); the `parallel`
  group validates (`pipeline/domain/step.py:90-193`).
- **Contention:** `templates/recipes/` only.

### P52-7 — `ModelProfile`: the contract varies with the model

**Status:** TODO (after P52-3) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033 §Decision 1. Today's single contract: an Implementer's schemas are about
  5,800 chars on every request (`consult` 1,229, `bash` 1,285); `tool_choice` is always `"auto"`
  (`openai_wire.py:110-112`); `budget_for_role` is unreachable on a 32k window without the manual
  env var in CONFIGURATION.md; the local eval needed the verdict parser's tolerance because the
  verdict was free text.
- **Goal:** a `profile` on a catalog row with built-ins `hosted` (today) and `local` (default for
  `local: true`): `toolSurface: full|minimal` (minimal = `bash`, `read`, `verify`, `verdict` when
  gated), `descriptions: full|compact` (≤ 2 sentences per tool for compact), `toolChoice: auto|
  forced-on-close` (the closing call of a verdict-gated step sends `tool_choice` for `verdict`),
  `budgets: window-derived` (`READ_DEFAULT_CHARS` and the tool-output cap as shares of
  `contextWindow`). The profile name is on every `llm_call` and in `docket status`.
- **Non-goals:** reasoning (deferred, ADR 0033); a per-role profile; heuristics by model name;
  changing `hosted` behaviour by one byte (goldens stay).
- **Spec:** `model-profiles.spec.md` (5.1.0 → 6.0.0, the profile and its two built-ins);
  `agent-loop.spec.md` (`tool_choice` on the chat port; window-derived budgets).
- **Change:** `models/catalog.py` (profile fields + resolution), `agent/ports.py` (`tool_choice` on
  the chat call), `agent/loop_types.py`, `models/adapters/openai_wire.py`,
  `hops/application/driver.py` (surface and budgets from the profile), `teams/role_composer.py`
  (surface), `hops/application/builtin_tools.py` (compact descriptions), `kernel/home.py` (derived
  defaults).
- **Acceptance:** a provider doc `local: true` without `profile` → `local`; its Implementer's
  request carries only the minimal surface and compact descriptions, and the closing call of a
  verdict step carries `tool_choice: {"type":"function","function":{"name":"verdict"}}` (oracle:
  captured payloads in `tests/integration/hops/test_docket_driver*`); a `hosted` row → payloads
  byte-identical to before (the CLI goldens and `tests/e2e` unchanged); `request_part_bytes["tools"]`
  for the local Implementer under 2,500. Live eval by the integrator at the wave close.
- **Contention:** continues P52-3's files; `builtin_tools.py` is not touched by P52-2 or P52-8.

### P52-8 — a result over the cap is kept whole and readable

**Status:** TODO (after P52-2) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0033: what passes `DOCKET_TOOL_MAX_OUTPUT_CHARS` is gone (the trace keeps a
  capped copy, `agent/loop_trace.py:219-220`, and no tool reads it); the condensation notice says
  "call X again", which re-runs a command whose result may differ and costs a round. A lower cap
  (the local endpoint needs 2,500) is only safe when the whole result stays reachable.
- **Goal:** a tool result over the cap is written whole to `<pod cache>/artifacts/<sha256>.txt`
  (plain text, not docket-owned JSON; the jail's HOME is the pod cache, so it is readable without a
  grant); the truncated result ends with `[full output: <path> — read it with read(path, offset,
  limit)]`; the condensation notice points at the artifact when one exists instead of inviting a
  re-run; retention follows the trace's. `read` must accept that path: check `toolbox.read`'s root
  containment first and, if it refuses, add the artifacts directory to the readable roots in the
  same card.
- **Non-goals:** lifecycle condensation (deferred); indexing or search over artifacts; a new tool.
- **Spec:** `session-history.spec.md` (1.10.0 → 1.11.0, the notice); `agent-loop.spec.md` (the
  artifact line in the tool-output section); `workspace-structure.spec.md` (the directory).
- **Change:** `agent/tools/builtins/toolbox.py` (write + marker, in the one place results are
  cut), `agent/session.py` (notice), `agent/loop_trace.py` (record the artifact path), retention
  in `observability/` where the trace's lives.
- **Acceptance:** a `bash` with 50 KB output under a 2,500 cap → the result carries the marker, the
  file exists with the full bytes, and a following `read(path, offset=2400, limit=50)` returns the
  bytes past the cut (oracle: `tests/integration/agent/test_tool_artifacts.py`, jailed variant in
  `tests/integration/sandbox/`); the notice for a condensed result names the path; the e2e jailed
  journey stays green.
- **Contention:** continues P52-2's files.

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
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 40 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close.
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
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`;
Phases 46-47 run on `plan/phase-46-structure` until the maintainer integrates it). `main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P52-5 acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-8, the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **The serial no-sandbox run fails 7 tests that pass alone** (`scripts/maint/pytest-without-sandbox.sh
  -q`, found at the Phase 48 close; the same 7 at `d6b16df5` in a clean worktree, so older than
  Phase 48). They are `test_step__step_env.py::TestShape::test_a_secret_store_name_is_refused`, two
  in `tests/integration/hops/test_diff_probe.py::TestHopDiffProbeUnit` and four in
  `tests/integration/sandbox/test_task_credentials.py`; the parallel default suite never orders
  them that way. Hypothesis: an earlier test in the same process leaves a process-wide binding
  changed (a bound port, the credential catalog or the secret-store names). Next: bisect the
  serial order with `-p no:randomly` and the file list before the first failure. Trigger: now,
  since the `no-sandbox` CI job runs this script serially once the branch is pushed.

- **Timing flakes seen once each:** `test_kernel_adoption.py` over its 2 s guard ceiling,
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.

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

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
