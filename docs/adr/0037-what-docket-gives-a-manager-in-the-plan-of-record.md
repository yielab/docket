# ADR 0037 (D-79): what docket gives a manager in the plan of record

**Status:** Accepted (2026-11-01, the maintainer). Phase 57 in `TODO.md` carries it out.

**Question:** Tack's ADR 0034 (accepted 2026-11-01) makes a "manager" a Tack profile that reads every
team through Tack's board. It asks docket for six things, all pulls and all additive: the hop a task
is running, a cursor over every task a pod holds, pod memory over HTTP, a task that continues
turn by turn, a read-only control plane, and a pod MCP server reachable from a lights-out pod. Which
of them fit docket's ADRs as asked, which need another shape, and what is the smallest structure
that carries each one?

**Where decided:** 2026-11-01. The scoped request is Tack's ADR 0034, "What this asks of docket".
The measurements below were read on `develop` at `00e2b25d`.

## What the code says today

- **No process knows which hop is running.** The `hop_started` event (`hops/application/compose.py`,
  `_compose_hop`) carries step, role, member, model and cycle. The rework counter lives only in the
  dispatch run's `UnitContext`. The HTTP server can be another process. So the fact has to be
  written to the task record.
- **Tasks have no change marker:** no `updated_at`, no sequence. Every write is one locked
  `read_modify_write` (`tasks/application/json_store.py` over `platform/store.py`). The only
  monotonic integer in docket is the escalation `seq`.
- **Memory statuses are `accepted | pending | refused`** (`teams/memory.py`). "Approved" means
  `accepted`. The CLI (`docket pod memory list --json`) prints a bare array.
- **One serve token, no scope.** `interfaces/http/auth.py::authorize` accepts it on every
  authenticated route. The MCP `queue` tool takes `retry_task_id`, so the tool named `queue` writes.
- **`waiting_input` exists**, and so does the machinery a continuation needs:
  - parking on an escalation, and `resolve` re-queueing the task;
  - replaying a `parked` hop at its own index;
  - a note injected into the re-run step (`consult_note`);
  - turn history kept per (member, pod, task, step) and compacted to a budget.

  What is missing is an outcome that parks a hop that succeeded.
- **A jailed stdio MCP server cannot reach loopback under network `none`** (read from the code;
  P57-6 pins it with a test):
  - `agent/tools/mcp_client.py::_jailed_command` wraps the server with the hop's own
    `launch.network`;
  - Landlock ABI 4 handles TCP connect with no allow rule (`sandbox/landlock.py:128`);
  - seccomp refuses `socket(AF_INET|AF_INET6)` (`landlock.py:161`);
  - lights-out requires network `none` (`hops/gates/profile.py:50-65`).
- **A process docket starts outside the jail cannot be held to a host list.** A declared
  service's `hosts` perimeter works because docket's own Python makes the call
  (`platform/service_http.py::_connector`), not a child process.

## Decision

The HTTP API stays version **6**. Everything below is additive. A client probes for it through one
new list, `features`, on `GET /status.json` and `GET /health`. A name joins the list in the commit
that makes the feature work, never before.

1. **`current` on a running task** (`feature: taskCurrent`). `TaskRecord` gains
   `current: {stepId, role, member, model, startedAt, cycle}`. It is absent, not null, when unset.
   - The hop writes it where it emits `hop_started` and clears it where it emits `hop_finished`.
   - `tasks/domain/state.py::decide` drops it on every move out of `running`. A task that dies
     mid-hop therefore never shows a stale `current`.
   - `model` is the planned model, as on `hop_started`.
   - `cycle` is the rework count, as on `hop_started`.
   - The field reaches both `GET /tasks/<pod>` and `GET /tasks/<pod>/<id>` through the one
     serializer they share. No route changes.

2. **A cursor over every task a pod holds** (`feature: taskCursor`).
   - **The counter.** The task file keeps a counter, and every task carries `rev`. Inside the store's
     locked `read_modify_write`, each task whose content changed (or that is new) gets the next
     value. The stamp sits at that one place, so no writer can miss it: http, mcp, a2a, routine,
     telegram, cli, the sweep or the dispatcher.
   - **The route.** `GET /tasks/<pod>?updatedSince=<cursor>` returns
     `{"tasks": [...], "next": "<cursor>"}`:
     - the tasks with `rev` greater than the cursor, in `rev` order;
     - each task with its `channel` and `externalRef` (already on the record);
     - `next` is the highest `rev` returned, or the cursor itself when nothing changed;
     - `updatedSince=0` starts from the beginning.
   - **The cursor.** It is opaque to the client: a decimal integer today.
   - **How it differs from the traces cursor:**
     - It is an integer, not `<ts>:<n>`. A counter stamped under the write lock is exactly-once
       without the traces cursor's one-second hold-back.
     - A task is state, not an event. A task changed twice between two polls appears once, in its
       latest state.
   - **Combining.** `status` and `externalRef` still filter. Combined with `updatedSince`, they
     filter the changed set.

3. **Pod memory, read only** (`feature: podMemory`). `GET /pods/<pod>/memory` returns
   `{"entries": [...]}` behind the serve token:
   - only the `accepted` entries, oldest first;
   - each element is exactly an element of `docket pod memory list --json`;
   - the object wrapper is the one every HTTP route uses; the CLI's bare array is a CLI choice;
   - an unknown pod answers 404.

4. **A task that continues is an escalation of a new kind, `turn`** (`feature: conversation`). It is
   not a new verb.
   - **Why not `/messages`.** ADR 0032 decided one record and one verb, `resolve`, for every pause.
     ADR 0016 §8 decided that every answer ends in a core function.
     `POST /tasks/<pod>/<id>/messages` would be a second answer verb, so docket does not add it.
   - **Creating one.** `POST /tasks/<pod>` accepts `conversation: {maxTurns}`.
     - `maxTurns` is required and is an integer from 1 to 20. ADR 0016 forbids an unbounded chat.
     - The task's pipeline must have exactly one step. Otherwise the request is refused with 400,
       code `conversation_needs_one_step`.
   - **On the wire.** The task carries `conversation: {maxTurns, turns}`. `turns` is the count of the
     step's finished hops; it is computed, not stored.
   - **After each turn.** A turn is one hop of that step, with its own `hop_finished` and `usage`.
     When the hop succeeds and `turns < maxTurns`:
     - the hop is recorded `parked`, so replay re-enters the same step;
     - an escalation of kind `turn` opens. Its `message` is the turn's answer. Its options are
       `reply` (content `{text}`) and `close`;
     - the task moves to `waiting_input` (A2A `INPUT_REQUIRED`).

     The A2A `INPUT_REQUIRED` data part already carries the pending escalation, and the answer
     with it.
   - **The operator replies** through the existing routes:
     - `POST /escalations/<id> {"optionId": "reply", "content": {"text": ...}, "actor": ...}`;
     - or A2A `message/send` naming the task.

     `resolve` screens the content as it does today. The task returns to `pending`. The re-run step
     loads its earlier turns from the step's history and gets the reply as its note, through the
     path `consult_note` already uses.
   - **How it ends.**
     - On `optionId: "close"`, or on cancel, the task is `done` (a cancel stays `cancelled`).
     - On the turn that reaches `maxTurns`, the task is `done` and no escalation opens.
     - When the task's `maxTokens` runs out after at least one turn, the task is `done` instead of
       failing with `budget`.
     - When a `turn` escalation expires (the pod's `approvalExpiryHours`), the task is `done`:
       nobody spoke, so the conversation is over.
   - **Refusals.** Resolving a `turn` escalation that is no longer pending answers 409 with
     `code: escalation_not_pending`. `_send_refusal` starts passing a refusal's code to the wire,
     which the cancel route already does by hand.

5. **A read-only control plane** (`feature: readScope` for the HTTP half).
   - **HTTP.**
     - `DOCKET_SERVE_READ_TOKEN`, when set, is a second bearer token that `GET` and `HEAD` accept.
     - On any `POST`, that token gets 403 with `code: read_scope`.
     - A missing or wrong token stays 401.
     - A read token equal to the serve token is refused at start.
   - **MCP.**
     - `docket start --mcp --read-only` registers seven tools: `status`, `pods`, `queue`, `runs`,
       `inbox`, `escalations` and `cost`.
     - `--read-only` without `--mcp` is refused.
     - So that `queue` is truly read-only, its `retry_task_id` moves to its own write tool,
       `retry`. The full server lists twelve tools.
     - `resolve` keeps checking no caller. The surface is the authorization, and a read-only
       server does not carry it.

6. **No `placement: host` for MCP servers.** This conflicts with **ADR 0024** (D-60):
   - Decision 1: one envelope where everything the project runs executes, stdio MCP servers
     included; the host runs only docket.
   - Decision 5: it deleted `isolate: false` on MCP servers. `placement: host` would bring that
     back under another name.

   It also conflicts with the maintainer's direction after Phase 55 to add no more MCP machinery.
   - **Why it cannot work.** An MCP server spawned in docket's process space is an ordinary child.
     It reaches everything docket reaches and holds its `env` secrets unjailed. Nothing in docket
     can hold it to a host list. Landlock's net rules match ports, not addresses.
   - **The shape that fits is already shipped (ADR 0036 decision 13).**
     - Declare Tack's HTTP API as a `kind: service` with `baseUrl: http://127.0.0.1:3210` and
       `hosts: ["127.0.0.1"]`.
     - The call runs in docket's process, inside the declared perimeter, governed by each
       operation's `access` (`read | send`). A `send` and a refusal are audited; a `read` is traced.
     - It works from a lights-out pod today.
   - **What P57-6 adds:** two tests and a sentence in the spec. One test pins the jailed-MCP
     loopback refusal. The other shows a lights-out pod calling a loopback service and being refused
     an unlisted host.

## Not decided here

- **A per-port perimeter** (`hosts: ["127.0.0.1:3210"]`). Today a listed host allows any port.
  - Trigger: a second loopback service on the same machine that one pod must not reach.
- **An in-process MCP client over streamable HTTP**, with the service perimeter.
  - Trigger: a Tack tool that a service operation cannot express, named with the request it
    needs.
- **Task deletion in the cursor.** No task-retention sweep deletes task records today, so the
  cursor has no tombstones.
  - Trigger: the first change that deletes a task record.

## Consequences

- Tack's fake docket and adapter follow this ADR and the card reports, not ADR 0034's message:
  - there is no `/messages` route;
  - the cursor is an integer;
  - memory comes wrapped in `entries`;
  - lights-out reaches Tack through a service.
- The operator contract (`operator-v2`) gains the escalation kind `turn`, a MINOR change. A
  consumer that switches on `kind` must accept the new value.
- The MCP tool list changes (`retry` is split out). Tack does not use docket's MCP, and docket
  keeps no compatibility (the 2026-10-30 rule).
