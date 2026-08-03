# Telegram Integration Specification

**Version**: 1.1.0
**Status**: Binding-only (manual entry) — **ROADMAP Phase 19 P19-7b deleted the OpenClaw
daemon** this spec was written against. Every requirement below describing daemon message
delivery, log-based group discovery, or `openclaw.json` synchronization described a real
pre-P19-7b system; it is now historical. What remains real: `docket wire`/`docket unwire`
record a manual peer/group ID in `fleet.json`. **No docket-owned channel bot exists yet
(P19-8, not shipped)** — a binding is recorded, but nothing today actually sends or receives a
Telegram message on its behalf. Do not read this spec as describing a working chat integration;
it describes the binding *data model* an eventual docket-owned bot will read.
**Last Updated**: 2026-08-03

## Purpose

This specification defines how docket records which Telegram group/peer maps to which agent
(`docket wire`/`docket unwire`), so that a future docket-owned channel bot (P19-8) — or, until
then, a human reading `fleet.json` — knows where an agent's channel thread lives. Pre-P19-7b,
this bound a group the *OpenClaw daemon* delivered messages through; that daemon is deleted,
and docket does not yet own a replacement transport.

## Scope

This specification covers:

- Recording a Telegram peer/group ID binding for an agent (`docket wire`)
- Removing a binding (`docket unwire`)
- The binding's storage in `fleet.json` (`core/fleet.py`)

This specification does NOT cover:

- Any live Telegram transport — none exists in this codebase today; P19-8 is not yet shipped
- Tool-approval gate semantics (see security-gates.spec.md)

## Requirements

### Wiring a group (docket wire)

1. **MUST** prompt for the peer/group ID directly (manual entry) — ROADMAP Phase 19 P19-7b
   removed log-based Telegram group auto-discovery (`scan_telegram_groups`) along with the
   daemon gateway log it read; there is no list of "recently active groups" to present any more.
2. **MUST** write a binding mapping the entered peer ID to the target agent into `fleet.json`
   (`core/fleet.py`'s `upsert_binding`), not `openclaw.json` (deleted).
3. **MUST NOT** claim the binding is live: `docket wire`'s output **MUST** state plainly that
   no docket-owned channel bot exists yet (P19-8) and nothing listens on the recorded peer
   until then.
4. **SHOULD** show an existing binding for the agent, if any, before prompting for a new one.
5. **MUST** fall back to the interactive agent picker when no agent id is supplied.
6. **MUST NOT** invent a binding from empty input; an empty entry **MUST** abort cleanly
   (exit 0, "Aborted").

### Unwiring a group (docket unwire)

1. **MUST** remove the binding for the given agent from `fleet.json`.
2. **SHOULD** succeed silently (idempotent) if no binding exists.

### Ownership boundary

1. **Historical (pre-P19-7b).** docket used to treat message send/receive, formatting, and
   approval prompts as the OpenClaw daemon's responsibility; docket only managed binding state.
   That daemon is deleted; there is currently no live transport of any kind, docket-owned or
   otherwise, for a wired binding to feed.
2. Bindings **MUST** remain the single source of truth linking a chat/peer to an agent, ready
   for a future docket-owned bot to read.

## Interface Contracts

### CLI Command Signatures

```bash
# Bind a Telegram group/peer to an agent (manual peer/group ID entry)
docket wire [agent-id] [--channel <name>]

# Remove an agent's channel binding
docket unwire [agent-id] [--channel <name>]
```

### Return Codes

- `0`: Success (bound / unbound / nothing to do / aborted on empty entry)
- `1`: Any error (unknown agent — CLI-wide convention, see ../api/cli-interface.spec.md)

## Examples

### Wiring an agent to a group

```bash
$ docket wire mywebsite
Wire Telegram: My Shop (mywebsite)

Enter the peer/group ID from your telegram setup.

Telegram peer/group ID: -1001234567890
[SUCCESS] Binding: mywebsite ← telegram group -1001234567890
  No daemon exists to answer this channel yet — the binding is recorded, but
  nothing listens on it until docket owns its own Telegram bot (P19-8).
[SUCCESS] Done. 'mywebsite' is now wired to telegram peer -1001234567890
```

### Removing a binding

```bash
$ docket unwire mywebsite
Unwire Telegram: My Shop (mywebsite)

This will remove the telegram binding for peer -1001234567890
Confirm? [y/N]: y
[SUCCESS] Binding removed
```

## Validation

### Pre-conditions

- None daemon-related — there is no daemon to have running any more. The operator **MUST**
  already know the peer/group ID to enter (no auto-discovery exists).

### Post-conditions

- After `docket wire`, `fleet.json` **MUST** contain a binding linking the entered peer ID to
  the agent.
- After `docket unwire`, no binding for the agent **MUST** remain in `fleet.json`.

### Invariants

- A peer **MUST** map to at most one agent at a time (per channel).
- A binding's existence **MUST NOT** be read as "this channel is live" — it is a recorded
  intent only until a docket-owned channel bot (P19-8) exists to act on it.

## Changelog

### Version 1.1.0 (2026-08-03)

- **ROADMAP Phase 19 P19-7b — the OpenClaw daemon is deleted; this spec's entire ownership
  model is rewritten.** Pre-P19-7b, docket "owned the wiring" and the daemon "owned message
  delivery" — a real division of labor when the daemon existed. It doesn't any more, so:
  - `docket wire` **no longer discovers groups** from daemon activity logs
    (`scan_telegram_groups` is deleted along with the gateway log it read) — it prompts for
    the peer/group ID directly. Rewrote requirement 1 and the Examples section accordingly.
  - Bindings are written to `fleet.json` (`core/fleet.py`'s `upsert_binding`), not
    `openclaw.json` (deleted, no successor for the daemon side).
  - `docket wire`/`docket unwire` no longer restart a gateway to "pick up the change" — there
    is no gateway process; `restart_gateway()` is an honest `status="no_daemon"` no-op kept
    for call-site compatibility.
  - **Added the honesty requirement this version exists to state**: `docket wire`'s output
    MUST say plainly that no docket-owned channel bot exists yet (P19-8) and nothing listens
    on a newly recorded binding until then. Retitled the Status line "Binding-only (manual
    entry)" to make this impossible to miss.
  - Corrected the Pre-conditions (no daemon-running requirement left) and Invariants (a
    binding is "recorded intent," not "this channel is live").

### Version 1.0.1 (2026-07-30)

- Truth pass (Platformization baseline): return codes corrected to the real 0/1
  convention (the spec'd codes 2/7 never existed).

### Version 1.0.0 (2026-06-09)

- Initial Telegram integration specification
- Defined wire/unwire binding contract and the docket/daemon ownership boundary
