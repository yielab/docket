# outward

The policy pack of a `respond` pod: ask a person before every `send` tool, and cap the pod's sends.

A `respond` pod acts outside the machine: it sends a message, submits a form, posts, books, pays, or
asks another agent to. Its pipeline (`docket init --blueprint respond`) is the Lead's intake, a
Researcher who gathers, a Writer who drafts into the working directory, a Reviewer who vets
(APPROVE or REQUEST-CHANGES, one rework back to the Writer), and only then the Actor, the one role
that holds a `send` tool. Reading and acting are kept apart: the roles that read cannot send, and the
role that sends cannot read the web, so what leaves was decided before the Actor ran. This recipe adds
the policy half; it ships no pipeline, no role and no member, because the blueprint has them.

## How the separation holds

- A `send` tool (a tool of an MCP server declared `--kind send`, or a write operation of a
  declared service) reaches a role only when the
  role's own `tools` list names it. The Researcher, Writer and Reviewer name none, so they are never
  offered one. The starter Actor holds `read` and `glob` only; your role overlay (see "Apply it")
  adds its send tool, for example `mcp__outbox__send`, and nothing that reads the web.
- `docket pod update` and `docket pod validate` refuse a role whose `tools` name a `send` tool
  and that still holds `fetch` or a tool of a `read` server. A step's `tools` can satisfy the rule
  when every step that runs the role declares them.
- docket asks a person before any `send` tool runs, whatever its name: the kind decides, so a
  new tool of the sender is covered without a policy. `policies/ask-before-send.yaml` names the
  Actor's tool as well, to carry the message the person reads. The approval shows the whole call,
  with credentials removed and nothing else: `docket task show <escalation>` prints it under
  "What leaves" and `GET /escalations/<id>` returns it as `call`; the inbox, notifications and
  Telegram keep the redacted text. The call is deleted when the approval is settled.
  `docket task answer <token> --option approve_once` lets that one call through.

- `policies/send-quota.yaml` caps the pod at ten sends in a trailing day. The count rises when a
  `send` runs, never when one is asked about or refused; past the limit the call is refused with
  the count and the window, audited as `tool.send` with `decision=deny`, and `docket status` shows
  `send 3/10 today`. Edit `count` or `per: hour | day`, or delete the file for no cap. To cap one
  declared service instead, write `service: <name>` in place of `kind: send`.

## Prerequisites

The recipe ships no MCP server and no service. Declare yours first; a server that both reads and
acts is declared twice, once for each. Four shapes with an MCP server and a fifth with none:

1. A mailbox and its sender.

   ```bash
   docket setup mcp add inbox --kind read -- <mail-reader-mcp-server-command>
   docket setup mcp add outbox --kind send --tools send -- <mail-sender-mcp-server-command>
   ```

2. A page reader and a browser that clicks. A browser keeps a page between calls, so it wants one
   session per hop. As a `kind: mcp-server` document (`access` carries the kind, because `kind:`
   is the envelope):

   ```yaml
   # mcp-servers/pages.yaml
   kind: mcp-server
   name: pages
   command: <page-reader-mcp-server-command>
   access: read

   # mcp-servers/outbox.yaml
   kind: mcp-server
   name: outbox
   command: <browser-mcp-server-command>
   access: send
   lifetime: hop
   ```

   Put them under `mcp-servers/` beside this recipe's files and `docket pod update` installs them
   for the pod. The same sender with the command line: `docket setup mcp add outbox
   --kind send --lifetime hop -- <browser-mcp-server-command>`.

3. An agent reached through an MCP server. Declare it `read` when it only informs (a research
   agent the Researcher may ask) and `send` when it acts (it books, orders or posts for you):

   ```bash
   docket setup mcp add advisor --kind read -- <agent-mcp-server-command>
   docket setup mcp add outbox --kind send -- <same-agent-mcp-server-command>
   ```

4. An external API with a token. An API is an MCP server, either an OpenAPI-to-MCP bridge
   pointed at the API's spec or a small wrapper you write; `fetch` stays a GET without headers.
   Declare it twice, its GET operations as `read` and its writes as `send`, split with `--tools`,
   and give both the token as a `--secret`:

   ```bash
   docket setup mcp add crm-read --kind read --secret API_TOKEN=crm \
     --tools list_contacts,get_contact -- <openapi-mcp-bridge-command> --spec <api-spec>
   docket setup mcp add crm-write --kind send --secret API_TOKEN=crm \
     --tools create_contact,update_contact -- <openapi-mcp-bridge-command> --spec <api-spec>
   ```

   `--secret API_TOKEN=crm` writes `API_TOKEN: secret:crm` into the server's `env` and never the
   token. Each turn takes the value from docket's secret store (`secrets.json` in the home, or the
   keyring) and hands it to the server's process only; the store scrubs it from the trace like
   any other stored secret. A name with nothing stored makes that server unavailable for the turn,
   with the variable named, while the pod's other servers still load. A `kind: mcp-server`
   document carries the same reference under `env:` (`API_TOKEN: secret:crm`). A literal token
   under `--env` still works, and `docket setup --fix` warns about it. Token refresh and OAuth are
   the wrapping server's job.

5. An HTTP API declared as a service, with no program in between. A `kind: service` document
   names the address, the header that carries the token and each operation with its method; docket
   turns every operation into a tool `svc__<service>__<operation>`. A `GET` is `read`, so the
   Researcher is offered it with no further step; a `POST`, `PUT`, `PATCH` or `DELETE` is `send`,
   so only a role whose own `tools` list names it is offered it, and every call parks for a
   person. The token is stored once and referenced, never written into the document:

   ```yaml
   # crm.yaml
   kind: service
   name: crm
   baseUrl: https://api.example.com/v1
   hosts: []              # extra hosts a call may reach; a loopback or private address must be listed
   auth: {header: Authorization, value: "Bearer ${secret:crm}"}
   operations:
     - {name: get_contact, method: GET, path: "/contacts/{id}", params: [{name: id, in: path, type: integer}]}
     - name: create_contact
       method: POST
       path: /contacts
       body: {type: object, properties: {email: {type: string}}, required: [email]}
   ```

   ```bash
   printf '%s' "$CRM_TOKEN" | docket setup secret set crm --stdin
   docket setup service add crm.yaml
   ```

   Then point the Actor at the operation in your role overlay: set `tools: [read, glob,
   svc__crm__create_contact]` (or `svc__crm` for every operation) as shown under "Apply it". The Researcher needs no edit for the
   `get_contact` read. Every call carries `X-Docket-Task`, the id of
   the task it serves; add `idempotencyHeader: Idempotency-Key` to the document for a key on each
   write. A `DELETE` is offered `approve_once` or `deny` only. An OpenAPI 3 file builds the document
   for you: `docket setup service add crm --from-openapi crm.yaml --auth-header Authorization
   --secret crm`. `tests/e2e/test_workdir_pod.py` runs this whole path against a local fake service.

## Apply it

This recipe is for a pod without a repository: a `respond` pod, because the draft lives in its
working directory.

```bash
docket init my-pod --blueprint respond
docket pod update outward
```

The Actor's send tool is whatever your overlay names. Copy this recipe's directory, add
`roles/actor.yaml` and `roles/actor.md` to the copy, and apply the copy with `docket pod update
<directory>`:

```yaml
# roles/actor.yaml
kind: role
name: actor
description: sends the approved draft through the pod's send tool
model: strong
cannot: [write, edit, bash]
tools: [read, glob, mcp__outbox__send]
instructions: actor.md
```

`actor.md` is the Actor's instructions: what it may send and when to stop. `apply` validates the
roster, the read/act rule and the policy before writing anything, and is safe to run again.
`--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - the recipe's manifest; it adds no member.
- `policies/ask-before-send.yaml` - asks before the Actor's `send` tool, with the message the
  person reads. It names `mcp__outbox__send`; edit the name to match your tool.
- `policies/send-quota.yaml` - the quota above.

## Limits

- A `send` tool always asks, whatever a policy says, unless a person pre-granted that exact call.
- docket does not read what a server's tool does: `--kind` is your assertion, not a check.

## Undo

```bash
rm ~/.docket/config/pods/<project>/policies/ask-before-send.yaml
rm ~/.docket/config/pods/<project>/policies/send-quota.yaml
```
