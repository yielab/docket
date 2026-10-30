# outward

Researcher -> Writer -> Critic (APPROVE or REJECT, one rework back to the Writer) -> Actor.

A pod that acts outside the machine: it sends a message, submits a form, posts, books, pays, or
asks another agent to. The Researcher gathers, the Writer drafts into the working directory, the
Critic vets, and only the Actor holds a `send` tool. Reading and acting are kept apart: the roles
that read cannot send, and the role that sends cannot read the web, so what leaves was decided
before the Actor ran.

## How the separation holds

- A `send` tool (a tool of an MCP server declared `--kind send`) reaches a role only when the
  role's own `tools` list names it. The Researcher, Writer and Critic name none, so they are never
  offered one. The Actor names `mcp__outbox__send` and nothing that reads the web.
- `docket pod update` and `docket pod validate` refuse a role whose `tools` name a `send` tool
  and that still holds `fetch` or a tool of a `read` server. A step's `tools` can satisfy the rule
  when every step that runs the role declares them.
- `policies/ask-before-send.yaml` asks a person before the Actor's send runs. A policy matches a
  tool by its exact name, so it lists every `send` tool of the pod: when your sender is not
  `outbox` with a `send` tool, rename it in that policy and in `roles/actor.yaml`.
  `docket task answer <token> --option approve_once` lets that one call through.

## Prerequisites

The recipe ships no MCP server. Declare yours first; a server that both reads and acts is declared
twice, once for each. Three shapes:

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

## Apply it

This recipe is for a pod without a repository (a `workdir` blueprint such as `content`), because
the draft lives in its working directory:

```bash
docket pod update outward
```

`pod.yaml` names the four members this recipe adds: `researcher`, `writer`, `critic` and `actor`.
`apply` validates the roster, the pipeline, the read/act rule and the policy before writing
anything, and is safe to run again. `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - `members: [researcher, writer, critic, actor]`.
- `pipeline.yaml` - `research` (Researcher) -> `draft` (Writer) -> `review` (Critic, APPROVE or
  REJECT, one rework to `draft`) -> `act` (Actor).
- `roles/actor.yaml` and `roles/actor.md` - the Actor: `tools: [read, glob, mcp__outbox__send]`,
  denied `write`, `edit` and `bash`.
- `policies/ask-before-send.yaml` - asks before every `send` tool of the Actor.

## Limits

- The policy names tools exactly; a new `send` tool of the same server is not asked about until it
  is added to the policy.
- docket does not read what a server's tool does: `--kind` is your assertion, not a check.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-writer
docket pod remove <project>-critic
docket pod remove <project>-actor
```
