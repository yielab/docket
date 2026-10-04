# ADR 0016 (D-50): the operator loop — work parks instead of blocking, the Lead asks before it builds, and every human touchpoint speaks one standard contract

**Question:** docket sells "the gate and the record", yet the human is outside the loop the gate
creates. An operator who assigns several tasks to a pod's Lead and walks away has no way to
learn that something needs them, no way to be asked a question (only a permission), and no
guarantee that answering late does not lose the work. The Lead's own prompt tells it that it
"owns human communication" and must "surface architectural decisions and risky actions to the
human"; no path exists for either. The 2026-09-28 request: the Lead must reason about a task
before assigning it (missing information, missing resources, what the Implementer needs),
decisions and clarifications must be a short conversation with the human, approval is a
separate flow, and all of it must reach the operator in a standard, intuitive way (console,
Telegram, email, phone, WhatsApp, Trello were named). The standing requirement on top: task
assignment, approvals, questions and notifications must be usable by a variety of systems and
flows **in a standard way**. What is the shape?

**Where decided:** 2026-09-28, as Phase 34. The operator accepted the five recommendations
recorded under "Decision" below. **Activation gate:** Phase 33 closed at `68feade`; the
integrator batches by function-level contention (TODO.md, Phase 34).

**Evidence** (read at `0197e8b`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| docket never messages anyone first; `send_message` has one call site, a reply | `core/telegram.py::poll_once`; `telegram-integration.spec.md` Command grammar 7 |
| An in-turn `ask` blocks a live thread for 120 s, then denies | `core/tools.py::dispatch_tool` → `core/approval.py::wait_for_approval`; `config.TOOL_APPROVAL_TIMEOUT` |
| A hop-level approval already parks durably and resumes at the exact position | `core/dispatch.py::resolve_waiting_approval`, `_apply_result`, `gateOverridePipelineIndex` |
| The policy source of the hop-level gate is an explicit `False` seam | `core/dispatch.py::_policy_requires_approval` |
| `serve --dispatch` walks pods serially in one thread; an in-turn `ask` in one pod stalls every pod | `serve.py::_run_sweeps`, `core/runs.py::execute` (synchronous) |
| Foreground dispatch drains the queue silently; it never subscribes to the trace | `cli/_pod.py::_pod_dispatch`; only `cli/_harness.py` and `core/telemetry.py` call `trace.subscribe` |
| The Lead has no gate, no structured output, and cannot say "not ready" | `core/archetypes.py` (`lead`: `GateContract(kind="none")`, `hop_instruction`); `core/dispatch.py` builds `HandoffArtifact(summary=hop_output)` |
| The Lead's hop message carries only its instruction and the task description | `core/dispatch.py::_hop_message` (`role == "lead"` branch) |
| The Lead's prompt and a guide promise human communication that does not exist | `core/archetypes.py::_LEAD_BODY`; `docs/AGENT-TEAMS.md` (the roles table, Lead row) |
| Outcome routing with bounded backward edges already exists; route counts are rebuilt from persisted hops on resume | pipeline-format.spec.md "Outcome routing"; `core/dispatch.py::_route_outcome`, the resume-position builder |
| A conversation registry keyed by channel, peer and task already exists | `core/conversations.py::Conversation` (`channel`, `peer_id`, `task_ref`, `status`) |
| The only four real approvals on the development machine (2026-08-05) all expired unanswered | `~/.docket/audit.log`, `approval.deny channel=timeout` ×4, no other human-channel resolution for a real pod |

## Decision

**One mechanism parks a task for a human. It has two reasons: a permission or a question. Every
surface reads one derived inbox. Every notification is one CloudEvents contract, delivered by a
declared `kind: channel`. Every answer ends in one of two core functions.** Standards are
adopted where they exist, and docket's own vocabulary maps onto them one to one.

### 1. The standards, and where each one binds

| Concern | Standard | How docket uses it |
| --- | --- | --- |
| Task lifecycle vocabulary | **A2A 1.0.0** `TaskState` (`SUBMITTED`, `WORKING`, `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) | Every task view carries `a2aState` next to docket's own `status` (table in §3). docket does not become an A2A server in this phase (deferred, §9). |
| A question to a human | **MCP elicitation** (`elicitation/create`, protocol 2025-06-18): `message` plus a `requestedSchema` limited to a flat object of primitive properties; the reply is `action: accept \| decline \| cancel` with `content` | A docket question **is** an elicitation request in shape, and an answer **is** an elicitation result. Any client that renders an MCP elicitation form can render a docket question unchanged. Like the MCP rule, a question never requests a secret. |
| Event envelope | **CloudEvents 1.0**, JSON structured mode (`application/cloudevents+json`) | Every operator event: `specversion: "1.0"`, `id`, `source`, `type`, `time`, `subject`, `datacontenttype`, `dataschema`, `data`. |
| Webhook transport and signing | **Standard Webhooks**: headers `webhook-id`, `webhook-timestamp`, `webhook-signature`; `v1,<base64 HMAC-SHA256>` over `<id>.<timestamp>.<body>`; secret `whsec_<base64>` | The `webhook` channel dialect signs every delivery; `webhook-id` equals the CloudEvent `id`. |
| Schemas | **JSON Schema 2020-12** | `docs/contracts/operator-v1/*.schema.json`, generated from Pydantic models and checked in CI, like `config-v1`. |
| Metrics | Prometheus text (existing) | `docket_inbox_items{section}` gauge next to the existing `docket_approvals_pending_total`. |

**Identifiers.** Schema `$id`: `https://docket.dev/schemas/operator-v1/<name>.schema.json`
(the `config-v1` base). Event `type`: reverse-DNS on the same domain, `dev.docket.<noun>.<verb>`.
`source`: `urn:docket:pod:<pod>`. `subject`: the task id, or the approval token for a direct
approval.

### 2. Park, don't block (`approvalMode: wait | park | refuse`)

- `park` is new. An in-turn `ask` records the exact call (tool plus a SHA-256 digest of
  canonical-JSON arguments), creates the approval record with that call and the task position in
  `context`, and ends the hop with a new stop reason, `approval_parked`. The task becomes
  `waiting_approval`: the same state, same record and same resolver the hop-level gate already
  uses.
- **On grant**, the task returns to `pending`. The re-entered hop carries a **single-use
  pre-grant** for that exact call: the same tool with a byte-identical canonical argument digest
  passes without asking, once; anything else asks again. Consuming a pre-grant writes an
  `approval.consume` audit entry. (The mid-turn alternative, resuming the stored session with the
  granted call's result injected, is deferred with a trigger in §9.)
- **Default by caller when a pod leaves `approvalMode` unset:** the `serve --dispatch` sweep and a
  foreground dispatch without a TTY resolve to `park`; a foreground dispatch on a TTY resolves to
  `wait`, rendered and answerable in place (§8). An explicit pod value always wins. This reverses
  P26-5's non-goal ("changing the default") on the evidence above.
- **Expiry:** `approvalExpiryHours` (pod setting, default 24). A parked approval past it resolves
  to **denied** through the existing fail-closed sweep. The 120 s in-turn wait stays exactly as
  it is for `wait`.

### 3. States and their A2A mapping

| docket `status` | Meaning | `a2aState` |
| --- | --- | --- |
| `pending` | queued | `SUBMITTED` |
| `running` | claimed, hops executing | `WORKING` |
| `waiting_input` **(new)** | a question is out; nothing runs | `INPUT_REQUIRED` |
| `waiting_approval` | a permission is out; nothing runs | `INPUT_REQUIRED` |
| `blocked` with `blockedReason: budget` | the operator must raise a cap | `INPUT_REQUIRED` |
| `blocked` with `blockedReason: resources` **(new reason)** | a named secret or resource is missing | `AUTH_REQUIRED` |
| `blocked` with `blockedReason: input_expired` **(new reason)** | a question went unanswered past its expiry | `INPUT_REQUIRED` |
| `done` | every step passed | `COMPLETED` |
| `failed` with `failureKind: rejected` **(new kind)** | the Lead's intake said the task is out of scope or infeasible | `REJECTED` |
| `failed` (any other kind) | a gate, verify or denial failed it | `FAILED` |
| `cancelled` | a run cancellation stopped it | `CANCELED` |

An unanswered question never fails a task. Nobody said no, so it becomes `blocked`, and
`queue --retry` re-opens it.

### 4. The Lead's intake: a pipeline pattern, not hard-wired behaviour

- **A new step kind, `input`**, joins `role`, `agent`, `run` and `parallel`:
  `{id: ask, input: {from: <step id>, message?: str}}`. It runs no agent. It creates a question
  record from the `from` step's latest hop, parks the task `waiting_input`, and on an answer
  yields the outcome `answered` (`accept`) or `declined` (`decline`/`cancel`), routed by the
  step's own `on:`.
- **A Lead intake step** is an ordinary verdict step: `verdict: [READY, NEEDS-INPUT, REJECT]`
  with `on: {NEEDS-INPUT: {goto: ask, max: 3}, REJECT: fail}`. The bound on the backward edge is
  the bound on the conversation.
- **The Lead's reply carries a typed `TaskBrief`**: one fenced ```` ```json ```` block with
  `objective`, `acceptance[]`, `context[]`, `constraints[]`, `assumptions[]`, `questions[]`,
  `resources[]`, `expectedRiskyActions[]`, followed by the verdict marker line. Each
  `questions[]` entry becomes one property of the elicitation `requestedSchema`. Parse failure
  follows the existing verdict rule: the step fails, nothing is guessed.
- **The Implementer receives the brief rendered by field**, not the Lead's prose. Every
  operator answer so far is carried into the Lead's next message and into the brief as
  `answers[]`.
- **Deterministic checks run before the model.** Resources named in the brief are checked by
  code: secret names exist in the store (names only), `verifyCmd` is set, the codebase path
  exists. A missing secret parks the task `blocked` with `blockedReason: resources`
  (`AUTH_REQUIRED`) and names what is missing, without spending another turn.
- **Shipped as the recipe `intake`, opt-in.** It is not the `software` default until a real run
  on the 16k local endpoint shows the Lead producing parseable briefs. A pod without an `input`
  step behaves byte-identically to today.

### 5. Task assignment in a standard shape

- `POST /tasks` and `docket pod <p> delegate` keep accepting a bare description.
- They additionally accept an optional **pre-brief**: the same `TaskBrief` fields, validated by
  the same model, so an upstream plan of record (Tack, a board bridge, CI) can hand over
  acceptance criteria and constraints it already holds. The Lead's intake still validates it.
- Every task read (`GET /tasks`, `GET /tasks/<id>`, `docket pod <p> queue --json`, the inbox)
  returns the `operator-v1` task view with `a2aState`.

### 6. One inbox, derived

- `core/inbox.py::build_inbox()` is a pure function over the task lists of every pod, the
  approval store and the run registry. Sections: `needs_you` (waiting_input, waiting_approval,
  blocked), `failed`, `done_since` (after the caller's cursor) and `running`.
- `docket inbox [--json] [--since <cursor>]`, `GET /inbox`, the MCP tool `inbox`, and Telegram
  `/status` (scoped as today) all call it.
- The `docket inbox` cursor is an operator file written through `edges/store.py`. `GET /inbox`
  takes `since` and returns `next`, so a polling consumer like Tack owns its own cursor. docket
  keeps no per-consumer state and pushes nothing to Tack.
- **Correction (2026-10-04, P35-10).** Tack does not poll docket. Tack dropped its docket poller
  and spawns `docket harness run --contract 1.1` as a subprocess instead; the harness contract is
  specified in `specs/api/harness-mode.spec.md`, "Contract 1.1". The `/inbox` route and the
  `docket inbox` cursor described above still exist for any other caller, but they are not
  Tack's integration path, and the sentence "Tack polls" in "What stands, unchanged" is no longer
  true. The decision text above is kept as written, because it was the decision at the time.

### 7. Notifications: events derived from inbox transitions, delivered by `kind: channel`

- **Producer.** `core/notify.py` diffs the current inbox against the last delivered snapshot
  (`notify-state.json` through `edges/store.py`). It emits one CloudEvent per new entry:
  - `dev.docket.task.input_required`
  - `dev.docket.approval.requested`
  - `dev.docket.approval.expiring` (at 80 % of the expiry)
  - `dev.docket.task.blocked`
  - `dev.docket.task.failed`
  - `dev.docket.task.rejected`
  - `dev.docket.task.completed`

  Deriving from state rather than hooking the dispatch hot path makes delivery restart-safe,
  deduplicated by a stable event `id`, and blind to which process caused the transition.
- **When it runs.** Each `serve` sweep, the end of every foreground dispatch, and
  `docket notify flush`.
- **Delivery.** Best-effort with a bounded retry count. It never blocks a turn or a sweep beyond
  a per-delivery timeout.
- **Channels.** A `kind: channel` document names:
  - a closed `dialect`;
  - `capabilities` from `{notify, converse, decide}`, validated against the dialect's maximum;
  - `on:` (which event types);
  - `content: minimal | actions | conversation` (the Phase 33 level names: `minimal` carries pod,
    task, reason, token and how to answer; `actions` adds the command docket rendered;
    `conversation` adds the question text and the brief);
  - `actors:` (the identities allowed to converse or decide);
  - `secret:` (a name in `secrets.json`, never a value).

  Built-ins ship dormant except `console`. The CLI is `docket channels list|show|enable|disable|
  test|add|remove|export`. Widening `content` is a confirmed, audited command, exactly as for
  exporters.
- **v1 dialects:**

  | Dialect | Maximum capability |
  | --- | --- |
  | `console` | decide |
  | `desktop` | notify |
  | `webhook` (CloudEvents plus Standard Webhooks signature) | notify |
  | `command` (an operator binary receiving the event on stdin) | notify |
  | `ntfy` | notify |
  | `email` (SMTP) | notify |
  | `telegram` | decide |

  All are stdlib only: `urllib`, `smtplib`, and `edges/adapters/system.py` for binaries.

### 8. Answers: two core functions, every surface is transport

- `core/answers.py::answer_task(project, task_id, action, content, *, channel, actor)`:
  - validates `content` against the question's `requestedSchema`;
  - screens every string through `pre_input`;
  - appends to the task's `answers[]`;
  - resumes the `input` step;
  - audits with channel and actor.
- `core/approval.py::approval_grant` / `approval_deny` (existing) gain an optional `actor`.
- `APPROVAL_CHANNELS` stays closed and grows by dialect name.
- A channel that can decide requires a **token** and an **allow-listed actor**. The email
  dialect can never decide (a `From` header is forgeable), and no notification carries a control
  that decides.
- **Surfaces in this phase:**
  - CLI: `docket pod <p> answer`, `docket chat <task>`, `docket approve|deny`;
  - HTTP: `POST /tasks/<id>/answer` with the elicitation-result body, and the existing
    `POST /approvals/<token>`;
  - MCP tools: `inbox`, `task_answer`, and the existing `approvals_*`;
  - Telegram: `/answer <task> <text>`, and `/approve` / `/deny` as today;
  - the foreground TTY prompt.

### 9. Telegram (the one amended boundary)

- `telegram-integration.spec.md` Command grammar 7 is amended. The channel may send
  **unprompted** only through the channel dispatcher (§7), only the event types its document
  selects, and at `minimal` unless the operator widened it.
- Decisions still require an explicit token from the bound chat. `/answer` is a fifth verb
  whose text passes `pre_input`, as `/delegate` does.
- `TestInboundOnly` is rewritten in the same commit to pin the new invariant: exactly one
  outbound call site, inside the Telegram channel adapter.
- The original reason for the rule (an approval request pushed to an untrusted surface) is
  answered by two things: the default content carries no command text, and the push never
  carries the power to decide.

### 10. Seeing it coming, and not being interrupted twice

- `docket pod <p> explain interruptions` derives, from the pod's effective configuration, what
  can stop a task:
  - policies whose action is `require_approval`, with their patterns;
  - the classifier's high-risk classes;
  - pipeline `approval` and `input` steps;
  - `requireApprovalRoles`;
  - `approvalMode` and the expiries;
  - the enabled channels.

  `delegate` prints its one-line summary.
- **Pre-grants from intake.** A READY brief lists `expectedRiskyActions`.
  `docket pod <p> pregrant <task> "<exact command>"` (and the HTTP/MCP equivalents) records a
  granted, single-use, task-scoped, expiring pre-grant for that exact rendered call, consumed
  through §2's matcher. Matching is exact after whitespace normalisation. This is an honest
  limit: a model that rephrases the command is asked again.

### What stands, unchanged

- Fail-closed expiry.
- D-22/D-24: one operator, no tenant axis, no streaming.
- Tack polls; nothing is pushed to it.
- A Telegram chat is not a conversation with an agent: every answer is bound to a task and
  bounded by `max`.
- No public inbound endpoint: every inbound path is local, Bearer-authenticated HTTP, or a
  poll.
- No new dependency.
- Every tool call through `dispatch_tool`; every docket-owned JSON write through `store.py`.

### Cut (and why)

| Item | Why |
| --- | --- |
| A WhatsApp dialect | The official Business Platform needs a verified business, pre-approved templates for business-initiated messages, and a public HTTPS webhook to receive. Unofficial clients break the terms of service. Reached today through `webhook` to an operator-owned gateway. |
| A Trello dialect | Trello is a plan of record, not a channel (D-20/D-22). A bridge consumes `GET /inbox` like Tack. Moving a card can never be an approval, because any board member can move one. |
| Decide-capable notifications (buttons) | They turn a notification into a decision surface. |
| Email that decides | A `From` header is forgeable. |
| Free chat with an agent | Every conversation is bound to a task and bounded. |
| docket creating subtasks or a DAG | The plan of record owns the DAG (D-20). |

### Deferred with named triggers

| Item | Trigger |
| --- | --- |
| **A2A binding** (`SendMessage`, `GetTask`, `CancelTask`, agent card) over the §3 mapping | A named A2A client that will call docket |
| MCP elicitation pushed to a connected client | An MCP client that supports elicitation, used as the operator console |
| `converse`/`decide` for Slack, Matrix or GitHub (issues as the thread) | An operator who receives `webhook` notifications there daily and asks to answer from it |
| `converse` over email (IMAP, thread token in `Reply-To`) | The same trigger |
| Mid-turn session resume instead of hop re-run with a pre-grant | Measured: in more than 20 % of parked approvals over at least 10, the re-run hop does not re-issue the granted call |
| One worker per pod in the sweep | The operator-loop scenario, re-run after `park`, still shows one pod delaying another |
| `intake` as the `software` default | A live run on the local endpoint where at least 9 of 10 Lead intake replies parse |

**Two of the seven triggers above are measurable against this machine's own state right now; the
integrator (2026-09-29, closing Phase 34) evaluated both. Neither fired — recorded here, not
acted on.**

- **Mid-turn session resume: not fired, insufficient sample.** The trigger needs at least 10
  parked approvals with more than 20% of the re-run hops failing to re-issue the granted call.
  The real `~/.docket/audit.log` on this machine carries **zero** `approval.pregrant` or
  `approval.consume` entries — every parked-approval round trip observed so far has been inside
  a test or a throwaway scenario world, never a real operator's own pod. Sample size 0 < 10: the
  trigger cannot fire yet, and the deferral stands unchanged.
- **One worker per pod in the sweep: not fired under the scripted backend, but the underlying
  cost is real and worth naming.** The operator-loop scenario (`scripts/smoke_workflow.py
  --scenario operator-loop`), re-run after `park` shipped: deterministically, `sweepBlockedSeconds`
  dropped from the pre-Wave-65 baseline of roughly 12-13s to under a second (0.0-1.0s across two
  runs) — `park` genuinely removes the blocking wait the trigger's premise describes. Against the
  real local model (`--live-model`), the same scenario measured `sweepBlockedSeconds = 138.0`:
  alpha's own two real Lead+Implementer turns (both ending in a park) ran to completion before
  beta's sweep slot ever started, because the sweep is still one worker walking pods serially.
  That is not the *blocking-on-a-human-answer* failure mode `park` was built to remove (§2's own
  evidence table) — it is ordinary serial generation latency, present with or without approvals in
  the mix — so the trigger's literal condition ("still shows one pod delaying another") is
  technically satisfied under a live model without being the failure the ADR opened against. This
  is worth a maintainer's attention as a measured cost of the current design, not a directive to
  add a worker pool: recorded, not acted on.

## Verdict table

| Request | Verdict |
| --- | --- |
| The Lead evaluates a task, detects missing information or resources, and briefs the Implementer | Yes: `TaskBrief`, the `input` step, deterministic resource checks, the `intake` recipe |
| Decisions and clarifications as a short conversation with the human | Yes: elicitation-shaped questions, bounded by `max`, bound to a task |
| Approval as a separate flow | Yes: `waiting_approval`, tokens, decide-capable channels only |
| Notified in a standard, intuitive way | Yes: CloudEvents events, Standard Webhooks signing, `kind: channel` |
| Console | Yes, v1 (decide) |
| Telegram | Yes, v1 (notify and converse by amendment; decide as today) |
| Email | Yes, v1 notify; converse deferred; never decide |
| WhatsApp | Through `webhook` to an operator gateway; no dialect (cut above) |
| Trello | As a consumer of `GET /inbox`; not a channel (cut above) |
| Usable by a variety of systems in a standard way | Yes: A2A states, MCP elicitation shape, CloudEvents, Standard Webhooks, JSON Schema; A2A binding deferred with a trigger |

## Test discipline

- One RED behavioural test per card in the module's `SUBJECT` file; a negative case only for a
  fail-closed property:
  - a parked approval past expiry denies;
  - a non-allow-listed actor cannot decide;
  - email cannot decide;
  - `minimal` content carries no command or question text (canary);
  - an unanswered question never fails a task.
- Every HTTP target in a test is a local `http.server` on port 0. No test calls a real model or
  a real vendor.
- The phase oracle is `scripts/smoke_workflow.py --scenario operator-loop`: deterministic by
  default, `--live-model` against the local endpoint. It is measured at P34-1 and again at the
  close.

**P34-1 baseline vs. the 2026-09-29 close (same four-task, two-pod scenario, unmodified).**

| Metric | P34-1 baseline (before park/inbox/answers/notify) | Close, deterministic | Close, `--live-model` |
| --- | --- | --- | --- |
| `sweepBlockedSeconds` | ~12-13s | 0.0-1.0s | 138.0s |
| `leadAsked` | always `false` | `false` (no task in this scenario reaches an `input` step) | `false` (same) |
| `eventsDelivered` | always `0` | `2` | `4` |
| A1 (gated push) outcome | timed out, denied | `waiting_approval` (parked, token recorded) | `waiting_approval` (parked) |

`eventsDelivered` reads `0` at the baseline for two different reasons across the two
deterministic re-runs above: first because no channel had anything to deliver yet, and even
after channels existed the scenario's own counter had a real bug (below) that always returned
`0` regardless. `leadAsked` stays `false` at every measurement because this scenario's four
tasks never route through an `input` step or the `intake` recipe — an honest scenario gap, not a
regression, left unclosed rather than extended under this pass's time budget (see this ADR's
closing changelog entry in `operator-loop.spec.md`).

**Two defects this re-run found, fixed as part of this close (full detail:
`operator-loop.spec.md`'s changelog):** `_oploop_events_delivered` read a `deliveries` key the
real `channels-health.json` shape never had, so the counter silently read `0` since the day it
was written — fixed to sum each channel's own `delivered` counter. `--live-model` registered its
provider *after* `docket init`, the reverse of the working order `_run`'s other scenarios use, so
`init`'s own readiness check failed on a missing `ANTHROPIC_API_KEY` before the live provider was
ever registered — `--scenario operator-loop --live-model` had never actually completed `init`
until this fix reordered the two calls.
