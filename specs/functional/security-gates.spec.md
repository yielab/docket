# Security Gates Specification

**Version**: 0.7.0
**Status**: Implemented (on by default for new installs; daemon-enforced — see the approval-seam note below). Docket's own approval store has two real production producers now (G-1's pod-level/pipeline-step gates, G-2's `pre_input` enqueue gate); `pre_output` has a real per-hop producer feeding `docket metrics`, and — since G-3 — also classifies hop output against the built-in high-risk class list; the daemon-gate bridge is confirmed **not available** today — the G-5 spike investigated it against a live daemon and concluded no practical bridge exists (see the approval-seam note and the G-5 findings section). `pre_tool_call` remains daemon-gated and unevaluated by docket, by design. G-3 also gave the high-risk classifier (`match_high_risk`) its first real, non-test callers, and deleted the three sibling helpers that never acquired any — see "High-risk action classes" below.
**Last Updated**: 2026-07-31

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
> exec-approval prompt for an arbitrary tool call. Three trigger sources feed this one gate: a
> pod-level Lead-meta role list (G-1), a pipeline `approval` step (W-1/W-2), and — since G-2 — a
> `pre_input` guardrail policy match evaluated once at task enqueue, not per hop (see "Policy
> engine on the live path" below and `pod-dispatch.spec.md`).
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
- The declarative guardrail policy engine (`core/policy.py`) and where its `pre_input`/
  `pre_output` hooks run on the live dispatch path (ROADMAP Phase 15 G-2)

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
2. On any path docket itself controls, a high-risk pattern match **MUST** take effect
   regardless of whether the invoked binary's resolved path is present in the curated
   allowlist — allowlist membership **MUST NOT** bypass a high-risk match. Both wired call
   sites satisfy this by construction: neither consults the allowlist at all, and
   `run_verify_cmd` refuses outright (a strictly stronger outcome than `ask`).

   > This requirement was previously expressed by a `resolve_command_action` helper that
   > returned `ask`/`allow` for a command string. That function was **deleted** when G-3
   > landed: it never acquired a production caller, because the ask/allow decision for a live
   > agent tool call belongs to the daemon's exec gate (D-15), which keys on binary path and
   > has no hook to consult docket. A never-called decision function in a security module is
   > the precise defect this phase existed to remove, so the requirement now constrains the
   > real paths instead of a helper nothing invoked.
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

### Docket-launched process classification (implemented, ROADMAP Phase 15 G-3)

Before this card, the `HIGH_RISK_PATTERNS` classifier had callers only in tests. A classifier
nothing calls is documentation, not enforcement — the same defect shape G-1 fixed for the
approval store and G-2 fixed for the policy engine. This section is what closes that gap for
the classifier itself, on the two paths docket actually controls.

`match_high_risk` is the surviving entry point. The three helpers that wrapped it —
`high_risk_bins`, `is_high_risk` and `resolve_command_action` — were deleted on merge rather
than left beside the wired one, since none of them gained a caller either (see the note under
requirement 2 above for why `resolve_command_action` in particular could never have one).

1. **Scope decision — which of docket's own subprocess calls are classification targets.**
   `edges/adapters/system.py` is the shell-out chokepoint (~11 `subprocess.run` call sites,
   plus `cli/_eval.py`'s `bash <script>`, `cli/_trace.py`'s `tail -f <file>`, and
   `cli/_install.py`'s `[python, --version]` probe). Of all of these, exactly **one** —
   `system.py`'s `run_verify_cmd` — launches a fully free-form, operator-composed command
   string through a real shell (`shell=True`); every other call site in this list builds a
   fixed argv list itself (a systemd unit name, `docker ps --format ...`, a `git -C <dir>
   rev-parse ...` plumbing call, a literal `[python, "--version"]` probe, a repo-relative
   `.eval.sh` path chosen from a fixed on-disk set, a `tail -f` on a trace file docket itself
   computed). None of those fixed-argv calls carry an arbitrary, classifiable command string —
   there is nothing there for `HIGH_RISK_PATTERNS` to match against that isn't already fully
   determined by docket's own code, and a `--version` probe is not a comparable risk surface to
   a shell-interpreted, operator-typed verify pipeline. `run_verify_cmd` **MUST** therefore be
   the only classification point in `edges/adapters/system.py`; the rest of the module's
   subprocess calls are explicitly out of scope for this requirement, not overlooked.
2. `edges/adapters/system.py`'s `run_verify_cmd` **MUST** classify its `cmd` argument against
   `core.security.match_high_risk` before starting the subprocess. A match **MUST** fail
   closed — the shell command **MUST NOT** be started at all — and the returned failure message
   **MUST** name the matched class and point at `docket gates classes`. Refusing outright is a
   stronger posture than routing to an approval prompt, and it is the only honest one available
   here: `run_verify_cmd` runs synchronously inside a dispatch hop with no interactive approver
   reachable to answer — the same posture the daemon's own `askFallback: deny` takes when nobody
   answers a live prompt.
3. `core/dispatch.py`'s `pre_output` guardrail scan (see "Policy engine on the live path" below)
   **MUST** also classify each hop's real output against `core.security.match_high_risk`,
   independently of the JSON policy engine — the shipped `high-risk-*.json` templates are
   hooked on `pre_tool_call`, which docket never evaluates (D-15: it is not inside a running
   turn to intercept a tool call), so without this, a hop that reports having run a
   money-movement or secret-access command trips nothing on the `pre_output` path at all.
4. A `HIGH_RISK_PATTERNS` match on a hop's output **MUST NOT** downgrade an already-stronger
   `policy_eval_detail` verdict (`redact`/`block`/`require_approval` all outrank a bare
   `allow`) — it **MUST** only raise a plain `allow` to `warn`. It **MUST NOT** go further than
   `warn`: there is no live approver to `ask` post-hoc (the hop has already run, the same
   reasoning behind `pre_output`'s require_approval-behaves-like-warn rule below), and
   `HIGH_RISK_PATTERNS` is a built-in Python list, not an installed, operator-authored JSON
   policy (FD-3 — not yet user-configurable) — so a match here **MUST NOT** be described as
   redacting or blocking anything by itself. It is a visibility signal (a `guardrail_check`
   trace event tagged `high-risk:<class-name>`), not an enforcement action, and **MUST NOT** be
   claimed as one in user-facing material.
5. **What remains advisory.** `pre_tool_call` interception (the daemon's own live tool-call
   gate) is unchanged by this card and remains out of scope per D-15 — G-3 does not make docket
   a per-argument enforcement daemon on the daemon's own exec path. The daemon's exec-allowlist
   itself still gates by binary path only (see "High-risk action classes" above); G-3 adds two
   new, real classification points under docket's *own* control, it does not change what the
   daemon enforces.

### Policy engine on the live path (implemented, ROADMAP Phase 15 G-2)

Before this card, `core/policy.py` was fully built and unit-tested (`policy_eval`, hooks,
actions, most-restrictive-wins ranking) but had exactly one caller anywhere: the CLI's own
dry-run printer, `docket policies test`. `docket install` never installed the six shipped
templates. `cli/_metrics.py` already shipped a reader for guardrail-trip trace events with no
producer anywhere. This section is what closes that gap — the same "built, tested, connected to
nothing" shape G-1 fixed for the approval store one card earlier.

1. `docket install` **MUST** install the baseline policy templates into `$POLICIES_DIR`
   (idempotent — an existing file is left untouched, never overwritten), via the same producer
   `docket policies init` uses (`core.policy.install_policies`). An empty `$POLICIES_DIR` makes
   every hook evaluation a no-op (`policy_eval` returns `allow` unconditionally), so this step is
   what makes the rest of this section possible at all, not an optional nicety.
2. The `pre_input` hook **MUST** be evaluated exactly once per task, at
   `core.dispatch.enqueue_task` time, against the task's raw description (role `"lead"` — the
   pipeline's fixed entry point). It **MUST NOT** be re-evaluated before every subsequent hop —
   doing so would re-trip the same `"*"`-scoped policy at every role in the pipeline for what is
   really one piece of incoming text, demanding a fresh human decision per hop instead of one at
   the door.
   - `block` **MUST** reject the task before it is ever written to the pod's queue
     (`DispatchError`; nothing persisted) and **MUST** close out a self-contained trace session
     (`session_start` → `guardrail_check` → `guardrail_block` → `session_end`, status `aborted`) —
     a rejected task is never dispatched, so nothing else will ever terminate that trace file, and
     an unterminated file is invisible to `cli/_metrics.py`'s terminal-session reader.
   - `require_approval` **MUST** persist the task straight into `waiting_approval` with a real
     `core/approval.py` record (`context: {"taskId", "pipelineIndex": 0}`) — the exact same
     resolution path G-1 already built for its pre-hop gate (grant → `pending` + a hop-0 gate
     override; deny → terminal `failureKind: "approval_denied"`), fed from a second source.
   - `redact` **MUST** scrub the stored task description (`core/trace.py`'s `redact()`) before it
     is ever persisted to the queue file.
   - `warn`/`allow` **MUST NOT** change task status or stored description; `warn` **MUST** still
     emit a `guardrail_check` trace event.
3. The `pre_output` hook **MUST** be evaluated on **every** hop's real output, inside
   `core.dispatch.dispatch_task`, after the agent turn returns and before that output is embedded
   in the carried-forward `HandoffArtifact` or the persisted `HopResult`.
   - `redact` **MUST** scrub the hop's output in place before it is stored or handed to the next
     hop.
   - `block` **MUST** fail the hop the same way a failed agent turn does (the pipeline stops
     there; later hops **MUST NOT** run).
   - `warn`/`allow` **MUST** pass the output through unchanged.
   - `require_approval` is **not** a `pre_output` outcome: a hop has already run by the time its
     output exists, so there is no "before the hop" moment left to gate — an operator who wants a
     human in the loop before a role runs uses the pod-level `requireApprovalRoles` gate or the
     `pre_input` enqueue gate instead. A `pre_output` policy declaring `require_approval` **MUST**
     behave exactly like `warn` (logged, not gated) rather than raise or silently do nothing.
   - Since ROADMAP Phase 15 G-3, this same evaluation **MUST** also classify the hop's output
     against `core.security.match_high_risk` (see "Docket-launched process classification"
     above) — a match raises a bare `allow` to `warn` but **MUST NOT** downgrade or override an
     already-stronger `policy_eval_detail` verdict.
4. Every non-`allow` verdict on either hook **MUST** emit a `guardrail_check` trace event
   (`payload: {hook, policy, action}`) — a pure audit trail, visible via `docket trace`. A `block`
   verdict **MUST** additionally emit `guardrail_block`, with `payload.action` set to the
   *tripped policy's id* (not the literal word `"block"`) — this is the shape
   `cli/_metrics.py`'s existing "Guardrail trips" reader keys its tally on
   (`payload.get("action", event_type)`), so trips are bucketed by which policy fired, not
   collapsed into one undifferentiated row. `guardrail_check` is deliberately **not** tallied by
   that reader — tallying both would double-count the same trip a `block` already reports via
   `guardrail_block`.
5. `pre_tool_call` (in-turn — a tool call attempted *inside* a running agent turn) **MUST
   remain daemon-gated** and **MUST NOT** be evaluated by docket at any point in this flow —
   docket orchestrates hops between turns; it is not inside a turn to intercept a tool call
   (ROADMAP §4.5, D-15). The shipped `block-destructive`/`high-risk-*` templates use this hook
   and are therefore schema-valid, dry-run-testable content with no live-path enforcement yet —
   see G-3 (deferred, blocked on this card landing first).
6. `docket policies validate [id|file.json]` **MUST** wire `core.policy.validate_policy` — a
   schema check (required fields, valid hook/action, a compilable regex pattern) previously
   implemented and unit-tested but callable only from tests, not the CLI. No argument validates
   every file in `$POLICIES_DIR`; an argument is looked up first as a file path, then as an
   installed policy's `id`. Exit code `1` if any checked file is invalid.

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

### `docket policies` command (implemented, ROADMAP Phase 15 G-2)

```bash
docket policies list                        # MUST list installed policies (id/hook/action/description)
docket policies show <id>                   # MUST print one installed policy's raw JSON
docket policies init                        # MUST seed $POLICIES_DIR from the shipped templates
                                             #   (idempotent; same producer docket install's own
                                             #   policy step uses)
docket policies test <hook> <role> "<text>" # MUST dry-run the evaluator (no trace emitted)
docket policies validate [id|file.json]     # MUST schema-check installed policies, one, or a file
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

### Policy engine flow — enqueue-time gate (implemented, ROADMAP Phase 15 G-2)

A `require_approval` policy match on a task's description gates it before it is ever claimable —
same resolution path as the G-1 example above, fed from a second source:

```text
$ docket pod myapp delegate "URGENT WIRE the vendor before EOD"
✓ Queued for pod 'myapp': [task-9a1b2c3d-...] URGENT WIRE the vendor before EOD

$ docket pod myapp queue
  [task-9a1b2c3d-...] waiting_approval — URGENT WIRE the vendor before EOD

$ docket approve apr-5678
✓ Approval granted: apr-5678

$ docket pod myapp dispatch
  [task-9a1b2c3d-...] done — 2 hop(s), $0.0064
```

A `block` match never reaches the queue at all — the CLI reports the rejection immediately and
nothing is persisted:

```text
$ docket pod myapp delegate "wipe the prod database tonight"
✗ task rejected by guardrail policy 'no-wipes' at enqueue: absolutely not
```

`docket metrics` reads its "Guardrail trips" tally from exactly the `guardrail_block` events
either flow (this one, or a `pre_output` block mid-dispatch) produces:

```text
$ docket metrics
docket metrics  (window: 12 terminal sessions)

  Success rate   83.3%  (10 success / 2 failure / 0 aborted)
  ...
  Guardrail trips:
    no-wipes                       1
    forbidden-marker               1
```

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

  This seed list is intentionally small and built-in (not yet user-configurable).
  Wired (G-3): docket's own run_verify_cmd refuses a matching verify command outright
  (fails closed, never runs it); a hop's real output is also scanned for a match on
  every pipeline step (pre_output) — a hit is logged, not blocked/redacted by itself.
```

### Docket-launched process classification — examples (implemented, ROADMAP Phase 15 G-3)

A verify command matching a high-risk class is refused before the shell ever starts:

```text
$ docket pod myapp add --verify "stripe charge customer --amount 500 && uv run pytest"
$ docket pod myapp dispatch
  [task-...] failed — verifyCmd failed: 'stripe charge customer --amount 500 && uv run pytest'
```

The task's trace records a `verification_failed` event whose `output` names the matched class:
`[verify command refused: matches high-risk class 'money-movement' (Payment/financial
operations: charges, refunds, payouts, transfers) -- see \`docket gates classes\`]` — the
subprocess is never started, not merely reported as failing.

A hop that reports having run a high-risk command is flagged, not blocked, on the `pre_output`
path (no installed JSON policy also matched here, so the built-in classifier's `warn` floor is
what fires):

```text
$ docket trace myapp <session-id>
  ... guardrail_check  {"hook": "pre_output", "policy": "high-risk:secret-access", "action": "warn"}
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
- A high-risk pattern match **MUST NOT** be bypassed by allowlist status on any path docket
  controls. For classes with no allowlist overlap (money-movement, secret-access) this is
  fully enforced today. Prod-deploy's `git`/`npm` overlap **MUST NOT** be claimed as enforced
  until per-argument daemon support exists; it remains a documented policy only.
- A task rejected by a `pre_input` `block` policy **MUST NOT** be written to the pod's queue —
  `enqueue_task` **MUST** raise before the locked read-modify-write, not after. A `pre_output`
  `block` **MUST NOT** let a later pipeline step run — the hop that tripped it **MUST** be the
  task's last recorded hop when it fails.
- `pre_tool_call` **MUST NOT** be evaluated by any code path this specification governs — it is
  the one hook that would require docket to intercept a call *inside* a running agent turn, which
  ROADMAP §4.5/D-15 places out of scope until a daemon-side interception point exists.
- A `waiting_approval` dispatch task **MUST NOT** be resumable by anything other than a grant
  resolving that exact token (see `pod-dispatch.spec.md`'s claim-eligibility invariant) — this
  spec does not duplicate that state machine, only the approval-store side of it.
- A verify command matching a `HIGH_RISK_PATTERNS` class **MUST NOT** be started as a subprocess
  at all (`edges/adapters/system.py`'s `run_verify_cmd` fails closed before calling
  `subprocess.run`) — this is a real behavior change, not documentation, and **MUST** be
  provable by a test that asserts `subprocess.run` is never invoked for a high-risk `cmd`.
- A `HIGH_RISK_PATTERNS` match on a hop's real output **MUST NOT** be described as blocking or
  redacting anything by itself — it is a `guardrail_check`-visible classification signal only
  (ROADMAP Phase 15 G-3), layered underneath whatever the installed JSON policy engine already
  decided, never on top of it.

## Changelog

### Version 0.7.0 (2026-07-31)

- **ROADMAP Phase 15 G-3 — high-risk classes enforced on docket-launched processes.** Before
  this card, `core/security.py`'s `HIGH_RISK_PATTERNS` classifier had callers only in tests
  (`test_m5_gates_policy.py`) — plus prose in this spec. A classifier nothing calls is
  documentation, not enforcement, the same defect shape G-1 fixed for the approval store and G-2
  fixed for the policy engine. Closed on two real paths:
  - `edges/adapters/system.py`'s `run_verify_cmd` — the one docket-launched subprocess built
    from a fully free-form, operator-composed command string run through a real shell — now
    classifies `cmd` against `match_high_risk` before ever calling `subprocess.run`. A match
    fails closed: the shell command is never started, and the returned failure message names the
    matched class. Every other subprocess call site audited for this card (`system.py`'s
    remaining ~10 `subprocess.run` calls, plus `cli/_eval.py`'s `bash <script>`, `cli/_trace.py`'s
    `tail -f`, `cli/_install.py`'s `[python, --version]`) builds a fixed argv list itself with no
    arbitrary command string to classify, and is explicitly out of scope — see "Docket-launched
    process classification" for the full per-site reasoning.
  - `core/dispatch.py`'s `pre_output` guardrail scan (G-2) now also classifies each hop's real
    output against the same built-in list, independently of the JSON policy engine (whose shipped
    `high-risk-*.json` templates are hooked on `pre_tool_call`, which docket never evaluates —
    D-15). A match raises a bare `allow` to `warn` and is visible via the existing
    `guardrail_check` trace event (`policy: "high-risk:<class-name>"`); it never downgrades an
    already-stronger policy verdict and never redacts or blocks by itself.
  - **What remains advisory, unchanged by this card.** The daemon's own exec-allowlist still
    gates by binary path only — a live agent's `git push origin production` is still not
    daemon-blocked, exactly as documented under "High-risk action classes" above. `pre_tool_call`
    interception is still out of scope (D-15). This card wires the classifier onto two paths
    docket itself controls; it does not make docket a per-argument enforcement daemon over the
    OpenClaw exec gate.
  - `docket gates classes` now also prints where the classifier is actually wired (no
    configuration surface added, read-only command unchanged in shape).
  - **Three sibling helpers deleted on merge:** `high_risk_bins`, `is_high_risk` and
    `resolve_command_action`. Wiring the classifier revealed that only `match_high_risk` had a
    place to be called from. `resolve_command_action` in particular could never acquire one: it
    resolved `ask` vs `allow` for a live command string, and that decision belongs to the
    daemon's exec gate (D-15), which keys on binary path and has no hook to consult docket.
    `is_high_risk` had no caller but `resolve_command_action`; `high_risk_bins` had none at all,
    since `docket gates classes` walks `cls.bins` directly. Leaving a never-called ask/allow
    resolver in a security module would have reproduced, one function over, the exact defect
    this card was written to remove. The policy they described is unchanged and still published
    by `docket gates classes` and by this spec; the affected tests now exercise
    `match_high_risk`/`HIGH_RISK_PATTERNS` directly rather than being deleted with the helpers.

### Version 0.6.0 (2026-07-30)

- **ROADMAP Phase 15 G-2 — policy engine on the live path.** Before this card, `core/policy.py`
  was fully built and unit-tested but had exactly one caller anywhere: the CLI's own dry-run
  printer (`docket policies test`). `docket install` never installed the six shipped templates.
  `cli/_metrics.py` shipped a "Guardrail trips" reader with no producer anywhere. Deferred twice
  before this wave — the same "built, tested, connected to nothing" shape G-1 fixed for the
  approval store one card earlier. Added:
  - `docket install`'s new Step 9 installs the baseline policy templates (idempotent, the same
    `core.policy.install_policies` producer `docket policies init` now also calls — the two could
    not previously drift on what "installed" means since they were two separate copies of the
    same copy-loop; now there is one).
  - `pre_input` is evaluated once, at `core.dispatch.enqueue_task` time — `block` rejects before
    the task is ever queued (closing its own self-contained trace session so the rejection is
    still visible to `docket metrics`); `require_approval` persists straight into
    `waiting_approval` with a real G-1-shaped approval record (grant/deny resolve exactly like a
    pre-hop gate); `redact` scrubs the stored description. This is deliberately a *single*
    evaluation, not a per-hop one — seeded `core.dispatch._policy_requires_approval` looked like
    the obvious wiring point (its docstring said so explicitly) but checking the same task text
    before every hop would re-trip a `"*"`-scoped policy once per role instead of once per task;
    that function's docstring now explains the decision instead of pointing at an open seam.
  - `pre_output` is evaluated on every hop's real output inside `core.dispatch.dispatch_task`,
    before it is embedded in the carried-forward `HandoffArtifact`/persisted `HopResult`: `redact`
    scrubs in place, `block` fails the hop (stopping the pipeline) the same way a failed agent
    turn does, `warn`/`allow` pass the text through. `require_approval` on this hook behaves like
    `warn` — a hop has already run by the time its output exists, so there is no "before the hop"
    moment left to gate.
  - `guardrail_check`/`guardrail_block` trace events are now real, on every non-`allow` hit.
    `guardrail_block`'s `payload.action` is set to the *tripped policy's id*, matching
    `cli/_metrics.py`'s existing `payload.get("action", event_type)` tally convention — the
    reader needed no changes, only a producer, so its shape is honored rather than replaced.
    `guardrail_check` is intentionally not tallied by that reader (it would double-count the same
    trip `guardrail_block` already reports); it remains a pure `docket trace` audit signal.
  - `pre_tool_call` stays daemon-gated and unevaluated by this module, unchanged from every prior
    version of this spec — G-2 did not expand what's claimed as enforced there.
  - `docket policies validate [id|file.json]` now wires `core.policy.validate_policy` (CL-2 had
    left it tested-but-unwired specifically to avoid a completions-golden diff on a
    no-behavior-change cleanup card). This card adds new CLI surface deliberately, so
    `completions_bash.golden`/`completions_zsh.golden` were regenerated — the only diff in either
    file is `validate` appended to the `policies|policy` subcommand list.
  - **What is still not true:** per-hop policy-driven approval (the seam
    `_policy_requires_approval` was originally meant to fill) is not wired — see above for why
    that turned out to be the wrong shape. G-3 (high-risk classes enforced on docket-launched
    processes, including this card's `pre_output` scan) remains a separate, still-open card.

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
