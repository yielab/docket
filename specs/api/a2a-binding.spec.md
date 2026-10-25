# A2A binding (JSON-RPC over HTTP) -- contract spec

**Version**: 1.1.0
**Status**: Implemented
**Last Updated**: 2026-10-25

## Purpose

This specification defines the A2A binding of docket: a thin facade that lets an A2A client
create a task, read its state, answer the escalation it waits on, cancel it and subscribe to its
changes, using the records docket already keeps. It adds no state of its own: a task is the task
queue's record, the state is `a2a_state` of that record (`operator-loop.spec.md` area 3), the
question a task waits on is its pending escalation (`operator-loop.spec.md` area 11), the answer
is `resolve` (area 10), and a push subscription is a `kind: channel` webhook document.

The operator routes (`operator-api.spec.md`) stay the door for an operator's script and the plan
of record; this binding is the door for a client that speaks A2A and wants to treat docket as an
agent.

## Scope

This specification covers:

- `POST /a2a`: JSON-RPC 2.0 with the methods `message/send`, `tasks/get`, `tasks/cancel`,
  `tasks/pushNotificationConfig/set` and `tasks/pushNotificationConfig/get`
- `GET /.well-known/agent.json`: the agent card
- The `Task` object, its `INPUT_REQUIRED` status message and the result `DataPart`
- The mapping from a docket refusal to a JSON-RPC error
- The push notification config as a task-scoped webhook channel

It does NOT cover:

- `message/stream`, `tasks/resubscribe`, `tasks/pushNotificationConfig/list` and `/delete`
  (answered `-32004`), the authenticated extended card, multi-part artifacts
- The operator routes and the escalation view -- `operator-api.spec.md`
- The state mapping, the escalation record, `resolve`, the channel catalog and webhook delivery
  -- `operator-loop.spec.md`
- Authentication beyond the Bearer token of `docket start`, tenants, quotas
  (`serve-read-api.spec.md`)

## Syntax

`POST /a2a` takes one JSON-RPC 2.0 request object and answers one response object. `401` (Bearer
token missing or wrong) and `413` (body over 1 MiB) are HTTP answers that come before the body is
read; every other outcome is `200` with a JSON-RPC response, `result` on success and `error`
(`{"code", "message", "data"?}`) on failure. A batch (a JSON array), a missing `jsonrpc: "2.0"`, a
missing `id` or a non-string `method` is `-32600`; a body that is not JSON is `-32700`; an unknown
method name is `-32601`.

State names are the `a2a_state` strings (`SUBMITTED`, `WORKING`, `INPUT_REQUIRED`,
`AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`); method, field and part names
follow the A2A JSON-RPC binding (`kind` discriminates `task`, `message`, `text`, `data`).

| Method | Params | Result |
|---|---|---|
| `message/send` | `{message, metadata?, configuration?}` | a `Task` |
| `tasks/get` | `{id}` | a `Task` |
| `tasks/cancel` | `{id}` | a `Task` |
| `tasks/pushNotificationConfig/set` | `{taskId, pushNotificationConfig}` | `{taskId, pushNotificationConfig}` |
| `tasks/pushNotificationConfig/get` | `{id}` | `{taskId, pushNotificationConfig}` |

The agent card is `GET /.well-known/agent.json` and requires the same Bearer token as every
other route (see "Agent card").

## Arguments

### `message/send`

`message` is an A2A `Message` (`{"kind": "message", "role": "user", "messageId": str, "parts":
[...], "taskId"?: str, "metadata"?: object}`).

- **No `message.taskId`: create a task.** The description is the `text` parts joined by a blank
  line; a message with no non-empty text part is `-32602`. The pod is `params.metadata.pod`, else
  `message.metadata.pod`, else the only pod when exactly one is provisioned; otherwise `-32602`
  naming the pods. `messageId` becomes the task's `idempotencyKey` (prefixed `a2a-`), so a
  retried send answers the task already created instead of a second one. The task is enqueued
  through the same function as `POST /tasks/<pod>` (channel `http`, so the `pre_input` policy
  screens the description), and a service running `--dispatch` starts its sweep. The result is
  the `Task` (state `SUBMITTED`). `configuration.pushNotificationConfig`, when present, is
  applied as `tasks/pushNotificationConfig/set` for the new task. `configuration.blocking` is
  ignored: the call never waits for the task.
- **With `message.taskId`: answer the task's escalation.** The message carries one `data` part
  `{"action": "accept"|"decline"|"cancel", "content"?: object, "escalationId"?: str}`. The
  escalation answered is the task's one pending escalation, or the one `escalationId` names
  among them. `content.optionId`, when given, is the option chosen and is removed from the
  content; the rest of `content` is the answer's content. The call is `resolve(escalation id,
  option, content, by="a2a", channel="a2a")` and the result is the `Task` as it then reads.
  `accept` needs an `optionId` unless the escalation offers only `decline`; `decline` and
  `cancel` choose the option `decline`, or `deny` for an approval, a gate and a changed check.
  `resolve` does not run the continuation: dispatch applies it when it claims the task, so the
  `Task` of the answer reads `SUBMITTED` (or `WORKING` once claimed) and ends `COMPLETED`.

### `tasks/get`, `tasks/cancel`

`id` is a task id. The pod is found by looking the id up in every provisioned pod; no match is
`-32001`. `tasks/cancel` is `cancel_task` with channel `a2a`; a task that
nothing holds (still `pending`, or terminal: nothing was cancelled) is `-32002`.

### `tasks/pushNotificationConfig/set`

`pushNotificationConfig` is `{"url": str, "id"?: str}`. `url` MUST be `http://` or `https://`.
`token` and `authentication` are refused with `-32602`: a channel document stores credential
*names*, never values, and the delivery is Standard Webhooks (unsigned here: no secret is
named). One config per task: `set` replaces it. `get` answers the stored config, or `-32602`
(`data.reason` `no_push_config`) when the task has none; an unknown task is `-32001`.

## Options

None. The binding has no flags; the pod's settings and the service's flags are those of the
operator routes.

## Output

### Task

```json
{"kind": "task", "id": "task-...", "contextId": "demo",
 "status": {"state": "INPUT_REQUIRED", "timestamp": "2026-10-25T10:00:00Z",
            "message": {"kind": "message", "role": "agent", "messageId": "esc-...",
                        "taskId": "task-...", "contextId": "demo",
                        "extensions": ["https://docket.dev/schemas/operator-v1.1/question.schema.json"],
                        "parts": [{"kind": "text", "text": "Which store?"},
                                  {"kind": "data", "data": {}}]}},
 "metadata": {"docket": {"pod": "demo", "status": "waiting_input"}}}
```

`id` is the docket task id and `contextId` its pod. `state` is `a2a_state` of the task record.
`timestamp` is the task's last update. `metadata.docket` is `{pod, status, externalRef?}`;
it never carries an approval token. A task with a `reason` (blocked, failed, rejected) has a
`status.message` with one `text` part, the reason. `status.message` of an `INPUT_REQUIRED` task
that has a pending escalation is the escalation message below.

### The escalation message

`messageId` is the escalation id. `extensions` lists the operator-v1.1 extension, declared by the
`$id` of `docs/contracts/operator-v1.1/question.schema.json`
(`https://docket.dev/schemas/operator-v1.1/question.schema.json`). The `text` part is the
escalation `prompt`. The `data` part is the MCP elicitation request and the extension fields:

| Field | Meaning |
|---|---|
| `message` | the prompt (the MCP elicitation `message`) |
| `requestedSchema` | the MCP elicitation `requestedSchema` the answer's `content` follows. It is the escalation's own schema, plus `optionId` (a string with `enum` the offered options other than `decline`, required when there are any) and, for an approval, a `reason` string |
| `kind` | the operator-v1.1 question kind: `approval` for an approval, gate and changed check; `decision` when options other than `decline` are offered; else `clarification` |
| `options`, `recommendation` | as in the operator-v1.1 question |
| `escalationId`, `escalationKind` | the record's id and its kind (`approval`, `consult`, `input`, `gate`, `check_changed`) |
| `expiresAt`, `onExpiry`, `policy` | as in the escalation view |

The data part is built from the `EscalationView` of the pending escalation and carries nothing
the view does not: no approval token, no resolve URL.

### Agent card

`GET /.well-known/agent.json` answers an A2A `AgentCard`: `name` `docket`, `description`,
`url` (the absolute `/a2a` URL, from the request's `Host`), `version` (the docket version),
`protocolVersion`, `preferredTransport` `JSONRPC`, `capabilities`
`{"streaming": false, "pushNotifications": true, "stateTransitionHistory": false,
"extensions": [{"uri": <the extension `$id`>, "required": false}]}`, `defaultInputModes`
`["text/plain"]`, `defaultOutputModes` `["text/plain", "application/json"]`, `skills` (one per
provisioned pod: `id` and `name` the pod, `description`, `tags` `[]`), and `securitySchemes`
`{"bearer": {"type": "http", "scheme": "bearer"}}` with `security` `[{"bearer": []}]`.

The card requires the Bearer token. A2A lets a card be public, but docket's only public routes are
the read-only status, metrics and health ones, and a card names every pod of the machine; a
client that is allowed to call `/a2a` holds the token and reads the card with it.

### Push notification

A config is stored as the channel `a2a-<task id>`: dialect `webhook`, enabled, capabilities
`[notify]`, `on` `[needs_you, task.completed, task.failed, task.rejected]`, content `minimal`,
`config` `{url, scopeTask, scopePod}`. A channel whose `config` has `scopeTask` receives only the
events of that task (and its approvals); every other channel is unchanged. The request body is
the CloudEvent of `operator-loop.spec.md` (`Content-Type: application/cloudevents+json`), not an
A2A `Task`: `data.taskId` and `data.pod` name the task, and the client reads its state with
`tasks/get`. `SUBMITTED` and `WORKING` do not push. The channel appears in `docket setup notify`.

The channel lives as long as its task is open. The `serve` sweep MUST remove the `a2a-<task id>`
channel of a task that is `done`, `failed` or `cancelled`, or that the pod's queue no longer
holds (pruned), after the sweep's notification flush
has delivered that task's closing event (the channel is chosen before the flush, so an event the
flush sends is never cut off). A channel of a task that is not terminal, and every channel whose
name does not begin `a2a-` or whose `config` has no `scopeTask`, is left as it is. A `failed` task
that is retried needs a new `tasks/pushNotificationConfig/set`.

## Return

| JSON-RPC code | When |
|---|---|
| `-32700` | the body is not JSON |
| `-32600` | not a single JSON-RPC 2.0 request object |
| `-32601` | unknown method |
| `-32602` | a param of the wrong shape; no text part; no pod or an unknown pod; no `data` part with an `action`; an unknown or unoffered option; content that fails `requestedSchema` or a `pre_input` policy (`data.reason` `invalid` or `refused`); an `escalationId` no record has (`not_found`); a refused push config |
| `-32001` | no task by that id |
| `-32002` | `tasks/cancel` on a task nothing holds: `pending` or terminal |
| `-32004` | a method docket does not implement (`message/stream` and the rest of the Scope list); `message/send` on a task with no pending escalation, or whose escalation is already settled (`data.reason` `not_pending`, the case `POST /escalations/<id>` answers `409`) |
| `-32603` | an unexpected failure; the message never carries a stack trace or a token |

`data` of a refusal is `{"reason": <code>}` and nothing else.

## Validation

- Recorded exchanges under `tests/contracts/a2a/*.json` are produced by a real service with a
  consult parked by a real run, through the real route, and compared once ids and times are
  placeholders: send a task (`SUBMITTED`), `tasks/get` of the parked task (`INPUT_REQUIRED` with
  the data part), the answer, a second answer (`-32004`), cancel, push config set and get.
- A local HTTP listener receives the push of a parked task and of its completion, and none for
  another task.
- The end-to-end lane drives a task over `POST /a2a` the way the plan-of-record test drives it
  over the operator routes: send, park, `tasks/get`, answer by the data part, completion, and a
  `401` without the token.
- Unit tests pin the error mapping, the part and schema builders and the push scope.

## Implementation

- `src/docket/interfaces/http/routes/a2a.py`: `post_a2a`, `get_agent_card`, the method table.
- `src/docket/interfaces/http/routes/a2a_task.py`: the `Task` object and the escalation message.
- `src/docket/interfaces/http/routes/a2a_push.py`: the push config as a channel, and `finished_channels`
  (the channels of terminal tasks, which the sweep removes).
- `src/docket/interfaces/http/routes/table.py`: the two rows.
- `src/docket/operator/notify.py`: `scopeTask` filtering of a delivery.
- `tests/contracts/test_a2a_http.py`, `tests/contracts/a2a/`, `tests/e2e/test_a2a_over_http.py`.
