# Audit Log Specification

**Version**: 2.5.0
**Status**: Implemented (recording coverage, tamper evidence, rotation, and the kill-switch
removal below are all shipped, now including `models.*`, `runs.cancel`, and `mcp_servers.*` — see
Requirement 2 for what audit still does NOT see). **ROADMAP Phase 19 P19-7a** moved the log file
itself from `$OPENCLAW_DIR/audit.log` to `$DOCKET_HOME/audit.log` — see Requirement 5.
**Last Updated**: 2026-08-03

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
   - `models.set` / `models.preset` / `models.reset` (`cli/__init__.py`'s `models` command,
     ROADMAP Phase 15 G-4b) — role→model policy changes. Each entry's `detail` names the role
     (or `default`) affected and the before/after model, so the log alone answers "which role
     changed, from what, to what, and when" without consulting `docket-models.json`. `set`
     writes `role=programmer anthropic/claude-sonnet-4-6->openai/gpt-4.1`, one entry for the one
     key it touched. `preset`/`reset` can touch every role at once and are each recorded as
     **one** entry naming the preset (preset only) and every role's before/after pair
     comma-joined after a `roles:` prefix, alongside a `default:` before/after pair — matching
     `agent.add`'s whole-pod-in-one-line style above, not one entry per role. See the Entry
     Schema section for a full example line.
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
   - `runs.cancel` (`core/runs.py`'s `cancel_run`, ROADMAP Phase 16 W-4) — the one gap W-2 left
     when it shipped `docket runs cancel`: every other privileged action already wrote an entry,
     cancellation did not. Written only when a run is actually cancelled (i.e. `cancel_run`'s
     `ok=True` path); an unknown run id or a run already in a terminal state changes nothing and
     writes no entry. `detail` names the run id, its project, its state immediately before
     cancellation (`was=`), and how many process groups were actually killed (`killed=`) — see
     `cli-interface.spec.md`'s `docket runs` entry. This and `approval.*` are the only families
     written from `core/` rather than `cli/`.
   - `mcp_servers.add` / `mcp_servers.remove` (`cli/_mcp.py`'s `docket mcp servers add|remove`,
     ROADMAP Phase 19 P19-13) — the CLI over `core/mcp_tools.py`'s `add_mcp_server`/
     `remove_mcp_server` (P19-10). `detail` names the server and, for `add`, the launch command —
     never the server's `env` values, matching `keys.add`'s convention of naming a secret's key,
     not its value. Distinct from the `mcp_client.*` family `core/mcp_tools.py` itself writes
     (`unavailable`, `tool_description_blocked`, `tool_description_warn`) — those record what
     happened when docket *connected* to a server; this family records the CLI operator *changing
     the configured server list*, the same client/server split `mcp.<tool>` vs. `mcp_client.*`
     already draws above.
2. **What the log does NOT see (scope boundary, not a backlog item).** Both gaps tracked through
   Version 2.1.0 — role→model policy changes and `runs.cancel` — are recorded as of Version
   2.3.0; the two cards that closed them (Phase 15 G-4b, Phase 16 W-4) landed in the same wave.
   What remains uncovered is **structural**: the log records what *docket* does, so an action
   taken outside docket — a raw Telegram session with an agent, direct `openclaw` CLI use, a
   human editing `openclaw.json` by hand — leaves no entry, and this spec **MUST NOT** be cited
   as evidence that it would. That boundary is D-9's "docket orchestrates hops" line, not a gap a
   future card closes.
3. `action` **MUST** be a dotted verb (e.g. `gates.enable`, `approval.grant`); `detail`
   **MUST** be a human-readable target (an id, key NAME, model id). Secret VALUES
   **MUST NOT** ever be written to the log.
4. Each entry **MUST** record `ts` (UTC ISO-8601, millisecond resolution — see
   Requirement 8), `user`, `pid`, `action`, `detail`, and the tamper-evidence
   fields `seq` and `prev_hash` (Requirement 9).
5. The log file **MUST** live at `$DOCKET_HOME/audit.log` (moved from `$OPENCLAW_DIR/audit.log`
   at ROADMAP P19-7a — the last docket-owned state that lived under the daemon's directory) and
   **MUST** be created with mode `0600`.
6. Recording **MUST** be best-effort: a write failure **MUST NOT** fail the calling command. A
   missing parent directory **MUST** be created (`mkdir(parents=True, exist_ok=True)`), not
   treated as a reason to skip recording — before P19-7a, a missing `$OPENCLAW_DIR` meant "OpenClaw
   was never installed" and correctly no-op'd; `$DOCKET_HOME` is genuinely docket-owned with
   nothing external to bootstrap it, so a missing parent now means only "first-ever docket write",
   and self-creating it is what stops the log silently losing its very first entry on a fresh
   `~/.docket`.
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

A `models.preset` entry, showing the multi-role-in-one-line shape (Requirement 1):

```json
{"seq": 43, "ts": "2026-07-30T08:00:12.500Z", "user": "alice", "pid": 12345,
 "action": "models.preset",
 "detail": "preset=openai default:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini roles:manager:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano,reviewer:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano,tester:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano,knowledge:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano,programmer:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini,security:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini,repo:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini",
 "prev_hash": "9c2e7a…64 hex chars"}
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
✗ Error: Tamper check FAILED at line 87 of 214: prev_hash mismatch — an earlier line was altered or removed
```

The failure message's `of 214` names the current file's total line count
(`VerifyResult.total_lines`, G-4b) — the one place this figure adds
information `chained`/`legacy` can't, since counting stops at the break. The
clean-chain summary above does not repeat it: there, `chained` already sums to
the total (every line is either chained or legacy), so restating it would be
redundant.

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

### Version 2.5.0 (2026-08-03)

- **ROADMAP Phase 19, card P19-7a (the runtime cutover).** `AUDIT_LOG` (`docket.config`) moved
  from `$OPENCLAW_DIR/audit.log` to `$DOCKET_HOME/audit.log` — updated Requirement 5. Requirement
  6 changed alongside it: `audit_log()` now creates a missing parent directory itself rather than
  silently no-op'ing, because `$DOCKET_HOME` (unlike `$OPENCLAW_DIR`, the daemon's own directory)
  has nothing external bootstrapping it — a missing parent under the old contract meant "OpenClaw
  was never installed" (a legitimate skip signal); under the new one it just means "first-ever
  docket write" (not a reason to lose the entry). No change to entry schema, tamper-evidence
  chain, rotation, or the no-kill-switch contract. No migration: per D-19's clean break, a
  pre-existing `$OPENCLAW_DIR/audit.log` is not read, moved, or chained-from.

### Version 2.4.0 (2026-08-02)

- **ROADMAP Phase 19, card P19-13 (`docket mcp servers` CLI).** Added the `mcp_servers.add` /
  `mcp_servers.remove` action family: `docket mcp servers add|remove` now write an entry naming
  the server (and, for `add`, its launch command — never `env` values), the same "name the thing
  changed, not its secret material" convention `keys.add` already established. `docket mcp
  servers list` is read-only and writes nothing, matching every other read-only listing command
  in this project.

### Version 2.3.0 (2026-07-30)

- **ROADMAP Phase 16, card W-4 — closed the `runs.cancel` gap.** Added the `runs.cancel` action
  family (`core/runs.py`'s `cancel_run`): the one privileged action W-2 shipped without an audit
  entry. Written from `core/` rather than `cli/`, matching `core/approval.py`'s existing
  `approval.grant`/`approval.deny` precedent — audit logging from `core/` is not a layering
  violation, only UI and printing are. Written only on an actual cancellation; the no-op paths
  (unknown run id, already-terminal run) change nothing and record nothing.
- **Requirement 2 rewritten, because both of its tracked gaps closed in the same wave.** G-4b
  (Version 2.2.0) recorded `models.*` and W-4 recorded `runs.cancel`; each card's own draft of
  this spec still listed the *other* one as an open gap, since neither could see the other's
  merge. Requirement 2 now states the boundary that actually remains — the log records what
  docket does, and nothing about actions taken outside it.

### Version 2.2.0 (2026-07-30)

- **ROADMAP Phase 15 G-4b (Audit coverage for `models.*`).** Closed the one gap G-4 (Version
  2.0.0) named and left open: `docket models set/preset/reset` now write the `models.set` /
  `models.preset` / `models.reset` action family, with the same `seq`/`prev_hash` chain, ms
  timestamps, and best-effort/never-crashes contract as every other family. `set` writes one
  entry naming the role (or `default`) it touched and its before/after model; `preset`/`reset`
  touch every role at once and are each recorded as one entry naming every role's before/after
  pair plus the default's, not one entry per role (see Requirement 1 and the new Entry Schema
  example). `docket audit verify` was confirmed to still walk a log containing these entries
  without reporting a false break. The only remaining tracked gap (Requirement 2) is a future
  `docket runs cancel` — the run registry it would cancel does not exist yet (Phase 16).
  Also rendered `VerifyResult.total_lines` (previously populated but read by nothing) in the
  tamper-check failure message (`"...FAILED at line N of TOTAL: ..."`) — the one place it adds
  information the existing `chained`/`legacy` counts can't, since counting stops at the break;
  left out of the clean-chain summary, where it would just restate `chained + legacy`.

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
