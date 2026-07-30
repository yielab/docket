# Audit Log Specification

**Version**: 1.1.0
**Status**: Partially implemented (viewer + format complete; recording coverage is partial — see Requirements)
**Last Updated**: 2026-07-30

## Purpose

This specification defines the audit log that records mutating docket operations —
who changed what, and when — and the `docket audit` command that displays it. The audit
trail answers "what changed this agent/binding/key, and when" without granting access
to any secret material.

## Scope

This specification covers:

- The `audit_log` helper and which operations actually call it today
- The on-disk JSONL format and its permissions
- Viewing the log (`docket audit [N]`, `docket audit --json`)
- The opt-out switch (`DOCKET_NO_AUDIT=1`)

This specification does NOT cover the daemon's own security audit
(see security-gates.spec.md).
It also does NOT cover cost accounting (see cost-tracking.spec.md).

## Requirements

### Recording (audit_log helper)

1. **Implemented action families (recorded today):**
   - `gates.enable` / `gates.disable` / `gates.isolate` (`cli/_gates.py`)
   - `approval.grant` / `approval.deny`, with a channel tag (`core/approval.py`)
   - `auth.setup` (`cli/_install.py`)
2. **Planned action families (NOT recorded today — tracked as ROADMAP Phase 15 G-4):**
   key changes (`keys.*`), model/profile changes (`profile.*`, `models.*`), scope
   changes (`scope.*`), and agent lifecycle (`agent.add`, `agent.delete`, `pod.*`,
   `persona.*`). Until G-4 lands, these mutations write **no** audit entry; this spec
   MUST NOT be cited as evidence that they do.
3. `action` **MUST** be a dotted verb (e.g. `gates.enable`, `approval.grant`); `detail`
   **MUST** be a human-readable target (an id, key NAME, model id). Secret VALUES
   **MUST NOT** ever be written to the log.
4. Each entry **MUST** record `ts` (UTC ISO-8601), `user`, `pid`, `action`, and `detail`.
5. The log file **MUST** live at `$OPENCLAW_DIR/audit.log` and **MUST** be created with
   mode `0600`.
6. `DOCKET_NO_AUDIT=1` disables recording entirely. **Known limitation:** this is an
   unauthenticated environment switch, and the log has no tamper evidence (no hash
   chain or sequence numbers) — both are Phase 15 G-4 work items. Until then the log
   is an operational convenience, not a security control.
7. Recording **MUST** be best-effort: a missing directory or write failure
   **MUST NOT** fail the calling command.

### Viewing (docket audit)

1. `docket audit [N]` **MUST** print the last N entries (default 20) as a human-readable
   table of timestamp, user, action, and detail. A non-numeric argument **MUST** fall
   back to the default count.
2. `docket audit --json` **MUST** emit the raw JSONL unmodified (stable for scripting).
3. When no log exists yet, the command **MUST** explain where entries will be recorded
   and exit 0.
4. Malformed lines **MUST** be skipped, never crash the display.

## Interface Contracts

### CLI Command Signatures

```bash
docket audit            # Last 20 changes, human-readable
docket audit <N>        # Last N changes
docket audit --json     # Raw JSONL passthrough
```

### Entry Schema (one JSON object per line)

```json
{"ts": "2026-07-30T08:00:00Z", "user": "alice", "pid": 12345,
 "action": "approval.grant", "detail": "token=apr-… project=mywebsite channel=cli"}
```

### Return Codes

- `0`: Success (including "no log yet")

## Examples

### Recording and viewing changes

```bash
$ docket gates enable
$ docket approve apr-1234…

$ docket audit 2
  2026-07-30T08:00:00Z  alice       gates.enable      fleet
  2026-07-30T08:00:11Z  alice       approval.grant    token=apr-1234… channel=cli
```

## Validation

### Pre-conditions

- None — the command works with or without an existing log.

### Post-conditions

- After a mutating command **in an implemented action family** (Requirement 1), the log
  contains exactly one new line describing it. Mutations in the planned families
  (Requirement 2) currently write nothing.

### Invariants

- The log file is always `0600`.
- No secret value ever appears in the log.
- Audit failures never break the mutating command that triggered them.

## Changelog

### Version 1.1.0 (2026-07-30)

- Truth pass (Platformization baseline): Status downgraded from Complete to Partially
  implemented. Requirement 1 now lists only the action families that actually record
  (`gates.*`, `approval.grant/deny`, `auth.setup`); the previously claimed `keys.*`,
  `profile.*`, `models.*`, `scope.*`, `agent.add/delete` coverage is explicitly marked
  unimplemented and tracked as ROADMAP Phase 15 G-4, together with tamper evidence and
  the `DOCKET_NO_AUDIT` hardening. Example updated to entries the code can produce.

### Version 1.0.0 (2026-06-13)

- Initial audit-log specification (helper, JSONL schema, `docket audit` viewer,
  `DOCKET_NO_AUDIT` opt-out); documents behavior shipped in Phase 4
