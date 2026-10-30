# ADR 0036 (D-77): a pod works outward, on its own schedule

**Question:** docket's pods are built for code: a repository, a worktree, an Implementer, a diff a
reviewer reads before anything reaches the world. The maintainer wants a pod to do other work as
well: research and write, send a message, navigate a web site and act on it, call an external API,
another agent or an MCP server, and do it at a set time or on a recurring schedule, with a person wherever an
action leaves the machine. What in docket assumes code, what cannot be expressed at all, and what
must a call that acts outside the machine get that a write to disk does not, without changing how
today's code pods are governed?

**Where decided:** 2026-10-30, by the maintainer, as a scoped request of 2026-10-29: "roles that are
not only for programming; pipelines that carry other flows and routines, on schedules; reading and
sending mail, reports; navigating and interacting with web sites; calling external APIs;
interacting with other agents and MCP servers; roles that act outward with their own security and escalation, without changing
today's governance". An outreach product (prospect, draft, send, follow up) was the worked example,
not the goal. Two private audits hold the full reading; this ADR keeps what the cards need. Every
number below was measured on this system; none is a projection.

## What was found

Read and run at `537c0b1f` on 2026-10-29 and 2026-10-30. Three probes ran the real product as
`python -m docket` subprocesses with a scripted model (the e2e harness, `tests/support/e2e.py`) on a
pod with no repository; one probe ran Playwright MCP 0.0.83 through docket's own MCP client against
a Chrome started with remote debugging; findings 3, 7, 8 and 9 were read in the code. Locators are
symbols or lines; re-locate with `rg -n`.

1. **A pod without a repository runs today.** The `content` blueprint (`workspaceKind: workdir`,
   lead → writer → critic) took a task to `done` in three hops with no worktree, no `baseCommit`
   and its output in the working directory. A custom pipeline on the same pod ran a `REJECT →
   draft` rework once and a `run:` step (`command_step exit 0`, cwd the working directory) and
   finished `done`. Worktree, `prepare`, diff, evidence and the protected-path check skip cleanly
   without git (`teams/workspace/worktree.py:39-41,106-112`, `tasks/application/queue.py:335`,
   `hops/gates/pre_hop.py:352`). No e2e or golden case had dispatched such a pod.
2. **The text a hop reads is code's.** On that pod the Lead's hop said "Working directory: the
   repository root" (the hop root line in `hops/application/compose.py`), and its identity named
   "repository" 3×, "code" 2×, "git" 1× (`templates/prompts/identity/lead.md:32-34`). The writer's
   `## Method` block said "repository map" and `grep` 2× (`teams/builtin_roles.py:19-35`, inherited
   by a custom role without a `## AGENTS` heading, `teams/roles.py:363`), and the writer carried
   `bash`, `edit` and `process_*` because its starter archetype denies nothing. The `MEMORY.md` seed
   has no workdir variant (`teams/agent_memory.py:222-243`). The `web-research` recipe's Lead gets
   "plan for the Implementer" (`templates/recipes/web-research/pipeline.yaml:8`,
   `templates/prompts/hop/lead.md:9`).
3. **Nothing tells an action outside the machine from a write to disk.** `ToolKind` is
   `read | write | exec` (`agent/tools/registry.py:37`); an MCP server is `read` or `write`, `write`
   by default (`kernel/mcp.py:33`); a role narrows by capability, and the pod's `deniedTools` refuses
   any non-built-in name (`teams/roles.py:205-217`, `teams/pod_settings.py:337-358`). A policy can
   `ask` for one tool by name, bound to the call's argument digest (`governance/gate.py:93-95,182-194`);
   that is the only lever today, and it is per tool name, not per kind of effect.
4. **A person approving an outward action does not see exactly what leaves, and an allowed call
   leaves no audit row.** With a policy `ask` on writes to `outbox/*`, a draft message parked the
   task `waiting_approval`; the inbox showed the call, its path and its body, with both e-mail
   addresses as `[REDACTED]`. The redaction is by text pattern, not by what the call does
   (`governance/secrets.py:140-164`): credentials and e-mail addresses are hidden wherever they
   appear, while a phone number, a chat handle, a name or a customer id in a form or an API body
   shows in full, so the same rule hides a mail recipient and shows a chat recipient. The summary is
   cut at 1,000 characters (`governance/gate.py:195`), so a long form or API body is approved half
   read. The full call is never kept: the approval record holds the redacted text and the argument
   digest (`governance/approval.py:242-248`, `gate.py:182`), and on resume the model re-issues the
   call, which runs only if its digest matches. `task answer --option approve_once` resumed it to
   `done`. The audit log held `tool.ask`, `approval.grant`, `approval.consume`,
   `escalation.resolve`, and no row for the call once allowed (`gate.py:136-167` audits only
   non-allow decisions). Expiry 24 h, L3.
5. **A browser session survives docket's MCP client; what the model needs to act on it does not.**
   Playwright MCP over `--cdp-endpoint` against an external Chrome, through
   `agent/tools/mcp_client.py::call_remote_tool`: the page navigated in call 1 was still open in call
   2 (same URL, element `ref=e3`); a click on `e3` in call 3 answered "Ref e3 not found in the
   current page snapshot". docket spawns one subprocess per exchange on purpose
   (`mcp_client.py:9-17`), so any server that keeps state between calls (a browser's element map, a
   login handshake, an agent conversation) loses it. The spec's own Playwright example
   (`mcp-client.spec.md:422-449`) cannot work as written.
6. **Time cannot be expressed.** `docket pod set schedule` parses cron, but holds one entry per pod
   and only re-dispatches the queue that already exists (`interfaces/http/sweeps.py:46-59`,
   `pipeline/application/schedule.py:156`); nothing creates a task on a schedule, there is no time
   zone (UTC only, `schedule.py:15-25`), no `wait` step (`pipeline/domain/step.py:88-136`), no
   `notBefore` (`tasks/domain/task.py:211-228`). Variables belong to a dispatch run, not a task
   (`interfaces/http/routes/dispatch.py:36,60`; the sweep passes none), and `when.var` compares the
   raw value where the spec says text (`hops/application/executor.py:217`, `pod-dispatch.spec.md:1333`).
   A parked task, on the other hand, waits for days and survives a restart: the probe's task went
   `waiting_approval → pending → done` across two separate `docket run` invocations.
7. **A custom role cannot pin a model.** `setup model set role.<custom>` is dropped silently
   (`teams/model_selection.py:432`, `if role in ROLE_CLASS`); the spec says it works
   (`role-archetypes.spec.md:553`).
8. **The network is narrowed, never widened, by a pod** (`security-gates.spec.md:1088-1093`), and
   the `fetch` allowlist is one list for the machine (`kernel/home.py:278`).
9. **An external API is reached only through an MCP server, and its credential is written in
   clear.** `fetch` sends a GET with a `User-Agent` header and nothing else
   (`platform/fetch.py:275`): no method, header or body, so no token and no write, by design. An MCP
   server's `env` holds plain values in `mcp-servers.json` (`teams/mcp_servers.py:78,100-101`),
   handed to the subprocess as written (`agent/tools/mcp_client.py:81`). Values kept in docket's
   secret store are already scrubbed from every trace (`governance/secrets.py:172-185`); values in
   `mcp-servers.json` are scrubbed only if they look like a known key format.

## Decision

Twelve decisions. The rule every one of them follows: **everything new is a capability no existing role or pipeline
has unless it names it.** A code pod that names none of it reads, runs and is governed byte for
byte as today.

1. **Code is the first kind of work, not the only one.** The text a hop reads follows the pod's
   `workspaceKind`: the hop root line says "the working directory" on a workdir pod, the `## Method`
   block and the `MEMORY.md` seed have a workdir variant, the Lead's prompts name "the role that
   follows" rather than the Implementer, and a recipe's Lead step carries its own instructions. The
   writer starter archetype denies `exec`. The first e2e test of a workdir pod is this decision's
   oracle. A custom role pins a model like a built-in one. (P55-1, P55-2)
2. **`send` is a fourth tool kind: the call acts outside the machine.** It sends a message, submits
   a form, posts, books, pays, or asks another agent to do any of these. An MCP server is declared
   `--kind read | write | send`. Unlike `write`, which every role has unless it denies it, a `send`
   tool reaches a role only through its `tools` allow-list. The same service read and acted on is
   two declarations (a mailbox `read`, the same server `send`; a browser for reading pages `read`,
   the browser that clicks `send`). A role that names a `send` tool cannot hold `fetch` or a `read`
   MCP server in the same hop: the one who reads untrusted text does not act; the one who acts
   receives reviewed work. Checked when the pod is updated. (P55-3)
3. **The person who approves an outward action sees exactly what leaves; every copy that is kept or
   forwarded stays redacted.** The line is drawn by place, not by kind of data, so it holds the same
   for a message, a form, a chat post or an API body without docket having to recognize what is an
   address. For a `send` call under `ask`, the approval keeps the whole call with only credentials
   removed (tokens, keys, passwords, `Authorization` headers, stored secret values), uncut, in the
   approval record (the home's `approvals/`, mode 700) while it is pending, and deletes it when the
   approval is settled: granted, denied or expired. Only the operator's own views show it, `docket
   task show <escalation>` and `GET /escalations/<id>` with the token. The trace, the audit log, the
   inbox list, notifications, Telegram, the MCP `inbox` tool and the observability export keep
   today's redaction. Every `send` call writes an audit row whatever the policy decided. A `send`
   under `ask` is an ordinary `approval`, denied at L5 as today, so no level acts outward without a
   person or a pre-grant. Other approvals (a gated shell command) are unchanged. (P55-4)
4. **An MCP server may live for the hop.** `lifetime: call | hop` on the server; `call` is today's
   subprocess per exchange and stays the default. A `hop` server opens on its first call, answers
   the hop's calls over one session, and is stopped where the hop's background processes are stopped
   (ADR 0034). This is what lets a pod navigate and act on a web site, or hold a conversation with an
   agent behind an MCP server, inside one hop. (P55-5)
5. **A `wait` step parks the task until a time or an event.** `- <id>: {wait: "72h", until: {run:
   "<probe>", every: "15m"}, on: {timeout: ...}}` creates an `Escalation` of kind `wait` that the
   escalation sweep settles when the time comes or the probe exits 0; the task resumes at the next
   step or routes on `timeout`. `wait` asks no one, is the same at every autonomy level and never
   shows under "needs you". It absorbs P52-12 (ADR 0034 decision 5). (P55-6)
6. **Variables belong to the task.** `POST /tasks/<pod>` and `task add --var` carry `variables`,
   merged over the run's; `when.var` compares as text. (P55-7)
7. **A quota is the one stateful rule.** A policy may say `limit: {kind: send, count: N, per: hour |
   day}` for a pod; the counter is written by the store and counts executions, not attempts; over the
   limit the call is blocked and audited. No other stateful rule. (P55-8)
8. **A routine creates tasks on a schedule.** A `kind: routine` document in the team's configuration
   (the four scopes of ADR 0035) names a schedule (5-field cron or `@every`), an IANA time zone, and
   the task to create: description, pipeline, variables, priority. The `docket start` sweep creates
   the task when a slot is due, with `idempotencyKey` `routine:<name>:<slot>` so a restart never
   duplicates it; `catchUp: skip | once` says what a slot missed while the service was down does;
   `overlap: skip | queue` says what happens while the previous run of the same routine is not
   finished. A plan of record (Tack) can still create tasks itself; a routine is how a pod works on a
   schedule without one. `pod set schedule` keeps its meaning. (P55-9)
9. **The browser is external, in two levels by risk.** Reading pages goes through `fetch` or an
   agent-browser server declared `read`, its output untrusted text. Acting on a site goes through a
   browser MCP server (Playwright MCP over `--cdp-endpoint` against a persistent browser) declared
   `send` and `lifetime: hop`, each action a governed call. No native browser tool.
10. **Another agent is a tool.** An agent is reached through an MCP server (one that wraps an A2A or
    HTTP client, or the agent's own MCP endpoint), `read` if it informs, `send` if it acts. docket
    governs the request and the result; what the agent does inside its own loop is outside docket's
    perimeter, and the docs say so. docket is already an A2A and MCP server for agents that call it.
11. **An external API is an MCP server, and its credential comes from the secret store.** An API is
    reached through an MCP server (an OpenAPI-to-MCP bridge or a small wrapper): its reading
    operations declared `read`, its writes `send`, split with the server's `tools` list, so a write
    to an API is governed like any other outward action. An MCP server's `env` value may be
    `secret:<name>`, resolved from docket's secret store when a turn loads its servers, never
    written to `mcp-servers.json` and scrubbed from traces like every stored secret. `fetch` stays
    a GET for reading pages. (P55-10) Amended 2026-10-30 by decision 13: an MCP server stays a valid
    way to reach an API, but it is no longer the only one.
12. **A pod widens the machine's network only with the operator's recorded yes.** A machine whose
    recorded network mode is `none` stays `none` for every pod, except a pod the operator widened
    with `docket pod set network open --widen`: the command says what opens (the pod's `bash`,
    `run:` steps, checks and MCP servers reach any host), asks `[y/N]`, records the grant with its
    date and audits it, the shape of a repository's commands accepted under ADR 0024. Only that
    command writes the grant; `pod update` and the HTTP apply never do, so a repository cannot open
    its own network. `pod set network none` removes it. A new pod is closed by default, as today.
    This amends the rule "a pod's `network` can only narrow it" (`security-gates.spec.md` item 7).
    (P55-11)

## Amendment, 2026-10-30: an external service is declared, not programmed

**Status: accepted 2026-10-30** by the maintainer, the day Phase 55's cards merged, from a request
made after the phase-close real run. Decisions 1 to 12 are unchanged.

**Why.** Decision 11 reaches an API through an MCP server, which means a program per service,
written or found before a task needs it. The maintainer wants a pod to reach a service nobody
programmed in advance, configured by commands or by a document, and does not want further MCP
implementation work. A task that ends in a `send` at a new service cannot wait for a bridge.

13. **A service is a document, and its operations are tools.** A `kind: service` document (name,
    `baseUrl`, an `auth` header whose value may be `${secret:<name>}`, and `operations`, each with a
    method, a path with typed parameters, an optional JSON body and `access: read | send`) is
    registered with `docket setup service add` or by a pod's `services/` directory, as
    `kind: mcp-server` is. Each operation becomes one tool through `dispatch_tool`: its kind is the
    operation's `access`, so a `send` operation is approved by a person who sees the whole call,
    audited `tool.send`, counted by the quota and redacted in every kept copy, exactly as decision 2,
    3 and 7 say, and a role holds it only by naming it in its allow-list. The secret is resolved when
    the call runs and never reaches the model, the trace or the audit. The caller is docket's own
    process, not the jail (as `fetch` is), so the perimeter is the service's host alone: a call to any
    other host, a redirect off it and a private, loopback or link-local address are refused unless
    the document lists them, and a path parameter is encoded, never concatenated. Response size and
    time are bounded as `fetch`'s are. A command to store a named secret (`docket setup secret set`,
    value by prompt or stdin, never echoed) comes with it, since a reference to a name nothing can
    write is unwired.

    *The maintainer's scope:* a header token now; JSON in and out, text otherwise; the jail not
    involved; every method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`); operations written by hand and
    imported from an OpenAPI document. An MCP server and a service never share a name. The quota
    counts per service.

14. **Writes are handled apart.** `GET` is `read` unless declared `send`; `POST`, `PUT`, `PATCH` and
    `DELETE` are always `send`, so a write reaches only a role that names it (one acting agent in the
    pipeline), is approved by a person who sees the whole call, is audited and is counted by its
    service's quota. A `DELETE` is approved one call at a time: it never offers "approve for this
    task". An agent that vets the call before the person is a pipeline step, as in `outward`.

*OAuth, later, and what it brings.* A client-credentials grant (a machine token from a token URL
with a client id and secret) needs no person: a token cache with its expiry, refreshed before it
lapses, the client secret in the store. An authorization-code grant (acting as a person's account)
needs that person once in a browser to consent, a local callback or a device code to receive the
grant, a refresh token kept in the store and rotated, and a task that meets an expired or revoked
grant parks for the person again. A site's own sign-in page (an SSO screen with a second factor) is
neither: it is the browser case, a person's step. None of it is in Phase 56.

*Cards:* Phase 56, P56-1..P56-9 on `TODO.md`.

## Second amendment, 2026-10-30: a pod keeps records, and a call that leaves names its task

**Status: accepted 2026-10-30** by the maintainer, as written (the three choices the cards took by default stand), from the maintainer's request the same day to fold the standard
teams work into Phase 56 without oversizing it, and to give pods "somewhere to store" the data of
the business: reports, listings, compilations, a register, captured data. Not docket's own state:
tasks, trace, audit and approvals stay where they are. Decisions 1 to 14 are unchanged. The three choices that were open (records belong to one pod, `rec__query` takes a read-only `SELECT`, an update overwrites the row) were settled by accepting it.

**Why.** Nothing in `src/docket` stores tabular data: there is no `sqlite3` import, pod memory
(`memory.json`) holds verified facts about the workspace, and a workdir pod that keeps a register
today writes a file the model must re-read whole, against a tool-output bound of 2,500 characters on
the local model. A declared service (decision 13) reaches a database someone runs, but a pod that
only needs a table should not need a server.

15. **A pod's records are declared tables in one SQLite file the pod owns.** A `kind: records`
    document in a pod's `records/` directory names a set, its typed columns (`string`, `integer`,
    `number`, `boolean`, `date`) and an optional `key` column. `pod update` creates the table or adds
    a column; it never removes, renames or retypes one. The file is `pods/<pod>/records.sqlite`,
    beside `memory.json`, outside the roots the jail may write, and one module writes it
    (`platform/records_store.py`, pinned like the task queue's writer). The tools follow the
    methodology "operations, not tables": `rec__<set>__add` and `rec__<set>__update` are `write`
    tools whose parameters are the declared columns, and an `add` whose key exists returns the
    existing row, so a resumed hop that repeats its call writes once; `rec__query` is a `read` tool
    that runs a `SELECT` on a read-only connection with an authorizer, a row bound and a time bound;
    `rec__export` writes a query's rows as CSV or Markdown into the hop's working directory without
    passing them through the model. docket fills `_task`, `_session`, `_step` and `_at` on every row
    from the hop, never from the model's arguments. Records never leave the machine, so no record
    tool is `send`.
16. **A service call names its task.** Every declared-service call carries `X-Docket-Task: <task
    id>`, and a `send` operation of a document that declares `idempotencyHeader` carries that header
    with a key derived from the task, the step, the operation and the canonical body, so the service
    can recognize a repeated call, such as the call a resumed hop issues again after its approval.

*Not in this amendment's decisions:* a set shared between pods, deleting rows,
vector search, an HTTP MCP transport (still deferred, above), a second store for docket's own tasks.

*Team composition, in the same phase and under no new decision.* The maintainer's request of the same
day also folds in what the standard-teams review found in the code team, each a card that amends an
earlier decision's data rather than this ADR, under the maintainer's rule that docket has no users and
keeps nothing for compatibility: one judge, `reviewer`, `strong`, judging code, text or data, with
`critic` and `tester` deleted outright (ADR 0012's archetypes are data; the tester ran the suite the
implementer's gate had run and could add no test); the full pod is lead, implementer, reviewer; the old
single-level home layout, its migration, the `roles.json` shim and the metadata models that kept unknown
keys are deleted; the short form and `docket init --with` resolve every registered role rather than the
four software ones; a pod's records are read over the HTTP API by the plan of record (how another pod
reads them without a shared file); an OpenAPI 2 document imports beside 3 (PostgREST publishes 2.0); and
the blueprints become the four team shapes the standard-teams review found behind every department
(`build`, `respond`, `operate`, `routine`: a roster, a pipeline, a workspace kind), with `actor` a
starter archetype and a recipe carrying only what a blueprint cannot (a policy pack, a records set, a
schedule), so nothing ships twice. A department (support, finance, …) is a shape plus the operator's
prose, connectors and policy, documented, never shipped as a blueprint.

*Cards:* Phase 56, P56-10..P56-20 on `TODO.md`; P56-3 and P56-5 carry decision 16.

## Not doing

- Native browser, mail, chat or CRM tools, and methods, headers or bodies on `fetch`: capability comes
  from MCP servers or from a declared service (decision 13), docket keeps the gate (the reasoning that
  refused a native search tool, ADR 0034). A declared service is configuration, not a tool per product.
  OAuth flows and token refresh belong to the server that wraps the API.
- An HTTP or SSE MCP transport, a `task`-long MCP session, a per-pod `fetch` allowlist (deferred).
- Per-host network rules inside the jail: it is all or nothing (finding 8), which is why a widened
  pod's outward roles hold no `exec`.
- An unredacted copy of an outward call anywhere but the pending approval record: not in the
  trace, the audit log, a notification or the export, and not after the approval is settled.
  Recognizing personal data by pattern beyond what `redact` does today is not attempted.
- Task-to-task dependencies, a follow-up task enqueued by a hop, sub-agents inside a turn: a
  pipeline's steps, a `wait` and a routine cover the measured needs.
- A new `EscalationKind` for outward actions: a `send` under `ask` is an approval.
- Any claim that a gated action is permitted by the site or service it reaches. docket governs the
  call; whether a site's terms allow automation is the operator's responsibility.

## Deferred, with triggers

- **HTTP/SSE MCP transport.** Trigger: the first real pod whose connector exists only hosted.
- **A per-pod `fetch` allowlist.** Trigger: two pods on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed
  the previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

## Cards

Twelve cards, Phase 55 on `TODO.md`, cut by file ownership into four waves. Sonnet runs behaviour in
`src/`; Haiku the docs card; no Opus.

| Wave | Cards | Why together |
| --- | --- | --- |
| 1 | P55-1 (workdir text, first workdir e2e), P55-5 (`lifetime: hop`), P55-7 (task `variables`), P55-11 (a pod's network grant) | prompts and compose · the MCP client · the task record · `effective_network` and `security-gates.spec.md`: disjoint files and specs |
| 2 | P55-3 (`send`, the `outward` recipe), P55-6 (`wait` step) | P55-3 continues `kernel/mcp.py` after P55-5; P55-6 continues `executor.py` after P55-7 |
| 3 | P55-2 (role model pin), P55-4 (send audited, the approver sees the whole call), P55-9 (routines) | P55-2 follows P55-3 on `role-archetypes.spec.md`; P55-4 needs the kind and follows P55-6 on `render.py`; P55-9 needs task variables and follows P55-6 on `pod-dispatch.spec.md` |
| 4 | P55-8 (send quota), P55-10 (API credentials from the secret store), P55-12 (docs) | P55-8 continues `gate.py` after P55-4; P55-10 continues `kernel/mcp.py` after P55-3 and P55-5; docs at the close |
