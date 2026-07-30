# Security Gates Specification

**Version**: 0.5.0
**Status**: Implemented (on by default for new installs; daemon-enforced — see the approval-seam note below). Docket's own approval store now has a real production producer (ROADMAP Phase 15 G-1); the daemon-gate bridge is confirmed **not available** today — the G-5 spike investigated it against a live daemon and concluded no practical bridge exists (see the approval-seam note and the G-5 findings section).
**Last Updated**: 2026-07-30

## Purpose

This specification defines the tool-approval and workspace-isolation model for docket agents:
requiring explicit approval before dangerous tool calls and confining agents to their own
workspace. It is implemented on the OpenClaw daemon's native exec-approval, approval-routing,
and sandbox primitives — docket configures and verifies; the daemon enforces.

> **Implementation status.** `docket install` applies exec-approval gates **by default**
> (`--no-gates` opts out; `--gates` is the explicit, redundant form of the default). `docket
> gates enable [--force]` remains available to (re-)apply the same configuration to an
> already-installed fleet, or one that opted out at install time. Gates
> write conservative exec-approval defaults (`security: allowlist`, `ask: on-miss`,
> `askFallback: deny`) with a curated allowlist; enabling gates also routes approval prompts to
> each agent's session (`approvals.exec`, answerable via `docket approve`/`docket deny` or, when
> Telegram-bound, `/approve`); `docket gates isolate on` applies Docker workspace isolation.
> `docket doctor` reports gate status, approval routing, isolation, and config-permission
> hardening.
>
> **Why on-by-default now.** The previous version of this spec deferred on-by-default pending
> "per-agent headless approval routing," reasoning that session-mode (Telegram) delivery "only
> answers prompts during an interactive session" and default-on "could deny an unattended agent
> with no approver." That blocking condition is now met: docket ships two headless-capable
> approval channels alongside Telegram —
>
> - **CLI channel**: `docket approve [token]` / `docket deny <token>` grant or deny a pending
>   approval from any shell (interactive or scripted); omitting the token lists everything
>   pending. No chat session required.
> - **HTTP channel**: `docket serve`'s `GET /approvals` (list) and `POST /approvals/<token>`
>   (`{"action": "grant"|"deny"}`, bearer-token authenticated) let CI jobs, cron, or any
>   automation vote on a pending approval without a human at a keyboard.
>
> Both channels are real, shipped surfaces (Phase 13) — **but note what they operate on.**
>
> **The approval seam (updated 2026-07-30 — G-1 shipped, G-5 concluded "no bridge").** There are
> two approval systems in play, and **the daemon-facing half of the seam is still not bridged**:
> (a) the **daemon's** exec-approval prompt — the thing that actually fires when a gated binary
> is invoked — which is delivered to the agent's chat session and answered with the daemon's own
> `/approve <id>` mechanism; and (b) **docket's** approval store (`apr-*` tokens under
> `$APPROVALS_DIR`), which the CLI/HTTP channels above read and write. The daemon's gate prompt
> still does not mint an `apr-*` token, so `docket approve` still cannot answer a *live daemon*
> gate.
>
> **G-5 spike verdict: No — a practical bridge does not exist today.** ROADMAP Phase 15 G-5 asked
> whether the daemon's exec-approval prompt can notify an external hook. It was investigated
> against a locally installed `openclaw 2026.2.23` daemon (live gateway, real registered agents)
> plus its published documentation. Short answer: half of a bridge is real and reachable
> (resolving a *known* prompt), while the other, load-bearing half (learning that a prompt exists
> at all) is not reachable from anywhere in docket's current toolbox. See "The `[GATE]` seam —
> G-5 spike findings" below for the full evidence trail. That card shipped no code, per its own
> evidence standard — so this remains a documented, evidenced upstream limitation rather than an
> open question.
>
> What changed: docket's store previously had **zero** production producers (`approval_create`
> was called only by tests). ROADMAP Phase 15 G-1 ("approval-gated dispatch") gave it its first
> one — `core/dispatch.py`'s require_approval gate, evaluated pre-hop in the pod dispatch
> pipeline (see `pod-dispatch.spec.md` v2.1.0). A gated hop now genuinely creates a real approval
> record, and `docket approve`/`docket deny` (and the HTTP endpoint below) genuinely resume or
> kill the *dispatch task* that gate stopped — this is real, shipped behavior, not a future
> contract. It is still scoped narrowly: it gates a pod dispatch hop, not the daemon's own
> exec-approval prompt for an arbitrary tool call, and its only wired trigger source this version
> is a pod-level Lead-meta role list (two more sources — a policy match, a pipeline step — are
> documented, inert seams for later cards; see `pod-dispatch.spec.md`).
>
> **Why on-by-default is still safe:** the fail-closed property for an unattended agent's
> *daemon-side* gate is the daemon's own `askFallback: deny` — a prompt nobody answers is denied
> by the daemon, full stop; that is unchanged by G-1. Separately, `approval_sweep_expired` now
> resolves a stale pending record in docket's own store to **denied** (fail-closed) after
> `APPROVAL_TIMEOUT`, not the prior, read-by-nobody `"expired"` state — and, for a G-1-originated
> record specifically, that resolution also fails the waiting dispatch task, so an unanswered
> gate on a pod dispatch hop now genuinely fail-closes end to end, not just on paper. This sweep
> still runs only while `docket serve` is up.

## Scope

This specification covers:

- Tool-approval gates for dangerous operations
- Workspace isolation between agents
- Audit logging of approvals and denials
- The high-risk action-class policy (money-movement, prod-deploy, secret-access)

This specification does NOT cover Telegram transport (see telegram-integration.spec.md), which
is *one* channel for approval prompts — the CLI and HTTP channels above are equally real and
are owned here, not there.

## Requirements

### Tool-approval gates (implemented)

1. Dangerous operations not on the curated allowlist (e.g. `rm`, `dd`, `docker`, `systemctl`)
   **MUST** require explicit approval before execution once gates are enabled (the default for
   new installs). Note: `git`/`npm` ARE on the curated allowlist (they're used constantly for
   benign work) and so do NOT prompt by default even for a high-risk invocation like
   `git push origin main` — see "High-risk action classes" below for that specific, narrower gap.
2. Approvals in **docket's approval store MUST** be answerable via at least one headless
   channel (CLI `docket approve`/`docket deny`, or HTTP `POST /approvals/<token>`). The
   daemon's own gate prompt is answered in the agent's session via the daemon's `/approve`;
   it is **not** answerable through docket's channels until the Phase 15 G-5 bridge lands
   (see the approval-seam note above). Since ROADMAP Phase 15 G-1, one real producer exists for
   this store — `core/dispatch.py`'s require_approval gate — and both headless channels
   **MUST** genuinely resume or kill the dispatch task a gate stopped, not merely flip the
   approval record's own state; see `pod-dispatch.spec.md`'s `resolve_waiting_approval`.
3. A gate prompt with no approver **MUST** fail closed. For the daemon's own exec-approval
   prompt this is enforced by `askFallback: deny`. Separately, a stale **pending** record in
   docket's own store **MUST** resolve to **denied** (not the pre-G-1 `"expired"` state) after
   `APPROVAL_TIMEOUT` via `approval_sweep_expired` — which runs only while `docket serve` is up.
   For a G-1-originated record (one gating a dispatch task), that resolution **MUST** also fail
   the waiting task terminally (`failureKind: "approval_denied"`) — this sweep is bookkeeping
   for the daemon's own gate, but real enforcement for docket's own require_approval gate.
4. Every grant and denial **through docket's approval store MUST** be recorded in the audit
   log (`audit_log("approval.grant"|"approval.deny", ...)`), tagged with the channel it came
   through (`cli`, `http`, or `timeout` for the expiry sweep's own fail-closed denial). The
   `telegram` tag is reserved for a future daemon bridge, which the G-5 spike (below) concluded
   is not currently practical to build: today a daemon-side `/approve` writes **no** docket
   audit entry.

### The `[GATE]` seam — G-5 spike findings (investigated 2026-07-30, not bridged)

1. **Question.** Can the daemon's native exec-approval prompt notify an external hook, so docket
   could bridge it into its own `apr-*` token store and answer it via `docket approve`/`docket
   deny`/`POST /approvals/<token>`, making the target-state example below genuinely real?
   Investigated against a locally installed `openclaw 2026.2.23` daemon — a live, already-running
   gateway with real registered agents — plus its published docs at docs.openclaw.ai.

2. **Confirmed present: the write half.** `exec.approval.resolve` is a real, registered Gateway
   RPC method on the installed daemon: calling it with no params returns a schema-validation
   error (`must have required property 'id'; must have required property 'decision'`), not
   `unknown method` — the daemon's distinct error for a genuinely absent method (see point 3). It
   is reachable via `openclaw gateway call exec.approval.resolve --params '{...}'`, the same
   CLI-subprocess pattern `edges/adapters/openclaw.py` already uses everywhere else — so
   *writing* a decision back to the daemon, once its id is known, needs no new client, dependency,
   or credential type beyond what docket already shells out to.

3. **Confirmed absent: the notify half.** Official docs (docs.openclaw.ai/gateway/clients,
   /tools/exec-approvals-advanced) describe an `exec.approval.requested` broadcast event plus an
   `exec.approval.list` backfill call, consumed by a WebSocket "operator" client holding the
   `operator.approvals` scope, via the officially "published Gateway packages"
   `@openclaw/gateway-client` / `@openclaw/gateway-protocol` — both **npm-only**; no Python SDK is
   published or documented anywhere. The docs themselves flag this surface as still rolling out
   ("npm may return `E404` until the first package-bearing OpenClaw release is published").
   Probing the installed daemon's `openclaw gateway call <method>` escape hatch (a request/
   response CLI call, not a subscription) for a backfill/list method under every plausible name
   returned `unknown method` in every case: `exec.approval.list`, `exec.approvals.list`,
   `exec.approval.pending`, `exec.approvals.pending`, `approval.list`, `approvals.list`,
   `commands.list`. There is no `openclaw gateway subscribe`/`listen`/`watch` CLI command either —
   `openclaw gateway call` is the only CLI-level RPC surface, and it is strictly request/response,
   so it structurally cannot deliver a push notification.

4. **Confirmed absent: a generic webhook.** `openclaw webhooks --help` covers only Gmail Pub/Sub
   (via `gogcli`) — unrelated to exec approvals. No config key under `approvals.exec` accepts an
   arbitrary URL; the only built-in "forwarding" is `approvals.exec.targets`, a fixed enum of
   native chat channels (Slack/Telegram/Discord/Matrix/Google Chat/WhatsApp/Signal/QQ bot),
   resolved via each channel's own `/approve` command — not an integration point docket (a CLI
   tool, not a chat channel) can register into.

5. **Confirmed absent: an HTTP path to resolution.** The bundled, opt-in `admin-http-rpc` plugin
   (disabled by default) exposes a curated method allowlist over plain HTTP —
   `exec.approvals.get`/`exec.approvals.set`/`exec.approvals.node.get`/`exec.approvals.node.set`
   (the static *policy* file: allowlist entries, `security`/`ask`/`askFallback` mode) — but
   explicitly **excludes** `exec.approval.resolve`/`approval.resolve` (the live per-request
   grant/deny action) from that allowlist per its own documentation. So even enabling that plugin
   does not give docket's HTTP-based `serve.py` a way to resolve a live prompt, let alone list one.

6. **Confirmed absent: the plugin hook system is a different, independent gate.** OpenClaw
   plugins can register `before_tool_call` with `requireApproval` (matched on tool ids like
   `exec`) to add their *own* approval step — but per the docs, "`approvals.plugin` is
   independent from `approvals.exec`. Enabling exec approval forwarding does not route plugin
   approval prompts." A plugin cannot use this hook to observe or resolve the *native*
   exec-approval prompt; it can only bolt on a second, parallel approval gate with its own,
   separate prompt.

7. **Verdict: No.** Half of a bridge exists and is genuinely reachable
   (`exec.approval.resolve`, over the existing CLI-subprocess pattern) — but the other,
   load-bearing half (learning that a prompt exists, and its `id`) is not reachable from
   anywhere in docket's current toolbox (subprocess calls + JSON file I/O). The only documented
   way to receive it is a persistent, authenticated WebSocket "operator" session — a protocol
   with no Python implementation published anywhere, requiring docket to mint and hold a new,
   high-privilege `operator.approvals` device credential (described by OpenClaw's own docs as
   "remote-execution-grade authority") that docket has never needed before. Implementing that
   from the wire-protocol docs alone, with no official Python SDK to validate against and no
   confirmation the backfill/list call even exists in the shipped daemon, is a multi-week
   protocol-implementation project, not a spike-scoped bridge — so no bridge was built. The
   `[GATE]` example below stays labeled target state, not shipped.

8. **What would change this answer.** Either (a) OpenClaw ships a Python-compatible client (or a
   documented, HTTP-reachable equivalent of `exec.approval.list` / `exec.approval.requested`), or
   (b) the `admin-http-rpc` plugin's exposed method allowlist is extended to include
   `exec.approval.resolve` *and* a way to list or stream pending requests over plain HTTP. Until
   one of those lands upstream, this spec's `[GATE]` bridge example remains aspirational by
   necessity, not by omission.

### Workspace isolation (implemented, opt-in)

1. An agent **MUST NOT** read or write outside its own workspace and codebase path.
2. Path traversal out of the workspace **MUST** be rejected (see input-validation.spec.md,
   `prevent_path_traversal`).
3. Docker workspace isolation (`docket gates isolate on`) remains **opt-in** — it requires
   Docker and is not part of the gates-default-on flip (which covers exec-approval only).

### Enablement (implemented)

1. `docket install` **MUST** apply exec-approval gates by default; `--no-gates` **MUST** be
   available as an explicit escape hatch that skips gate application entirely.
2. `docket gates enable [--force]` **MUST** remain available to apply (or re-apply) the same
   configuration to an already-installed fleet, or one that opted out at install time.
3. There **MUST** be a way to verify gate status (`docket doctor`, `docket gates status`).

### High-risk action classes (implemented, FD-3)

1. `core/security.py` **MUST** define a small, built-in, named list of high-risk action
   classes (`HIGH_RISK_PATTERNS`): today, `money-movement`, `prod-deploy`, and `secret-access`.
   Each class's pattern **MUST** be matched, case-insensitively, against the full command
   string (e.g. `"git push origin production"`), not just the invoked binary name. This is
   intentionally a small policy seed, not exhaustive coverage; it is not yet user-configurable
   (a config-file override is a natural follow-up, not implemented today).
2. For any caller that has an actual command string to classify (`resolve_command_action`,
   used by tests and available to any future daemon hook or docket subprocess call site), a
   high-risk pattern match **MUST** always resolve to `ask`, regardless of whether the invoked
   binary's resolved path is present in the curated allowlist — allowlist membership **MUST
   NOT** bypass a high-risk match in this decision function.
3. **Money-movement** and **secret-access** classes **MUST** be treated as fully enforced by
   the shipped allowlist gate today: none of their named bins (`stripe`, `paypal`,
   `ssh-keygen`, `vault`, etc.) are members of the curated `SAFE_BINS` allowlist, so any live
   agent invocation matching these classes already falls through to `ask` under
   `docket gates enable`'s existing exec-approval config — no additional wiring was needed.
4. **Prod-deploy** is a documented policy, **not fully daemon-enforced**, for its two bins that
   overlap the curated allowlist (`git`, `npm`): the OpenClaw daemon's own exec-approval
   allowlist gates by resolved binary path only, with no argument-aware matching (confirmed via
   `openclaw approvals allowlist --help` — entries are bare glob paths like `/usr/bin/git`, no
   denylist concept). It genuinely cannot distinguish `git push origin main` from
   `git status`, or `npm publish` from `npm test`, at the binary-path level the daemon actually
   gates on. Excluding `git`/`npm` from the allowlist wholesale to force prod-deploy
   invocations to `ask` was evaluated and rejected — it would also force every benign,
   constant-use invocation of those tools to `ask`, an unacceptable usability regression. **This
   MUST NOT be described as fully enforced** in user-facing material; per-argument enforcement
   for allowlisted bins is deferred pending a daemon-side capability that does not exist today,
   and is tracked as a backlog item, not shipped behavior.
5. The full high-risk class list — name, description, pattern, and (for prod-deploy) which
   allowlisted bins it overlaps and therefore does not yet fully gate — **MUST** be visible,
   read-only, via `docket gates classes`. This command **MUST NOT** change any configuration.

## Interface Contracts

### `docket gates` command (implemented)

```bash
docket gates status            # MUST report exec-approval policy, routing, isolation, audit
docket gates enable [--force]  # MUST apply conservative exec-approval defaults + curated
                             #   allowlist and enable approval routing
docket gates disable           # MUST reset gate defaults + routing (reversible escape hatch)
docket gates isolate [on|off]  # MUST set/clear Docker workspace isolation (requires Docker; opt-in)
docket gates classes           # MUST list the documented high-risk action classes, read-only
docket install                 # MUST apply the gate configuration by default
docket install --no-gates      # MUST skip gate application (explicit opt-out)
docket doctor                  # MUST report whether security gates are configured
```

### Approval channels

```bash
# docket's approval store (production producer since Phase 15 G-1: core/dispatch.py's
# require_approval gate — see pod-dispatch.spec.md)
docket approve                 # List pending approvals in docket's store
docket approve <token>         # Grant a pending approval — headless, no chat session needed
                                #   (G-1: also resumes any dispatch task it gated)
docket deny <token>            # Deny a pending approval — headless, no chat session needed
                                #   (G-1: also fails any dispatch task it gated, terminally)
GET  /approvals                # docket serve: list pending approvals (bearer auth)
POST /approvals/<token>        # docket serve: {"action": "grant"|"deny"} (bearer auth)
                                #   (G-1: same resume/kill behavior as the CLI channel)

# the daemon's own gate prompt (what actually fires on a gated binary today)
/approve <id> allow-once|deny  # answered in the agent's chat session, daemon-side
                                #   — NOT bridged to docket's store yet (G-5, not implemented)
```

## Examples

### Gate flow today (daemon-enforced)

An agent invoking a non-allowlisted binary (e.g. `docker stop mywebsite-db`) is stopped by
the daemon's exec-approval gate; the prompt is delivered to the agent's session and answered
with the daemon's `/approve <id>` (or denied by `askFallback: deny` when nobody answers).
`git push origin main` does *not* trigger this prompt by default — see "High-risk action
classes" above for why.

### Approval flow — target state (daemon-gated; investigated by G-5, confirmed not practical today)

```text
[GATE] Agent 'mywebsite' requested: docker stop mywebsite-db
       Approve via: docket approve <token>  ·  docket deny <token>
       ·  POST /approvals/<token>  ·  or, if Telegram-bound, reply ✅/❌
       Times out in APPROVAL_TIMEOUT → denied.
```

This worked example would require the daemon-notify bridge that the G-5 spike investigated and
found **not practically buildable today** — see "The `[GATE]` seam — G-5 spike findings" above
for the evidence. No docket code emits a `[GATE]` line, and none is planned until OpenClaw
exposes a Python-reachable way to learn that a live exec-approval prompt exists. The example is
retained as the target contract only. **Do not cite it as shipped behavior.**

### Approval flow — shipped state (dispatch-gated, ROADMAP Phase 15 G-1)

This one *is* real today — narrower than the target state above (it gates a pod dispatch hop,
not an arbitrary daemon exec prompt), but genuinely end to end, store to task:

```text
$ docket pod myapp dispatch
  [task-9a1b2c3d-...] waiting_approval — approval required before implementer hop (token=apr-1234)

$ docket approve apr-1234
✓ Approval granted: apr-1234
  The waiting action may now proceed.

$ docket pod myapp dispatch
  [task-9a1b2c3d-...] done — 2 hop(s), $0.0091
```

An unanswered token fail-closes the same way: `approval_sweep_expired` (running only under
`docket serve`) resolves it to `denied` after `APPROVAL_TIMEOUT`, and the dispatch task fails
terminally (`failureKind: "approval_denied"`) without anyone calling `docket deny` at all. See
`pod-dispatch.spec.md` v2.1.0 for the full state-machine contract this flow is built on.

### High-risk action classes (implemented)

```text
$ docket gates classes
High-risk action classes

  Documented action classes considered especially consequential
  (money movement, prod deploys, secret access).

money-movement — Payment/financial operations: charges, refunds, payouts, transfers
  pattern: \bstripe\b|\bpaypal\b|\bbraintree\b|charge\s+customer|refund.*amount|...
  none of this class's bins are in the curated allowlist — always asks today

prod-deploy — Production deploys and release pushes
  pattern: git\s+push\s+.*\b(main|master|production|prod)\b|npm\s+publish|...
  overlaps curated allowlist bins: git, npm — daemon gates by binary path only, so these
  bins stay allowlisted; per-argument enforcement is not yet available (deferred)

secret-access — Secret/credential writes and key generation
  pattern: vault\s+(write|kv\s+put)|ssh-keygen|openssl\s+genrsa|...
  none of this class's bins are in the curated allowlist — always asks today
```

## Validation

### Pre-conditions

- The OpenClaw daemon **MUST** support tool-approval hooks for this to be enforceable.

### Post-conditions

- After a default install (no `--no-gates`), dangerous operations **MUST** be gated
  (daemon-enforced).
- Grants and denials through docket's approval store **MUST** appear in the audit log
  (`cli`/`http`/`timeout` channels). Daemon-side `/approve` responses write no docket audit
  entry until the G-5 bridge lands.
- A gate prompt with no approver **MUST** resolve to denied (daemon `askFallback: deny`).
  Stale docket-store records additionally resolve to **denied** (fail-closed, not merely
  "expire") while `docket serve` runs, and — since G-1 — a dispatch task waiting on such a
  record is failed terminally as part of that same resolution.

### Invariants

- A denied or timed-out request **MUST NOT** execute (enforced by the daemon for its own
  exec-approval prompt; enforced by `core/dispatch.py`'s `resolve_waiting_approval` for a G-1
  require_approval gate on a pod dispatch hop).
- Audit log entries **SHOULD NOT** be silently editable by the agent. As of ROADMAP Phase 15
  G-4, the log carries a `seq`/`prev_hash` tamper-evidence chain (`docket audit verify` detects
  an altered line) and the prior `DOCKET_NO_AUDIT=1` kill switch has been removed entirely — see
  audit.spec.md.
- A high-risk pattern match **MUST NOT** be bypassed by allowlist status in
  `resolve_command_action` for classes with no allowlist overlap (money-movement,
  secret-access) — those are fully enforced today. Prod-deploy's `git`/`npm` overlap **MUST
  NOT** be claimed as enforced until per-argument daemon support exists; it remains a
  documented policy only.
- A `waiting_approval` dispatch task **MUST NOT** be resumable by anything other than a grant
  resolving that exact token (see `pod-dispatch.spec.md`'s claim-eligibility invariant) — this
  spec does not duplicate that state machine, only the approval-store side of it.

## Changelog

### Version 0.5.0 (2026-07-30)

- **G-5 spike concluded: the `[GATE]` seam investigated, not bridged.** Investigated whether the
  OpenClaw daemon's native exec-approval prompt can notify an external hook that docket could
  bridge into its own `apr-*` token store. Verdict: **no** practical bridge exists today.
  `exec.approval.resolve` is a real, callable Gateway RPC method (verified against the installed
  `openclaw 2026.2.23` daemon; reachable via the existing `openclaw` CLI-subprocess pattern) —
  but there is no reachable way for docket to learn that a prompt exists in the first place: no
  working list/backfill method could be found under any plausible name (`exec.approval.list`,
  `exec.approvals.list`, `exec.approval.pending`, `exec.approvals.pending`, `approval.list`,
  `approvals.list`, `commands.list` — all `unknown method`) via `openclaw gateway call` against
  the real running daemon; the documented notification path (`exec.approval.requested` over a
  WebSocket operator session) has no Python SDK (only npm packages, which the docs themselves
  note may still be rolling out); the `admin-http-rpc` plugin explicitly excludes
  resolve/list-pending methods from its HTTP surface; and the plugin `before_tool_call` hook is a
  separate, independent approval system (`approvals.plugin`) that does not intercept native
  exec-approval prompts. The `[GATE]` worked example stays labeled target state (unchanged
  conclusion from 0.4.0) — this version adds the concrete, dated evidence trail behind that
  label so it reflects an actual investigation rather than an open question. No code shipped;
  this is a documentation-only update per the spike's own evidence standard (see ROADMAP Phase
  15 G-5).
- **ROADMAP Phase 15 G-1 — approval-gated dispatch: docket's approval store gets a real
  production producer.** Previously `approval_create` had zero production callers anywhere in
  the codebase; `core/dispatch.py`'s new require_approval gate (pre-hop in the pod dispatch
  pipeline — see `pod-dispatch.spec.md` v2.1.0) is that first producer. Updated to reflect what
  is now genuinely true, not just a future contract:
  - `docket approve`/`docket deny` and `POST /approvals/<token>` now genuinely resume or kill
    the dispatch task a gate stopped (`resolve_waiting_approval`), not merely flip the approval
    record's own state.
  - `approval_sweep_expired` resolves a stale pending record to **denied** (not the prior
    `"expired"` state) and, for a G-1-originated record, also fails the waiting dispatch task —
    so the sweep is no longer *purely* bookkeeping; it is real enforcement for docket's own
    require_approval gate specifically (the daemon's own exec-approval prompt still fail-closes
    entirely on its own `askFallback: deny`, unaffected by this change).
  - Added the `timeout` audit-log channel tag for the expiry sweep's own fail-closed denial.
  - Added a shipped "Approval flow" example (dispatch-gated) alongside the still-not-implemented
    daemon-gated target-state example, clearly distinguishing the two.
  - **What is still not true:** the G-5 daemon-gate bridge (the daemon's own exec-approval
    prompt minting an `apr-*` token) remains unimplemented — `docket approve` still cannot
    answer a *live daemon* gate. G-1's producer is scoped to pod dispatch hops only. Its only
    wired trigger source is a pod-level Lead-meta role list; a policy-match source (G-2) and a
    pipeline-step source (W-1/W-2) are documented, inert seams, not shipped.

### Version 0.4.1 (2026-07-30)

- Cross-reference update: the audit-log tamper-evidence invariant is no longer a known gap —
  ROADMAP Phase 15 G-4 shipped the `seq`/`prev_hash` hash chain, `docket audit verify`, and
  removed the `DOCKET_NO_AUDIT` kill switch entirely (see audit.spec.md v2.0.0). No change to
  this spec's own requirements — gates, routing, and isolation are unaffected.

### Version 0.4.0 (2026-07-30)

- **Approval-seam truth pass (Platformization baseline).** Documented that the daemon's
  exec-approval prompt and docket's `apr-*` approval store are two disconnected systems
  today: no production code creates docket-store records (`approval_create` has no
  production caller), so the CLI/HTTP channels cannot answer a live daemon gate. The
  `[GATE]` worked example is re-labeled **target state (Phase 15 G-5, daemon-gated)** —
  it was previously presented as implemented, which was wrong. Fail-closed is correctly
  attributed to the daemon's `askFallback: deny` (docket's expiry sweep is bookkeeping that
  runs only under `docket serve` and resolves to `expired`). Audit parity is scoped to the
  channels that reach docket's store (`cli`/`http`); the `telegram` tag is reserved for the
  G-5 bridge. The tamper-evidence invariant is downgraded to SHOULD with the known gap named
  (Phase 15 G-4). Gates themselves (exec-approval on by default, high-risk classes,
  isolation) are unchanged and remain accurate.

### Version 0.3.0 (2026-07-02)

- **Gates-default-on**: `docket install` now applies exec-approval gates by default;
  `--no-gates` is the explicit opt-out. Condition for the flip (headless approval routing) is
  met: the CLI (`docket approve`/`docket deny`) and HTTP (`serve.py` `GET/POST /approvals`)
  channels work without an interactive chat session, on top of the pre-existing Telegram
  channel.
- Documented the high-risk action-class policy (`core/security.py`'s `HIGH_RISK_PATTERNS`,
  `docket gates classes`) and its always-`ask` decision rule (`resolve_command_action`):
  money-movement and secret-access classes are fully enforced today (no allowlist overlap —
  those bins were never allowlisted, so any invocation already falls through to `ask`);
  prod-deploy's `git`/`npm` overlap is documented policy, not daemon-enforced, since the
  daemon's exec-allowlist gates by binary path only and can't distinguish
  `git push origin main` from `git status` — per-argument enforcement is deferred as a
  backlog item, not claimed as shipped. Added the read-only `docket gates classes` command to
  the interface contract with an example of its output.
- Documented audit-log parity: every approval grant/deny, on any channel, writes an
  `audit_log()` entry tagged with the channel (`cli`, `http`, `telegram`).
- Docker workspace isolation (`docket gates isolate on`) remains opt-in — unaffected by this flip.
- Fixed a pre-existing spec inconsistency: the gated-example used to be `git push origin main`,
  but `git` is on the curated allowlist — replaced with `docker stop`, with an explicit note
  that `git push` is not blocked by the base gate alone.

### Version 0.2.0 (2026-06-10)

- Implemented opt-in on native daemon primitives: `docket gates enable` / `isolate`,
  `docket install --gates`, and config-permission hardening
- Exec-approval enforcement (allowlist + ask/on-miss + deny fallback), Telegram approval
  routing (`approvals.exec`, `/approve`), and Docker workspace isolation
- `docket doctor` reports gate status, routing, isolation, and audit posture
- On-by-default in `docket install` deferred pending per-agent headless approval routing

### Version 0.1.0 (2026-06-09)

- Initial, spec-first definition of the intended security-gates design
- Explicitly marked Planned: install currently skips security configuration
