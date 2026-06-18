# Audit Log Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-13

## Purpose

This specification defines the audit log that records every mutating docket operation —
who changed what, and when — and the `docket audit` command that displays it. The audit
trail answers "what changed this agent/binding/key, and when" without granting access
to any secret material.

## Scope

This specification covers:

- The `audit_log` helper called by every mutating command
- The on-disk JSONL format and its permissions
- Viewing the log (`docket audit [N]`, `docket audit --json`)
- The opt-out switch (`DOCKET_NO_AUDIT=1`)

This specification does NOT cover the daemon's own security audit
(see security-gates.spec.md).
It also does NOT cover cost accounting (see cost-tracking.spec.md).

## Requirements

### Recording (audit_log helper)

1. Every mutating operation **MUST** append one JSON line via
   `audit_log <action> [detail]` — at minimum: key changes (`keys.*`), gate changes
   (`gates.*`), model/profile changes (`profile.*`, `models.*`), scope changes
   (`scope.*`), and agent lifecycle (`agent.add`, `agent.delete`).
2. `action` **MUST** be a dotted verb (e.g. `keys.add`, `models.preset`); `detail`
   **MUST** be a human-readable target (an id, key NAME, model id). Secret VALUES
   **MUST NOT** ever be written to the log.
3. Each entry **MUST** record `ts` (UTC ISO-8601), `user`, `pid`, `action`, and `detail`.
4. The log file **MUST** live at `$OPENCLAW_DIR/audit.log` and **MUST** be created with
   mode `0600`.
5. `DOCKET_NO_AUDIT=1` **MUST** disable recording entirely.
6. Recording **MUST** be best-effort: a missing `python3`, missing directory, or write
   failure **MUST NOT** fail the calling command.

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
{"ts": "2026-06-13T08:00:00Z", "user": "alice", "pid": 12345,
 "action": "models.preset", "detail": "openai"}
```

### Return Codes

- `0`: Success (including "no log yet")

## Examples

### Recording and viewing changes

```bash
$ docket keys add ANTHROPIC_API_KEY sk-...
$ docket profile mywebsite anthropic/claude-opus-4-6

$ docket audit 2
  2026-06-13T08:00:00Z  alice       keys.add          ANTHROPIC_API_KEY
  2026-06-13T08:00:11Z  alice       profile.model     mywebsite=anthropic/claude-opus-4-6
```

## Validation

### Pre-conditions

- None — the command works with or without an existing log.

### Post-conditions

- After a mutating command, the log contains exactly one new line describing it.

### Invariants

- The log file is always `0600`.
- No secret value ever appears in the log.
- Audit failures never break the mutating command that triggered them.

## Changelog

### Version 1.0.0 (2026-06-13)

- Initial audit-log specification (helper, JSONL schema, `docket audit` viewer,
  `DOCKET_NO_AUDIT` opt-out); documents behavior shipped in Phase 4
