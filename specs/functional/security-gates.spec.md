# Security Gates Specification

**Version**: 0.4.1
**Status**: Implemented (on by default for new installs; daemon-enforced — see the approval-seam note below)
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
> **The approval seam (honesty note, 2026-07-30).** There are two approval systems in play and
> they are **not yet bridged**: (a) the **daemon's** exec-approval prompt — the thing that
> actually fires when a gated binary is invoked — which is delivered to the agent's chat
> session and answered with the daemon's own `/approve <id>` mechanism; and (b) **docket's**
> approval store (`apr-*` tokens under `$APPROVALS_DIR`), which the CLI/HTTP channels above
> read and write. Today **no production code creates records in docket's store** (`approval_create`
> has no production caller): the daemon's gate prompt does not mint an `apr-*` token, so
> `docket approve` cannot answer a live daemon gate. Bridging the two is tracked as ROADMAP
> Phase 15 G-5 (daemon-gated spike); docket's store gains its first production producer in
> Phase 15 G-1 (approval-gated dispatch).
>
> **Why on-by-default is still safe:** the fail-closed property for an unattended agent is the
> daemon's own `askFallback: deny` — a prompt nobody answers is denied by the daemon, full
> stop. docket's `approval_sweep_expired` additionally expires stale store records after
> `APPROVAL_TIMEOUT`, but that sweep runs only while `docket serve` is up and marks records
> `expired`; it is bookkeeping on docket's store, not the enforcement mechanism.

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
   (see the approval-seam note above).
3. A gate prompt with no approver **MUST** fail closed. This is enforced by the daemon's
   `askFallback: deny`. Additionally, stale records in docket's store expire (state
   `expired`) after `APPROVAL_TIMEOUT` via `approval_sweep_expired` — which runs only while
   `docket serve` is up and is bookkeeping, not enforcement.
4. Every grant and denial **through docket's approval store MUST** be recorded in the audit
   log (`audit_log("approval.grant"|"approval.deny", ...)`), tagged with the channel it came
   through (`cli`, `http`). The `telegram` tag is reserved for the G-5 bridge: today a
   daemon-side `/approve` writes **no** docket audit entry.

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
# docket's approval store (no production producer yet — first producer: Phase 15 G-1)
docket approve                 # List pending approvals in docket's store
docket approve <token>         # Grant a pending approval — headless, no chat session needed
docket deny <token>            # Deny a pending approval — headless, no chat session needed
GET  /approvals                # docket serve: list pending approvals (bearer auth)
POST /approvals/<token>        # docket serve: {"action": "grant"|"deny"} (bearer auth)

# the daemon's own gate prompt (what actually fires on a gated binary today)
/approve <id> allow-once|deny  # answered in the agent's chat session, daemon-side
```

## Examples

### Gate flow today (daemon-enforced)

An agent invoking a non-allowlisted binary (e.g. `docker stop mywebsite-db`) is stopped by
the daemon's exec-approval gate; the prompt is delivered to the agent's session and answered
with the daemon's `/approve <id>` (or denied by `askFallback: deny` when nobody answers).
`git push origin main` does *not* trigger this prompt by default — see "High-risk action
classes" above for why.

### Approval flow — target state (daemon-gated, NOT implemented; ROADMAP Phase 15 G-5)

```text
[GATE] Agent 'mywebsite' requested: docker stop mywebsite-db
       Approve via: docket approve <token>  ·  docket deny <token>
       ·  POST /approvals/<token>  ·  or, if Telegram-bound, reply ✅/❌
       Times out in APPROVAL_TIMEOUT → denied.
```

This worked example requires the G-5 bridge (daemon gate prompt → docket `apr-*` token).
No docket code emits a `[GATE]` line today; the example is retained as the target contract
only. **Do not cite it as shipped behavior.**

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
  (`cli`/`http` channels). Daemon-side `/approve` responses write no docket audit entry
  until the G-5 bridge lands.
- A gate prompt with no approver **MUST** resolve to denied (daemon `askFallback: deny`).
  Stale docket-store records additionally expire while `docket serve` runs.

### Invariants

- A denied or timed-out request **MUST NOT** execute (enforced by the daemon).
- Audit log entries **SHOULD NOT** be silently editable by the agent. As of ROADMAP Phase 15
  G-4, the log carries a `seq`/`prev_hash` tamper-evidence chain (`docket audit verify` detects
  an altered line) and the prior `DOCKET_NO_AUDIT=1` kill switch has been removed entirely — see
  audit.spec.md.
- A high-risk pattern match **MUST NOT** be bypassed by allowlist status in
  `resolve_command_action` for classes with no allowlist overlap (money-movement,
  secret-access) — those are fully enforced today. Prod-deploy's `git`/`npm` overlap **MUST
  NOT** be claimed as enforced until per-argument daemon support exists; it remains a
  documented policy only.

## Changelog

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
