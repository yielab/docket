# outward

Researcher -> Writer -> Reviewer (APPROVE or REQUEST-CHANGES, one rework back to the Writer) -> Actor.

A pod that acts outside the machine: it sends a message, submits a form, posts, books, pays, or
asks another agent to. The Researcher gathers, the Writer drafts into the working directory, the
Reviewer vets, and only the Actor holds a `send` tool. Reading and acting are kept apart: the roles
that read cannot send, and the role that sends cannot read the web, so what leaves was decided
before the Actor ran.

## How the separation holds

- A `send` tool (a tool of an MCP server declared `--kind send`) reaches a role only when the
  role's own `tools` list names it. The Researcher, Writer and Reviewer name none, so they are never
  offered one. The Actor names `mcp__outbox__send` and nothing that reads the web.
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

The recipe ships no MCP server. Declare yours first; a server that both reads and acts is declared
twice, once for each. Four shapes:

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

## Apply it

This recipe is for a pod without a repository (a `workdir` blueprint such as `content`), because
the draft lives in its working directory:

```bash
docket pod update outward
```

`pod.yaml` names the four members this recipe adds: `researcher`, `writer`, `reviewer` and `actor`.
`apply` validates the roster, the pipeline, the read/act rule and the policy before writing
anything, and is safe to run again. `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - `members: [researcher, writer, reviewer, actor]`.
- `pipeline.yaml` - `research` (Researcher) -> `draft` (Writer) -> `review` (Reviewer, APPROVE or
  REQUEST-CHANGES, one rework to `draft`) -> `act` (Actor).
- `roles/actor.yaml` and `roles/actor.md` - the Actor: `tools: [read, glob, mcp__outbox__send]`,
  denied `write`, `edit` and `bash`.
- `policies/ask-before-send.yaml` - asks before the Actor's `send` tool, with the message the
  person reads.
- `policies/send-quota.yaml` - the quota above.

## Limits

- A `send` tool always asks, whatever a policy says, unless a person pre-granted that exact call.
- docket does not read what a server's tool does: `--kind` is your assertion, not a check.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-writer
docket pod remove <project>-reviewer
docket pod remove <project>-actor
```
