# Agent Lifecycle Specification

**Version**: 1.12.0
**Status**: Complete
**Last Updated**: 2026-08-20

## Purpose

This specification defines the complete lifecycle of docket agents from creation to deletion, including all state transitions and operations.

## Scope

This specification covers:
- Agent creation (`docket add`)
- Agent listing (`docket list`)
- Agent information display (`docket info`)
- Agent deletion (`docket delete`)
- Agent maintenance operations (`docket maintain`)

This specification does NOT cover:
- Agent communication (see telegram-integration.spec.md)
- Pipeline definitions (see pipeline-format.spec.md; `docket workflow`, the retired Lobster YAML
  surface it replaced, is gone per ROADMAP D-16 — see cli-interface.spec.md's Pipeline Commands
  section)
- Pod delegation and dispatch (see pod-dispatch.spec.md)
- Blueprint selection/composition (which roster, workspace kind, default pipeline, and default
  budget a pod is provisioned with) — see the new pod-blueprints.spec.md (ROADMAP Phase 16 W-7).
  This spec covers the creation/listing/info/deletion/maintenance lifecycle common to every pod
  member regardless of which blueprint provisioned it.

## Requirements

### Agent Creation (docket add)

1. **MUST** create a unique agent identifier
2. **MUST** validate the codebase path exists, for a `codebase`-kind blueprint (`software`, the
   default). A `workdir`-kind blueprint (`research`/`content`/`ops`) has no codebase to validate
   and instead auto-provisions its shared working directory when none is given (see
   pod-blueprints.spec.md)
3. **MUST** create isolated workspace directory
4. **MUST** generate session key for project isolation
5. **MUST** initialize configuration files (SOUL.md, AGENTS.md, HEARTBEAT.md, and — for a
   standalone agent or a pod Implementer with allocated resources/a verify command — TOOLS.md;
   see workspace-structure.spec.md for the exact per-role file set)
6. **MUST** register agent in docket's fleet registry (`fleet.json`; ROADMAP Phase 19 P19-6 — see
   ../data/docket-meta.spec.md's "Sync contract (retired)" for what this replaced)
7. **MUST** set appropriate file permissions (700 for dirs, 600 for files)
8. **SHOULD** auto-detect project stack (`codebase`-kind blueprints only)
9. **SHOULD** suggest appropriate model profile based on project type
10. **MAY** initialize with custom description
11. **MUST** stamp the active template version into agent metadata so prompt drift is detectable
12. **MAY** provision one or more agents declaratively from a spec file (`docket init --from <file>`)
13. **MUST** select a pod blueprint (`--blueprint <name>`, default `software`) before provisioning
    and **MUST** fail cleanly, before any interactive prompt, if the name is not registered (see
    pod-blueprints.spec.md)

#### Declarative Provisioning (docket init --from)

1. **MUST** accept a JSON spec; **SHOULD** accept YAML when a YAML parser is available
2. **MUST** support a list of agents, a `{agents: [...]}` mapping, or a single agent mapping
3. **MUST** apply the same defaults as interactive creation (id slugified from name,
   default model, stack auto-detection) and require only a `name`
4. **MUST** be idempotent: an agent whose workspace already exists is skipped, not recreated
5. **MUST** skip invalid records without aborting the rest of the spec file
6. **SHOULD** restart the gateway at most once per invocation, after all agents are provisioned
7. **MAY** carry a `blueprint` field on any entry, provisioning a pod (see pod-blueprints.spec.md)
   instead of the single flat agent described by requirements 1–6 above; an entry with no
   `blueprint` field is entirely unaffected by this option's existence

### Agent States

An agent is either **registered** (workspace + `.docket-meta.json` + a `fleet.json` entry all
present) or **deleted**. There is no separate stopped state; the docket-local `paused` flag
(cost-tracking.spec.md) marks an agent that dispatch must refuse, without unregistering it.

### Agent Listing (docket list)

Output **MUST** include:
- Agent ID (slugified, unique)
- Kind/scope (project agent vs org specialist; pod role where applicable)
- Codebase path (if applicable)
- Current model and source (policy or pinned)
- Telegram binding status
- Session key / project scope

The exact table rendering is pinned by the golden suite; the machine-readable shape by
../data/cli-json-shapes.spec.md.

### Agent Information (docket info)

**MUST** display:
1. Agent identifier
2. Kind/scope (and pod role where applicable)
3. Workspace path
4. Codebase path (if set)
5. Detected stack (if set)
6. Current model and profile
7. Session key
8. Project key
9. Memory usage (log count and size)
10. Telegram binding status
11. Cost metrics (tokens and dollars)
12. Creation timestamp
13. Last activity timestamp

### Agent Deletion (docket delete)

1. **MUST** prompt for confirmation (interactive; there is no `--force` bypass flag)
2. **MUST** remove workspace directory completely
3. **MUST** unregister from docket's fleet registry (`fleet.json`)
4. **MUST** remove any Telegram bindings and conversation-registry entries
5. **SHOULD** display deletion summary
6. Deleting a pod project **MUST** tear down every pod member and free the pod's
   allocated resources (port range, scratch dir)
7. Deleting a pod **MUST** remove its Docket-owned runtime directory, durable session histories,
   and JSONL trace directories for both the project id and its member ids. It **MUST NOT** delete
   or rewrite the global audit log; the deletion record remains as durable evidence.
8. The pre-deletion summary **MUST** render each member's role literally, without markup syntax
   hiding the value.

### Agent Maintenance (docket maintain)

`docket maintain [agent-id] [mode]` consolidates the retired `reset`, `repair`, and `cleanup`
commands. Six modes **MUST** be supported.

#### check (Default) - Health and Auto-fix
- Verify and fix missing workspace directory → recreate
- Regenerate missing core files from templates
- Reset invalid permissions to 700/600
- Backfill a specialist's missing `.docket-meta.json` from the role→model policy; the fleet
  registry does not track per-agent models, so the policy resolver is the only source.
- Re-register a missing fleet registration
- Clean up orphaned Telegram bindings

#### clean - Memory Logs
- Distill pending `memory/*.md` daily logs into MEMORY.md and archive the originals under
  `memory/.distilled/<day>/` **before** deleting anything (ROADMAP Phase 17 C-2) — **MUST** be the
  default behaviour; `--no-distill-first` is the explicit opt-out that restores the pre-C-2
  behaviour of deleting `memory/*.md` outright with no distillation step
- A failed distillation (driver/model error, timeout, or an empty reply) **MUST** abort the whole
  `clean` operation before any file is deleted — never partially apply
- Preserve SOUL.md, AGENTS.md, TOOLS.md
- Preserve session and project keys
- Preserve .docket-meta.json

#### reset - Deep Memory
- Everything from `clean`, including the same `--distill-first` default/`--no-distill-first`
  opt-out and fail-closed abort behaviour
- Clear MEMORY.md summary — **unless** a distillation actually ran this invocation (there were
  pending logs and it succeeded), in which case MEMORY.md was *just* refreshed with the distilled
  summary and this step is skipped, so `--distill-first` never immediately erases the summary it
  exists to preserve
- Clear HEARTBEAT.md tasks — for a pod **Lead**, this also clears the docket-owned dispatch
  ledger region dispatch mechanically maintains (ROADMAP Phase 17 C-3; see
  pod-dispatch.spec.md's "Mechanical HEARTBEAT ledger"). If a task is genuinely `running` in
  `TASK_LIST.json` at reset time, the ledger and the queue now disagree until the next dispatch
  lifecycle event (claim/hop/retry/finalize) or `docket doctor --fix` re-syncs it — `reset` is an
  operator action on a workspace file, not a dispatch-aware operation, so it does not special-case
  a Lead mid-task
- Reset conversation context

#### rebuild - Complete Rebuild
- Everything from `reset`
- Regenerate SOUL.md from metadata
- Regenerate AGENTS.md from template
- Regenerate TOOLS.md from stack
- Generate new session key
- Reset project key to default

#### sessions - Session Hygiene
- Archive large or old session data
- Preserve all configuration and identity files

#### distill - Memory Distillation (ROADMAP Phase 17 C-2)
- Summarize pending `memory/*.md` daily logs into a dated `MEMORY.md` section via **one
  driver-backed agent turn** (decision D-18 — docket's first self-originated LLM call; see
  ../../ROADMAP.md §6). No provider SDK or HTTP client is used; the call goes through the same
  `RuntimeDriver` port every pod dispatch hop already uses
- Archive the original daily logs to `memory/.distilled/<day>/` (moved, not deleted) once the
  summary is durably written
- **MUST** fail closed: a driver failure (timeout, model error, non-zero exit) or an empty reply
  leaves every file on disk untouched and returns a non-zero exit code — no partial archive, no
  partial MEMORY.md write
- A sparse operator-authored line beginning `- [exact] ` **MUST** retain its decision identifier
  and every backtick-delimited literal byte-for-byte in the model summary. Docket **MUST** validate
  those fields before writing or archiving, fail closed on omission/corruption, and append the
  marked records verbatim under `## Exact durable records`. Ordinary unmarked narration remains
  model-summarized; this mechanism **MUST NOT** copy whole logs into long-term context.
- No pending logs is a no-op success (there is nothing undistilled to lose)
- **MUST NOT** require interactive confirmation — it is additive/non-destructive to the daily logs
  (they are archived, not deleted), unlike `reset`/`rebuild`

`reset` and `rebuild` are destructive and **MUST** prompt for confirmation unless forced. `distill`
is not destructive to the daily logs it processes (they are archived, not deleted) and runs without
a confirmation prompt.

## Interface Contracts

### CLI Command Signatures

```bash
# Create a project pod from a blueprint (interactive or with args); --blueprint
# defaults to `software`. --pod full/--with apply only to the software blueprint.
docket init <project> [location] [--blueprint <name>] [--pod full | --with reviewer,tester]

# Create one or more agents (or, with a `blueprint` field, pods) declaratively
# from a spec file (JSON, or YAML when PyYAML is present)
docket init --from <agents.yaml|agents.json>

# List agents
docket list [--json]

# Show agent info
docket info <agent-id> [--json]

# Delete agent (or a whole pod, by project name)
docket delete <agent-id>

# Maintain agent (replaces reset/repair/cleanup)
docket maintain <agent-id> [check|clean|reset|rebuild|sessions]
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid arguments, permission problems, driver failures —
  docket's CLI-wide convention; see ../api/cli-interface.spec.md)

## Examples

### Creating a Project Agent

```bash
$ docket add mywebsite ~/projects/website
[INFO] Creating agent: mywebsite
[INFO] Stack: node (detected: package.json)
[INFO] Workspace: ~/.docket/workspaces/projects/mywebsite
[INFO] Session key: agent:mywebsite:default
[SUCCESS] Agent 'mywebsite' created and registered
```

### Maintaining an Agent

```bash
$ docket maintain mywebsite reset
[WARN] 'reset' will clear memory and tasks
Continue? (y/N): y
[INFO] Clearing memory logs...
[INFO] Resetting MEMORY.md...
[INFO] Clearing HEARTBEAT.md...
[SUCCESS] Agent 'mywebsite' maintained (reset)
```

## Validation

### Pre-conditions
- User **MUST** have write permissions to `~/.docket`.
- Python 3.11+ **MUST** be available (docket's runtime requirement)

### Post-conditions
After successful creation:
- Workspace directory **MUST** exist at expected path
- All core files **MUST** be present and valid
- Agent **MUST** appear in `docket list` output
- Agent **MUST** be registered in docket's fleet registry (`fleet.json`)

### Invariants
- Agent IDs **MUST** be unique across system
- Session keys **MUST** follow format: `agent:<id>:<project>`
- Workspace permissions **MUST** be 700 for directories, 600 for files
- Model and session key **MUST** exist in exactly one place: `.docket-meta.json` (ROADMAP Phase 19
  P19-6 — `fleet.json` tracks the bare registration fact only, never a copy of either field; see
  ../data/docket-meta.spec.md's "Sync contract (retired)")

## Error Handling

### Common Errors and Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| Agent already exists | Duplicate ID | Use different ID or delete existing |
| Codebase not found | Invalid path | Verify path exists |
| Permission denied | Insufficient rights | Check ~/.docket permissions |
| Workspace corrupted | Missing files | Run `docket maintain check` |
| Distillation turn failed (model error, timeout, no credential) | `docket maintain distill`, or `clean`/`reset` with `--distill-first` (the default) | Nothing was deleted (fail-closed); retry once the model endpoint is reachable, or pass `--no-distill-first` to `clean`/`reset` to proceed without distilling |

## Performance Criteria

- Agent creation: < 2 seconds
- Agent listing: < 500ms for 100 agents
- Agent deletion: < 1 second
- Maintain (clean, `--no-distill-first`): < 500ms
- Maintain (rebuild): < 3 seconds
- Maintain (check): < 5 seconds
- Maintain (distill, or clean/reset with `--distill-first`): bounded by one driver turn
  (`config.DISTILL_TIMEOUT_S`, default 120s) rather than a fixed local-operation budget — it is a
  real, costed LLM call, not a file operation

## Changelog

### Version 1.12.0 (2026-08-20)

- Pod deletion now removes orphanable runtime/session/trace state while preserving the global
  audit log, and its confirmation summary renders member roles literally.

### Version 1.10.0 (2026-08-19)

- W24's real memory canary caught a model changing an exact tax divisor from `10_000` to `1_000`
  while distilling. Added sparse `- [exact]` durable records: their identifier/backtick literals
  are validated before any write/archive and carried verbatim; corruption now fails closed without
  turning every daily log into permanent context.

### Version 1.9.0 (2026-08-19)

- Removed retired-runtime migration detail from the live maintenance and precondition contract.

### Version 1.8.0 (2026-08-03)

- ROADMAP Phase 19 P19-7b (the OpenClaw daemon is deleted): removed the "OpenClaw daemon MUST
  be running" pre-condition — there is no external daemon any more, so it cannot be a
  pre-condition of anything (`DocketDriver` talks to a model endpoint directly). Corrected every
  `~/.openclaw` path reference to `~/.docket` (the workspace-creation example, the permissions
  pre-condition, and the "permission denied" error-recovery row). Removed the "Daemon not
  running / Start with systemctl --user start openclaw-gateway" error-recovery row outright — no
  successor: there is no gateway systemd unit left to start. Reworded "driver/daemon error" to
  "driver/model error" in the distillation fail-closed requirements and the exit-code
  description (a distillation turn can still fail — timeout, bad credential, empty reply — the
  failure just no longer has a daemon in the loop to attribute it to).

### Version 1.7.0 (2026-08-02)

- ROADMAP Phase 19 P19-6 (docket-native fleet registry): agent registration/unregistration now
  target docket's own `fleet.json` (`core/fleet.py`), not `openclaw.json`'s `agents.list` — the
  removal spine's first card. Reworded the registered-state definition, the create/delete
  MUSTs, the post-conditions/invariants, and `maintain check`'s auto-fix bullets accordingly.
  Retired the "metadata synchronized between .docket-meta.json and openclaw.json" invariant —
  see ../data/docket-meta.spec.md v2.8.0's "Sync contract (retired)": `fleet.json` never tracks
  `model`/`sessionKey`, so there is exactly one place either lives now, not two kept in sync.

### Version 1.6.0 (2026-07-31)

- ROADMAP Phase 17 C-3 (one durable task state): noted that `maintain reset`'s "Clear HEARTBEAT.md
  tasks" step also clears a pod Lead's docket-owned dispatch ledger region, and that this can
  transiently disagree with a genuinely `running` task in `TASK_LIST.json` until the next dispatch
  lifecycle event or a `docket doctor --fix` re-sync — full behavior in pod-dispatch.spec.md's
  "Mechanical HEARTBEAT ledger".

### Version 1.5.0 (2026-07-30)

- ROADMAP Phase 17 C-2 (memory distillation, decision D-18): added the `distill` mode and gave
  `clean`/`reset` a `--distill-first` default (with `--no-distill-first` as the explicit opt-out)
  so neither command bare-deletes undistilled `memory/*.md` logs — they are summarized into
  MEMORY.md and archived instead. The summarization turn is docket's first self-originated LLM
  call, routed entirely through the `RuntimeDriver` port (no new SDK dependency). A failed
  distillation aborts the whole operation before any file is touched (fail-closed); `reset`
  additionally skips its own "clear MEMORY.md" step when a real distillation just ran, so
  `--distill-first` never immediately erases the summary it exists to preserve. Added a
  corresponding error-recovery row and a performance-criteria note (a driver turn, not a
  file-system operation, so the old fixed-latency targets do not apply to it).

### Version 1.4.0 (2026-07-30)

- ROADMAP Phase 16 W-7 (pod blueprints): `docket add` now selects a blueprint (`--blueprint
  <name>`, default `software`) before provisioning; the codebase-path validation and stack
  auto-detection requirements are now scoped to `codebase`-kind blueprints (a `workdir`-kind
  blueprint has no codebase and auto-provisions its shared working directory instead — see the
  new pod-blueprints.spec.md). `docket init --from`'s declarative contract gained a `blueprint`
  field that provisions a pod instead of a single flat agent for the entry that carries it,
  leaving every entry without one unaffected. Also fixed two stale CLI-signature claims this
  section had drifted on: `TOOLS.md` was never actually required-initialize-for every pod member
  (only a standalone agent or an Implementer with allocated resources/a verify command — see
  workspace-structure.spec.md), and the `--model <id>`/`--count N` options shown on `docket add`
  were never implemented (they exist only in the arg parser's "don't leak into positionals"
  skip-list) — removed from the documented signature.

### Version 1.3.1 (2026-07-30)
- Retargeted the "does NOT cover" workflow cross-reference at pipeline-format.spec.md — the old
  `docket workflow` / Lobster surface it named (workflow-integration.spec.md) was retired per
  ROADMAP D-16 (Phase 16 W-3); that spec file was deleted.

### Version 1.3.0 (2026-07-30)
- Truth pass (Platformization baseline): removed every remnant of the deleted repo/task
  dual-type model (`--type` flag, `type` field validation, per-type template MUSTs — the
  `type` field no longer exists); fixed the header version (was 1.0.0 while the changelog
  said 1.2.0); replaced the fictional return codes 2–7 with the real 0/1 convention;
  corrected `list`/`info`/`delete` signatures to the shipped flags (`--json` only; no
  `--format/--filter/--force/--keep-logs`); replaced the Created/Active/Stopped state
  diagram with the real registered/deleted + docket-local `paused` model; retargeted the
  team-coordination cross-reference at pod-dispatch.spec.md.

### Version 1.2.0 (2026-06-11)
- Added template-version stamping requirement (drift surfaced in `docket doctor`)
- Added declarative provisioning (`docket init --from <file>`): JSON/YAML specs, fleet lists,
  idempotent re-apply, shared defaults with interactive creation

### Version 1.1.0 (2026-06-09)
- Replaced the retired `docket reset`/`docket repair` with `docket maintain` and its five modes
- Updated interface signatures, examples, and recovery steps to match the shipped CLI

### Version 1.0.0 (2024-01-20)
- Initial complete specification
- Full lifecycle operations defined
- Error handling and validation rules
- Performance criteria established
