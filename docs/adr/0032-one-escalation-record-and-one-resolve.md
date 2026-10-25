# ADR 0032 (D-72): one escalation, one record, one resolve

**Question:** a docket task can stop to wait for someone outside it in five ways: a tool approval,
a consult, an `input` step, a gate, and a changed check. Each has its own field on the task, its
own trace event, its own answer verb and its own way of reaching the operator. No autonomy level
(`lights-out`, Tack's L3/L4/L5) says what happens to a question when nobody is there. What is the
one shape for "docket needs a decision from outside", and in what order does it replace the five?

**Where decided:** 2026-10-25, by the maintainer, after a live run of the basic scenario against
the local model failed 0/3 on a consult the pod could have answered itself, and a read of how a
question travels through `run`, `inbox`, `task show`, HTTP, MCP and Telegram. Phase 51 on
`TODO.md` is the card list.

## What was measured

- A consult with a recommendation parks the task and ends the turn, even on a pod declared
  `lights-out`; the profile has four requirements and none is about a pause.
- The task carries seven fields that all mean "what the outside told this task": `approvalToken`,
  `question`, `consultAnswer`, `answers`, `pregrants`, `taskGrants`, `gateOverridePipelineIndex`.
- The inbox is a scan of every task of every pod plus every approval, with seven callers, and
  Tack polls it every 2 s per attempt. It lost a consult's options once and no test pins the route.
- `docket run` renders an approval in place and renders nothing for a question; `task show`
  never prints the question; Telegram at the default content level omits the option ids.
- Three answer vocabularies (`grant|deny`, `accept|decline|cancel` plus an `optionId` in content,
  `approve|refuse`) and four surfaces that each map the same errors by hand.

## Decision

1. **One concept, `Escalation`.** A durable record per pause, written only by `platform/store.py`
   (the second typed record after the task, D-70), with a monotonic `seq`. It is the resumption
   token: the task lists escalation ids, and the seven fields become projections of the record,
   then are deleted (P51-9).
2. **One verb, `resolve(id, option_id, content, by, channel)`.** Every surface calls it; the old
   routes, tools and verbs become thin adapters, then go. Dispatch, not the answering thread,
   applies the continuation when it claims the task.
3. **One policy table, `whenNobody[kind]` in `person | recommendation | deny | fail`**, evaluated
   when the escalation is created and recorded on it. The first row ships alone as the pod
   setting `consultMode: park|decide` (P51-1) and `lights-out` requires `decide`.
4. **One event family and one render.** `escalation_*` events with one payload and a span whose
   duration is the wait; one renderer shared by `inbox`, `task show`, the progress view, Telegram
   and notifications; option ids always present.
5. **The name is `Escalation`.** `Decision` is taken by `kernel/gate.py`; `Pause` was the
   alternative.

## Approved with it

- **The A2A facade (P51-7):** the trigger ADR 0016 named, "a client that calls docket", is Tack.
  The facade is thin, over the escalation record, and approved on 2026-10-25.
- **The per-task level (P51-8):** `autonomy: L3|L4|L5` travels with the task on `POST /tasks`,
  narrows only, and the pod profile is the ceiling (`attended` up to L3, `lights-out` up to L5).
  The policy table is published as the `kind: autonomy` document that ROADMAP had deferred.

## Not decided here

- Nothing waits on Tack. Retiring the old shapes (P51-9) follows the per-task level (P51-8) and
  does not wait for Tack to consume `escalations[]` and `POST /escalations`: Tack adapts to docket
  and both belong to the maintainer, so the runner is updated alongside, not ahead of, the deletion.

## A2A binding

ADR 0016 deferred the A2A binding until a named client would call docket; Tack is that client
(approved above). The facade is `POST /a2a` (JSON-RPC 2.0: `message/send`, `tasks/get`,
`tasks/cancel`, `tasks/pushNotificationConfig/set|get`) and `GET /.well-known/agent.json`;
`specs/api/a2a-binding.spec.md` is the contract. It adds no state:

- A task is the queue's record and its state is `a2a_state` of it (ADR 0016 section 3).
- A task in `INPUT_REQUIRED` carries its pending escalation as a `data` part, built from the
  `EscalationView`: the MCP elicitation request (`message`, `requestedSchema`) and the
  operator-v1.1 fields (`kind`, `options`, `recommendation`) plus `escalationId`,
  `escalationKind`, `expiresAt`, `onExpiry`, `policy`.
- A `message/send` that names a task and carries a result `data` part
  `{action: accept|decline|cancel, content: {optionId?}}` calls `resolve`. `optionId` is lifted
  out of `content` by the facade, as the other surfaces do.
- A push config is a task-scoped `kind: channel` webhook document, so it is delivered by the
  machinery that already delivers notifications.

**Extension declaration.** The agent card lists one extension in `capabilities.extensions`, and
every escalation message lists it in `extensions`: the URI is the `$id` of the operator-v1.1
question schema (`https://docket.dev/schemas/operator-v1.1/question.schema.json`), whose fields
the data part reuses. It is not `required`: a client that ignores it still reads `message`,
`requestedSchema` and the text part and can answer with `accept` and an `optionId`.

**Decided with it.** The agent card requires the Bearer token (it names every pod; docket's public
routes are read-only status, metrics and health). The push body is the CloudEvent the webhook
dialect already sends, not an A2A `Task`; the client reads the state with `tasks/get`. A push
config with a `token` or `authentication` is refused, because a channel document stores credential
names and never values. The task-scoped channel is never deleted when its task ends; a later
sweep may remove it.
