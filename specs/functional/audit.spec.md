# Audit Log Specification

**Version**: 2.7.0
**Status**: Implemented (recording coverage, tamper evidence, rotation-continuation, and the
kill-switch removal below are all shipped, now including `models.*`, `runs.cancel`,
`mcp_servers.*`, and `telegram.*` — see Requirement 2 for what audit still does NOT see).
**ROADMAP Phase 19 P19-7a** moved the log file itself from `$OPENCLAW_DIR/audit.log` to
`$DOCKET_HOME/audit.log` — see Requirement 5. **ROADMAP Phase 19 P19-8** gave the
`channel=telegram` tag on `approval.grant`/`approval.deny` a real producer for the first time —
see Requirement 1's `telegram.*` family. **ROADMAP Phase 18/19 wave, card W18-1** closed the gap
where two rotations in a row could erase security-relevant history while `docket audit verify`
kept reporting a clean chain — see Requirement 9c and the Rotation section below for what is, and
plainly is NOT, detected now.
**Last Updated**: 2026-08-05

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
   - `telegram.unauthorized` / `telegram.delegate_blocked` / `telegram.delegate_warn`
     (`core/telegram.py`, ROADMAP Phase 19 P19-8) — the docket-owned Telegram bot's own audit
     family, the same client-side shape as `mcp_client.*` above: `telegram.unauthorized` fires
     when a message arrives on a chat id with no `fleet.json` binding (`detail` names the chat id
     and update id — never the message text); `telegram.delegate_blocked`/`_warn` fire when a
     `/delegate` message's text trips the `pre_input` policy hook (`detail` names the project and
     policy id — never the message text). **A grant/deny answered through Telegram writes no
     entry in this family** — it writes the ordinary `approval.grant`/`approval.deny` entry
     (below) tagged `channel=telegram`, exactly as a CLI or HTTP grant would; this family exists
     only for the channel-specific events (a refusal) that have no other home.
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
   ":"))`). The first entry of a genesis chain **MUST** use the sentinel
   `prev_hash="0"*64` (`GENESIS_HASH`). A **chain restart** — starting a fresh
   `seq=1`/`GENESIS_HASH` entry with no claim on anything before it — is the
   correct, honest behavior (not a defect) in two cases: (a) the log is
   missing or empty, or (b) the immediately preceding line predates this
   requirement and carries no `seq`/`prev_hash` (a "legacy" line), including
   when that legacy line was the last thing in a generation that then
   rotated away (Rotation Requirement 2). A size-triggered rotation over a
   generation that **does** have a chained tail is **not** a restart — see
   Requirement 9c.
9c. **Rotation continuation (W18-1).** When the generation being rotated away
   (Rotation Requirement 1) has a chained tail — a last line carrying
   `seq`/`prev_hash` — the new current file's first entry **MUST NOT** reset
   to `seq=1`/`GENESIS_HASH`. It **MUST** instead carry `seq = <rotated
   generation's final seq> + 1` and `prev_hash = <SHA-256 of the rotated
   generation's final entry>` — i.e. exactly the entry the old file's chain
   would have produced next, had it not been renamed away. This is a claim,
   not a proof: `docket audit verify` (see Viewing Requirement 5) **MUST**
   check it against the single retained backup (`audit.log.1`) and
   distinguish three states for the current file's first entry:
   - **genesis** — `seq=1` and `prev_hash=GENESIS_HASH`. No predecessor is
     claimed (a fresh install, or a restart after a legacy tail per
     Requirement 9). Never a break, regardless of what `audit.log.1`
     contains — a pre-W18-1 log's rotations never made this claim, so an old
     log **MUST** continue to verify exactly as it did before this
     requirement existed (backward compatibility).
   - **continued, verified** — `seq>1`, `prev_hash != GENESIS_HASH`, and
     `audit.log.1`'s last line has `seq = (claimed seq) - 1` and recomputes to
     the claimed `prev_hash`. Reported clean; the verifier additionally
     reports the seq the chain continues from, so an operator can see that
     more history preceded this file even when that history itself is no
     longer readable (having rotated further back than the one retained
     backup covers — Rotation Requirement 4).
   - **continued, unverifiable** — `seq>1`, `prev_hash != GENESIS_HASH`, but
     `audit.log.1` is missing, unreadable, or its last line does not match
     the claim. The current file is asserting a prior generation it cannot
     produce. This **MUST** be reported as a break (Viewing Requirement 5),
     the same way a hand-tampered line is — this is the concrete case W18-1
     exists to make detectable: deleting or altering the one backup
     generation after a rotation no longer reads as a clean, fresh chain.

   **What this does NOT do.** It does not recover deleted entries, and it
   does not prevent erasure — an operator (or attacker) with filesystem
   access can still delete both `audit.log` and `audit.log.1` and let the
   next write start a genuine, unverifiable-from-genuine genesis chain,
   indistinguishable from a real fresh install. It also does not extend
   coverage past one rotation back: a generation two or more rotations in
   the past is gone once its backup is itself overwritten by the next
   rotation, by design (Rotation Requirement 4) — only the *fact* that
   something preceded the current file (a `seq` greater than the file's own
   line count) remains visible, not that generation's content. `docket audit
   verify` (see Viewing) walks the chain and reports the first line where a
   stored `prev_hash` does not match the recomputed hash of the entry before
   it, or a first-entry continuation claim that cannot be substantiated —
   these are the only things a legacy line or a genesis chain-restart can
   never trigger, by construction.
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
   other docket-owned path/size constant in `config.py`). This is still a
   single generation, unchanged by W18-1 — retention stays bounded at
   "current file + one backup"; W18-1 is about detecting what rotation
   erases, not keeping more of it around.
2. The entry that triggers rotation **MUST** carry forward the rotated
   generation's chain (`seq + 1`, `prev_hash` of its final entry) rather than
   restarting at `seq=1`/`GENESIS_HASH` — **unless** the rotated generation's
   own last line had nothing chained to continue from (empty file, or a
   legacy line with no `seq`/`prev_hash`), in which case a fresh genesis
   chain is still the correct, honest result (Requirement 9c).
3. `docket audit verify` **MUST** verify only the current `audit.log`'s own
   entries, but **MUST** check a first-entry continuation claim (2, above)
   against `audit.log.1` and report a break when that claim cannot be
   substantiated (Requirement 9c) — it is never permitted to silently accept
   an unverifiable claim as if it were a genuine genesis chain.
4. Verification never bridges past the single retained backup: a generation
   two or more rotations back is unrecoverable once its own backup is
   overwritten by the next rotation, and `docket audit verify` **MUST NOT**
   claim to check it. When a rotated backup exists, whether or not the
   current chain makes a claim on it, the command **MUST** say so explicitly
   (rather than silently ignoring it or claiming full-history coverage it
   cannot provide).

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
     the chain verifies clean. When the first entry made a rotation-
     continuation claim (Requirement 9c) that was substantiated against
     `audit.log.1`, the report **MUST** additionally say so — naming the seq
     it continues from — rather than reporting a plain clean chain
     indistinguishable from a fresh install;
   - exit 1 and report the **first** broken link's line number and reason
     when tampering is detected — a `prev_hash` mismatch, an out-of-order
     `seq`, malformed JSON, **or** a first-entry continuation claim that
     `audit.log.1` cannot substantiate (missing, unreadable, or its tail
     doesn't match — Requirement 9c's "continued, unverifiable" state).
   A legacy line, or the first line of a genuine genesis chain restart,
   **MUST NOT** be reported as a break — only an actual hash/seq mismatch, or
   an unsubstantiated continuation claim, counts as tampering.

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

### Verifying across a rotation (W18-1)

```bash
$ docket audit verify   # after a size-triggered rotation, backup intact
✓ 6 chained line(s) verified clean.
  Chain continues from a rotated generation ending at seq=214 — verified against audit.log.1.

$ docket audit verify   # audit.log.1 was deleted after that same rotation
✗ Error: Tamper check FAILED at line 1 of 6: chain claims continuation from seq=214, but audit.log.1 is missing — earlier history may have been deleted
```

## Validation

### Pre-conditions

- None — every `docket audit` subcommand works with or without an existing log.

### Post-conditions

- After any mutating command in an implemented action family (Requirement 1), the
  log contains exactly one new line describing it, chained to the previous entry.
- `docket audit verify` after a hand-edit of any non-final line reports a break at
  the first line whose `prev_hash` no longer matches.
- After a rotation whose rotated-away generation had a chained tail, the new
  current file's first entry continues that chain's `seq`/`prev_hash`
  (Requirement 9c) rather than restarting it, and `docket audit verify`
  reports the continuation as clean when `audit.log.1` still substantiates it.
- If `audit.log.1` is deleted or altered after such a rotation, `docket audit
  verify` reports a break at the current file's first line — this is the one
  thing distinguishing it from an install that never had prior history.

### Invariants

- The log file is always `0600`.
- No secret value ever appears in the log.
- Audit failures never break the mutating command that triggered them.
- Recording cannot be disabled by an environment variable.
- A legacy line, or a genuine genesis chain-restart, is never reported as
  tampering.
- A rotation-continuation claim that `audit.log.1` cannot substantiate IS
  reported as tampering (Requirement 9c) — this is new as of Version 2.7.0
  and is the one exception to "only an actual hash/seq mismatch counts".
- Retention stays bounded at one rotated generation; verification never
  claims to check further back than that.
- **What remains undetectable, stated plainly:** deleting or replacing both
  the current file and its backup in one motion is indistinguishable from a
  fresh install — no local, single-copy tamper-evidence scheme can prevent
  that, and this spec does not claim otherwise.

## Changelog

### Version 2.7.0 (2026-08-05)

- **W18-1 — the audit chain now survives its own rotation.** Before this version, two
  size-triggered rotations in a row could erase security-relevant entries from both
  `audit.log` and the single-generation `audit.log.1` backup, and `docket audit verify`
  reported a clean chain restarting at `seq=1` — indistinguishable from a fresh install,
  even though history had genuinely been overwritten. Added Requirement 9c: the entry
  written immediately after a rotation now carries the rotated generation's final `seq +
  1` and its hash as `prev_hash` (a **continuation claim**) instead of resetting to
  `seq=1`/`GENESIS_HASH`, unless the rotated generation's own tail was itself a legacy
  line with nothing to continue (unchanged, honest restart). `docket audit verify`
  (Requirement 5) now checks that claim against `audit.log.1` and distinguishes three
  states: genesis (no claim, e.g. a fresh install or a pre-2.7.0 log — unaffected,
  verifies exactly as before), continued-and-verified (reported clean, naming the seq it
  continues from), and continued-but-unsubstantiated (`audit.log.1` missing, unreadable,
  or its tail doesn't match — now reported as a break, the concrete new detection this
  card adds). Rotation/retention Requirement 1 is unchanged: still one current file plus
  exactly one backup, no unbounded growth. **Stated plainly, what this does NOT do:** it
  does not recover deleted entries, and an operator who deletes both the current file and
  `audit.log.1` in one motion still produces an unverifiable-from-genuine fresh chain — no
  local tamper-evidence scheme can prevent that. `core/audit.py`'s `VerifyResult` gained
  one new field, `continued_from_seq` (`int | None`), populated only on a verified
  continuation. No change to the entry schema, to `audit_log()`'s never-fail contract, or
  to the no-kill-switch decision.

### Version 2.6.0 (2026-08-03)

- **ROADMAP Phase 19 P19-8 — the docket-owned Telegram bot is a real audit producer.** Added the
  `telegram.unauthorized` / `telegram.delegate_blocked` / `telegram.delegate_warn` action family
  (`core/telegram.py`) to Requirement 1's implemented-families list. `channel=telegram` on
  `approval.grant`/`approval.deny` is no longer a reserved-but-unwritten tag (security-gates.spec.md
  v0.11.0 and earlier described it that way) — it is written on every real grant/deny answered
  through a `docket wire`-bound chat, via the same `approval_grant`/`approval_deny` producer every
  other channel calls. No schema change: this is a new *producer*, not a new entry shape.

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
