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

## Not decided here

- The A2A facade (P51-7) and the per-task `autonomy` level with the `kind: autonomy` document
  (P51-8) are on the board but wait for the maintainer's answers on design decisions 6 and 7.
- Retirement of the old shapes (P51-9) waits for Tack to consume `escalations[]` and
  `POST /escalations`.
