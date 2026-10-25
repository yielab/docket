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

## ▶ PHASE 51 ACTIVE — one escalation: ask, resolve, decide (D-72, ADR 0032)

> Opened 2026-10-25 by the maintainer. The reasoning and the measurements are in
> [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md). P51-1 and P51-2 are ready;
> P51-3..P51-6 follow in wave order; P51-7 and P51-8 wait for the maintainer's answers on the A2A
> facade and the per-task level; P51-9 waits for a trigger.

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
| F | P51-9 | retirement; trigger: Tack consumes `escalations[]` and `POST /escalations` |

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

**Status:** TODO (needs P51-3, P51-4) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

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

**Status:** TODO (needs P51-5) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

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

**Status:** TODO (needs P51-5) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec + ADR

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

**Status:** TODO (needs P51-6) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

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

### P51-9 — retire the old shapes (trigger: Tack on `escalations[]` + `POST /escalations`)

**Status:** TODO (trigger) · **Size:** M · **Model:** Sonnet · **Kind:** deletion + spec

- **Goal:** delete the seven task fields (keep `escalations[]`), `ApprovalView` from `needsYou`,
  `POST /approvals/<token>`, `POST /tasks/<id>/answer`, MCP `approvals_*`/`task_answer`, the five
  old trace events, `resolve_waiting_approval` and `answer_task`; contract `operator-v2`;
  `gen_operator_schemas.py` regenerated (allowed: a contract bump, not a golden hide).
- **Acceptance:** suite green; `tests/architecture`; baselines only shrink; `metrics.py --check`;
  the e2e lane rewritten against the new shapes only; Tack's fixture capture script re-run by the
  Tack maintainer against this build (note in the handoff, not a docket test).

---

**Notes for Tack (not docket cards)**

- Pause the attempt clock while the task is `INPUT_REQUIRED`; the deadline is the escalation's
  `expiresAt`. Today the attempt timeout turns a legitimate L3 wait into `timeout`.
- Subscribe (`webhook` channel / A2A push) instead of polling `/inbox` every 2 s per attempt.
- Send `autonomy` per task from `level_for`; map `failureKind: needs_human` to "re-route at L3".
- After P51-7: one A2A client replaces `approval_question`, `held_approval_question`,
  `consult_question` and the task-view workaround.

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
      `validate-specs.sh`, `metrics.py --check`, the generated-docs checks and the real run: once, at
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
  over half") fired. Next: on a real run, measure which calls repeat before cutting anything.

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
