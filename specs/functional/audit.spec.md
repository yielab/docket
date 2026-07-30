# Audit Log Specification

**Version**: 2.1.0
**Status**: Implemented (recording coverage, tamper evidence, rotation, and the kill-switch
removal below are all shipped; `models.*` and a future `runs.cancel` remain tracked gaps — see
Requirements)
**Last Updated**: 2026-07-30

## Purpose

This specification defines the audit log that records mutating docket operations —
who changed what, and when — the tamper-evidence chain that lets an operator detect
if a line was altered after the fact, and the `docket audit` command family that
displays and verifies it. The audit trail answers "what changed this agent/binding/
key, and when" without granting access to any secret material.

## Scope

This specification covers:

- The `audit_log` helper and which operations call it
- The on-disk JSONL format, its permissions, and its tamper-evidence hash chain
- Size-capped rotation and the verification boundary it creates
- Viewing the log (`docket audit [N]`, `docket audit --json`) and verifying its
  chain (`docket audit verify`)
- Why there is no environment kill switch

This specification does NOT cover the daemon's own security audit
(see security-gates.spec.md).
It also does NOT cover cost accounting (see cost-tracking.spec.md).

## Requirements

### Recording (audit_log helper)

1. **Implemented action families:**
   - `gates.enable` / `gates.disable` / `gates.isolate` (`cli/_gates.py`)
   - `approval.grant` / `approval.deny`, with a channel tag (`core/approval.py`)
   - `auth.setup` (`cli/_install.py`)
   - `keys.add` / `keys.rotate` / `keys.remove` (`cli/_keys.py`, including the
     `docket keys setup` wizard's per-key adds/rotations)
   - `profile.model` / `profile.budget` / `profile.resume` (`cli/__init__.py`'s `profile`
     command; `profile.resume` is ROADMAP Phase 14 R-5's auto-pause clear)
   - `scope.set` / `scope.reset` (`cli/__init__.py`'s `scope` command)
   - `agent.add` — both the interactive pod flow (`docket add`, `cli/_agents.py`'s
     `run_add`) and the declarative flow (`docket add --from <spec>`,
     `_provision_agent`)
   - `agent.delete` — both a single non-pod agent (`run_delete`) and a whole pod
     teardown (`cli/__init__.py`'s `_delete_pod`, one line per pod summarizing all
     removed members)
   - `pod.add` / `pod.remove` (`cli/_pod.py`'s `_pod_add`/`_pod_remove`) — an
     `add --count N` call writes exactly one line naming every member created
   - `pod.set-verify` (`cli/_pod.py`'s `_pod_set_verify`, and `_pod_add` when `--verify` is
     passed) — ROADMAP Phase 14 R-6; names the member and the (validated) command being set,
     never the raw command's stdout
   - `persona.set` / `persona.clear` (`cli/__init__.py`'s `persona` command)
   - `mcp.<tool>` (`cli/_mcp.py`, ROADMAP Phase 18 L-3) — **every** `docket mcp serve` tool call
     (`status`, `pods`, `queue`, `delegate`, `dispatch`, `runs`, `approvals_list`,
     `approvals_grant`, `approvals_deny`, `cost`) writes one entry unconditionally, before the
     underlying operation runs — including the six read-only tools, which have no other
     mutating-command analogue in this list. A mutating tool (`delegate`, `dispatch`,
     `approvals_grant`/`approvals_deny`) additionally triggers whatever domain-specific entry the
     `core/` function it calls already writes (e.g. `approval.grant` tagged `channel=mcp`) — two
     entries for one call is intentional, not a duplicate bug: the `mcp.*` line is the uniform
     "an MCP call happened" record, the domain line is the same record any other channel producing
     that same effect would write. See `specs/api/mcp-server.spec.md`.
2. **Tracked gaps (NOT recorded — out of this version's scope):** role→model
   policy changes (`docket models set/preset/reset`) and a future `docket runs
   cancel` (Phase 16 — the run registry these would cancel does not exist yet).
   Both stay tracked as ROADMAP Phase 15 G-4 follow-up; this spec MUST NOT be
   cited as evidence that they record today.
3. `action` **MUST** be a dotted verb (e.g. `gates.enable`, `approval.grant`); `detail`
   **MUST** be a human-readable target (an id, key NAME, model id). Secret VALUES
   **MUST NOT** ever be written to the log.
4. Each entry **MUST** record `ts` (UTC ISO-8601, millisecond resolution — see
   Requirement 8), `user`, `pid`, `action`, `detail`, and the tamper-evidence
   fields `seq` and `prev_hash` (Requirement 9).
5. The log file **MUST** live at `$OPENCLAW_DIR/audit.log` and **MUST** be created with
   mode `0600`.
6. Recording **MUST** be best-effort: a missing directory or write failure
   **MUST NOT** fail the calling command.
7. **There is no environment kill switch.** A prior `DOCKET_NO_AUDIT=1` escape
   hatch has been removed entirely — it was an unauthenticated way to silently
   disable the only tamper record docket keeps, indistinguishable from the
   daemon simply not running any mutating commands. What survives from that
   contract is Requirement 6's best-effort property (recording still cannot
   crash a command); the switch itself is gone, not gated behind a TTY prompt
   (a prompt would force `core/audit.py`, and any `core/` caller such as
   `core/approval.py`, into interactive I/O — a layering violation of the
   "core never imports ui.py or prints" rule). `core/trace.py`'s sibling
   `DOCKET_NO_TRACE=1` switch is unaffected by this decision and continues to
   exist for the separate trace-event store; its suppressed-write return value
   was corrected in the same change (Requirement 10) but the switch itself was
   out of this card's scope.
8. Timestamps **MUST** be millisecond resolution
   (`YYYY-MM-DDTHH:MM:SS.mmmZ`) — second resolution collided under
   scripted/rapid-fire use (e.g. a declarative `docket add --from spec.json`
   provisioning several agents inside one process).
9. **Tamper evidence.** Every entry **MUST** carry a monotonically increasing
   `seq` (integer, starting at 1) and a `prev_hash` — the SHA-256 hex digest
   (stdlib `hashlib`, no new dependency) of the immediately preceding entry's
   canonical JSON form (`json.dumps(entry, sort_keys=True, separators=(",",
   ":"))`). The first entry of a chain **MUST** use the sentinel
   `prev_hash="0"*64` (`GENESIS_HASH`). A **chain restart** — starting a fresh
   `seq=1`/`GENESIS_HASH` entry rather than continuing the previous chain — is
   the correct, honest behavior (not a defect) in three cases: (a) the log is
   missing or empty, (b) the immediately preceding line predates this
   requirement and carries no `seq`/`prev_hash` (a "legacy" line), or (c) the
   preceding line was just rotated away (Requirement 11). `docket audit
   verify` (see Viewing) walks the chain and reports the first line where a
   stored `prev_hash` does not match the recomputed hash of the entry before
   it — this is the one thing a legacy or chain-restart line can never
   trigger, by construction.
10. `core/trace.py`'s `trace_event()` (a sibling append-only store, not part of
    this log) **MUST** distinguish a suppressed write (`DOCKET_NO_TRACE=1`)
    from a real one and from a rejected (invalid `event_type`) call — it
    returns one of the literal strings `"written"`, `"rejected"`, or
    `"suppressed"` rather than a `bool`, so a caller can no longer mistake a
    silently-dropped write for a successful one.

### Rotation and retention

1. `audit.log` **MUST** rotate to a single-generation backup, `audit.log.1`
   (overwriting any prior backup), once it reaches `AUDIT_LOG_MAX_BYTES`
   (`config.py`, default 5 MiB, env-overridable — the house style for every
   other docket-owned path/size constant in `config.py`).
2. The entry that triggers rotation, and every entry after it, **MUST** start
   a fresh chain in the new current file (Requirement 9c) — the chain is
   never required to bridge across a rotation boundary.
3. `docket audit verify` **MUST** verify only the current `audit.log`; when a
   rotated backup exists it **MUST** say so explicitly (rather than silently
   ignoring it or claiming full-history coverage it cannot provide).

### Viewing and verifying (docket audit)

1. `docket audit [N]` **MUST** print the last N entries (default 20) as a human-readable
   table of timestamp, user, action, and detail. A non-numeric argument **MUST** fall
   back to the default count.
2. `docket audit --json` **MUST** emit the raw JSONL unmodified (stable for scripting).
3. When no log exists yet, the command **MUST** explain where entries will be recorded
   and exit 0.
4. Malformed lines **MUST** be skipped, never crash the display. A legacy line
   (missing `seq`/`prev_hash`) **MUST** display normally, not as an error.
5. `docket audit verify` **MUST** walk the current log's hash chain and:
   - exit 0 and report "no audit log yet" when the file does not exist;
   - exit 0 and report the count of chained and legacy (unchained) lines when
     the chain verifies clean;
   - exit 1 and report the **first** broken link's line number and reason
     (e.g. a `prev_hash` mismatch, an out-of-order `seq`, or malformed JSON)
     when tampering is detected.
   A legacy line, or the first line of a fresh chain restart, **MUST NOT** be
   reported as a break — only an actual hash/seq mismatch counts as tampering.

## Interface Contracts

### CLI Command Signatures

```bash
docket audit            # Last 20 changes, human-readable
docket audit <N>        # Last N changes
docket audit --json     # Raw JSONL passthrough
docket audit verify     # Walk the current file's hash chain; exit 1 on a detected break
```

### Entry Schema (one JSON object per line)

```json
{"seq": 42, "ts": "2026-07-30T08:00:00.123Z", "user": "alice", "pid": 12345,
 "action": "approval.grant", "detail": "token=apr-… project=mywebsite channel=cli",
 "prev_hash": "3f9a1c…64 hex chars"}
```

A line written before this version lacks `seq`/`prev_hash` entirely — readers
and `docket audit verify` MUST treat that shape as valid legacy input, not as
a parse error.

### Return Codes

- `0`: Success (including "no log yet" for both `docket audit` and `docket audit verify`,
  and a clean chain for `docket audit verify`)
- `1`: `docket audit verify` detected a broken chain link

## Examples

### Recording and viewing changes

```bash
$ docket gates enable
$ docket approve apr-1234…

$ docket audit 2
  2026-07-30T08:00:00.041Z  alice       gates.enable      fleet
  2026-07-30T08:00:11.902Z  alice       approval.grant    token=apr-1234… channel=cli
```

### Verifying the chain

```bash
$ docket audit verify
✓ 214 chained line(s) verified clean.

$ docket audit verify   # after a line was hand-edited
✗ Error: Tamper check FAILED at line 87: prev_hash mismatch — an earlier line was altered or removed
```

## Validation

### Pre-conditions

- None — every `docket audit` subcommand works with or without an existing log.

### Post-conditions

- After any mutating command in an implemented action family (Requirement 1), the
  log contains exactly one new line describing it, chained to the previous entry.
- `docket audit verify` after a hand-edit of any non-final line reports a break at
  the first line whose `prev_hash` no longer matches.

### Invariants

- The log file is always `0600`.
- No secret value ever appears in the log.
- Audit failures never break the mutating command that triggered them.
- Recording cannot be disabled by an environment variable.
- A legacy or chain-restart line is never reported as tampering.

## Changelog

### Version 2.1.0 (2026-07-30)

- ROADMAP Phase 18 L-3 (docket as an MCP server): added the `mcp.<tool>` action family — every
  `docket mcp serve` tool call is audited unconditionally, first thing, before the underlying
  operation runs, regardless of whether that operation also has its own action family (e.g.
  `approval.grant`). This is the first action family that covers read-only operations (`status`,
  `pods`, `queue`, `runs`, `approvals_list`, `cost` have no other audited surface anywhere else in
  this project). See `specs/api/mcp-server.spec.md`.

### Version 2.0.1 (2026-07-30)

- ROADMAP Phase 14 R-6/R-5 spec truth pass: added the missing `pod.set-verify` action family
  (shipped alongside R-6's worktree-cwd fix and verify-command validation) and `profile.resume`
  (R-5's auto-pause clear) — both were shipped before 2.0.0 but omitted from its Requirement 1
  coverage list by mistake.

### Version 2.0.0 (2026-07-30)

- **Audit v2 (ROADMAP Phase 15 G-4, pulled forward).** Coverage: added
  `keys.add/rotate/remove`, `profile.model/budget`, `scope.set/reset`,
  `agent.add/delete` (both the pod and declarative flows, and both single-agent
  and whole-pod deletes), `pod.add/remove`, and `persona.set/clear` — the
  previous version's entire "planned" list, minus `models.*` and `runs.cancel`
  (tracked as remaining gaps, Requirement 2). Tamper evidence: every entry now
  carries `seq` + `prev_hash` (SHA-256 chain, stdlib-only); new `docket audit
  verify` walks it and reports the first break. Timestamps moved to
  millisecond resolution. Added size-capped rotation (`AUDIT_LOG_MAX_BYTES`,
  single-generation `audit.log.1` backup) with a documented, non-bridged
  verification boundary. **Removed** the `DOCKET_NO_AUDIT` kill switch
  entirely (Requirement 7) rather than gating it behind a TTY prompt, to avoid
  forcing interactive I/O into `core/audit.py` and its `core/`-layer callers.
  Status raised from Partially implemented to Implemented for everything this
  version claims; `models.*`/`runs.cancel` stay explicitly out of scope rather
  than silently implied.

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
