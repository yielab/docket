# Agent Lifecycle Specification

**Version**: 2.0.0
**Status**: Complete
**Last Updated**: 2026-10-08

## Purpose

This specification defines the complete lifecycle of docket agents from creation to deletion, including all state transitions and operations.

## Scope

This specification covers:
- Agent creation (`docket init` creates a project pod; `docket pod add` adds role agents to an
  existing pod and never creates a project)
- Pod display (`docket pod show`)
- Member removal and reset (`docket pod remove`, `docket pod reset`)
- Pod deletion (`docket pod delete`)

This specification does NOT cover:
- Agent communication (see telegram-integration.spec.md)
- Pipeline definitions (see pipeline-format.spec.md; `docket workflow`, the retired Lobster YAML
  surface it replaced, is gone per ROADMAP D-16 — see cli-interface.spec.md's Pipeline Commands
  section)
- Pod delegation and dispatch (see pod-dispatch.spec.md)
- Blueprint selection/composition (which roster, workspace kind, default pipeline, and default
  budget a pod is provisioned with) — see the new pod-blueprints.spec.md (ROADMAP Phase 16 W-7).
  This spec covers the creation/display/removal/reset/deletion lifecycle common to every pod
  member regardless of which blueprint provisioned it.

## Requirements

### Agent Creation (docket init)

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
10b. **MUST NOT** bootstrap the workstation home. When `cli/_setup.py::readiness()` reports no model
   endpoint, it **MUST** still build the team and end with a `No model endpoint yet` warning and the
   single next step `docket setup`; the endpoint, baseline policies and security posture are
   `docket setup`'s (api/cli-interface.spec.md).
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
6. *(Retired.)* ~~**SHOULD** restart the gateway at most once per invocation~~ — docket has no
   gateway process (ROADMAP D-19), so provisioning restarts nothing
7. **MAY** carry a `blueprint` field on any entry, provisioning a pod (see pod-blueprints.spec.md)
   instead of the single flat agent described by requirements 1–6 above; an entry with no
   `blueprint` field is entirely unaffected by this option's existence

### Agent States

An agent is either **registered** (workspace + `.docket-meta.json` + a `fleet.json` entry all
present) or **deleted**. There is no separate stopped state; the docket-local `paused` flag
(cost-tracking.spec.md) marks an agent that dispatch must refuse, without unregistering it.

### Pod Information (docket pod show)

`docket pod show [member] [--json]` **MUST** display, for the pod:
1. The pod name and, per member, its id, role and model with where the model comes from (`policy`,
   or `pod overlay` when the pod's own role overlay defines the role)
2. Each implementer's `verifyCmd`
3. Every pod setting with its value and source (`set` or `default`), the approval mode the
   dispatcher will resolve for this caller (`core.dispatch.pod_approval_mode`), the pipeline
   source and the network mode and scope
4. `configSource`, `configDigest` and `drift` when the pod was applied from a directory

`docket pod show <member>` **MUST** display that member's whole effective configuration: workspace
path, role, model, endpoint readiness, provider, composed prompt sections, allowed and denied
tools, MCP servers, applicable policies, skills, project instructions and exporters. A name that
is not a member of the pod **MUST** exit 1. A pod whose stored settings are invalid **MUST**
refuse (exit 1, the key named) and never show a default in its place. The command **MUST NOT**
write anything.

### Member Removal (docket pod remove)

1. **MUST** confirm: on a terminal a `y/N` prompt; off a terminal it **MUST** exit 1 naming
   `--yes` and change nothing
2. **MUST** refuse the pod's Lead (exit 1, "delete the pod instead"), leaving the pod unchanged
3. **MUST** refuse an id that is not a member of the pod
4. **MUST** deregister the member from `fleet.json`, remove its workspace and its task
   worktrees (requirement 9 of Pod Deletion applies to its branch), write one `pod.remove` audit
   entry, and free the pod's runtime resources when it was the last implementer

### Member Reset (docket pod reset)

1. **MUST** confirm exactly as `pod remove` does
2. **MUST** distill pending `memory/*.md` day-logs into MEMORY.md and archive the originals under
   `memory/.distilled/<day>/` (one driver-backed turn through the `RuntimeDriver` port) **before**
   any file is deleted. There is no flag that skips it
3. **MUST** fail closed: a distillation failure (driver or model error, timeout, an empty reply)
   exits 1 naming its `failure_kind`, and every file is left as it was
4. **MUST** then delete `memory/*.md`, clear MEMORY.md (unless a distillation just refreshed it
   this invocation) and reset HEARTBEAT.md. For a pod Lead the reset also clears the docket-owned
   dispatch ledger region, so the ledger and `TASK_LIST.json` disagree until the next dispatch
   event or `docket setup check --fix` re-syncs it
5. **MUST** rebuild SOUL.md, AGENTS.md and (for an implementer with resources or a verify command)
   TOOLS.md from the member's metadata, and stamp the template version. It **MUST NOT** touch
   `INSTRUCTIONS.md`, `.docket-meta.json`, the fleet registration or the session keys
6. **MUST** write one `pod.reset` audit entry

### Pod Deletion (docket pod delete)

1. **MUST** require the pod's name: typed at a prompt on a terminal, or `--confirm <name>` off one.
   Off a terminal without `--confirm`, or with a `--confirm` that is not the pod's name, it **MUST**
   exit 1 naming `--confirm <name>` and delete nothing. There is no picker, and an agent or member
   id is refused as "not a pod"
2. **MUST** remove the workspace directory completely for every pod member
3. **MUST** unregister from docket's fleet registry (`fleet.json`)
4. **MUST** remove any Telegram bindings and conversation-registry entries
5. **SHOULD** display a deletion summary before asking
6. Deleting a pod **MUST** tear down every pod member and free the pod's
   allocated resources (port range, scratch dir)
7. Deleting a pod **MUST** remove its Docket-owned runtime directory, durable session histories,
   and JSONL trace directories for both the project id and its member ids. It **MUST NOT** delete
   or rewrite the global audit log; the deletion record remains as durable evidence.
8. The pre-deletion summary **MUST** list each member with its role.
9. An Implementer's git-worktree branch **MUST** be deleted at member teardown only when it is
   fully merged into the codebase's current branch (`edges/adapters/system.py`'s
   `git_branch_merged` against `git_current_branch(codebase)`, deleted with `git_branch_delete`'s
   `-d`, never `-D`). An unmerged branch, or a missing/failing git, **MUST** be left in place; the
   caller prints a one-line manual `git branch -D <branch>` note naming it rather than losing the
   work silently. A worktree-remove failure **MUST NOT** block workspace/fleet cleanup either way.
10. Deleting a pod **MUST** write one `pod.delete` audit entry.
11. Pod-level provisioning state **MUST NOT** outlive the pod: `free_pod_resources` (whole-pod
    teardown) **MUST** remove that project's `.pod-provision-locks/<hex>/` directory, once its own
    lock is released (never while held).

## Interface Contracts

### CLI Command Signatures

```bash
# Create a project pod from a blueprint; with no arguments the id, path and stack come
# from the cwd. --blueprint defaults to `software`. --pod full/--with apply only to it.
docket init [<project>] [location] [--blueprint <name>] [--pod full | --with reviewer,tester]

# Create one or more agents (or, with a `blueprint` field, pods) declaratively
# from a spec file (JSON, or YAML when PyYAML is present)
docket init --from <agents.yaml|agents.json>

# The roster. The pod comes from --pod, DOCKET_POD, then the current directory.
docket pod show [<member-id>] [--json]
docket pod add <role> [--count N] [--verify "<cmd>"]
docket pod remove <member-id> [--yes]
docket pod reset <member-id> [--yes]
docket pod delete [--confirm <pod>]
```

### Return Codes

- `0`: Success
- `1`: Any error (unknown agent, invalid arguments, permission problems, driver failures —
  docket's CLI-wide convention; see ../api/cli-interface.spec.md)
- `2`: A usage error — an unknown option, command or verb (Click)

## Examples

### Creating a Project Pod

```bash
$ docket init mywebsite ~/projects/website
→ Provisioning 'software' pod 'mywebsite' (lead, implementer)...
✓   mywebsite-lead  [lead]  anthropic/claude-haiku-4-5
✓   mywebsite-implementer  [implementer]  anthropic/claude-sonnet-4-6

✓ Pod 'mywebsite' created with 2 members!
```

### Resetting a Member

```bash
$ docket pod reset mywebsite-implementer --yes
→ Distilling memory before proceeding (one driver-backed turn)...
✓ Distilled 2 log(s) into MEMORY.md; original(s) archived under memory/.distilled/.
✓ Reset mywebsite-implementer: 2 memory log(s) cleared, workspace files rebuilt
→ Next: docket pod show
```

## Validation

### Pre-conditions
- User **MUST** have write permissions to `~/.docket`.
- Python 3.11+ **MUST** be available (docket's runtime requirement)

### Post-conditions
After successful creation:
- Workspace directory **MUST** exist at expected path
- All core files **MUST** be present and valid
- Agent **MUST** appear in `docket status` output
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
| Workspace corrupted | Missing files | Run `docket setup check --fix`, or `docket pod reset <member>` to rebuild its files |
| Distillation turn failed (model error, timeout, no credential) | `docket pod reset` (distillation is not optional) | Nothing was deleted (fail-closed); retry once the model endpoint is reachable |

## Performance Criteria

- Agent creation: < 2 seconds
- Agent listing: < 500ms for 100 agents
- Pod deletion: < 1 second
- Member reset: bounded by one driver turn (`config.DISTILL_TIMEOUT_S`, default 120s) rather than a
  fixed local-operation budget — it is a real, costed LLM call, not a file operation

## Changelog

### Version 2.0.0 (2026-10-08)

- Phase 39 (P39-10): the roster is `docket pod show|add|remove|reset|delete`. `docket info`,
  `docket delete`, `docket maintain` (every mode) and `docket add` are removed with their
  requirements. `pod remove` refuses the Lead and needs `--yes` off a terminal; `pod reset`
  distills first, fails closed and rebuilds the member's files from metadata; `pod delete`
  needs the pod's name typed or `--confirm <name>` and refuses a member id. New audit actions
  `pod.reset`, `pod.delete` (replacing `agent.delete`) and `pod.unset-verify`.

### Version 1.17.0 (2026-10-07)

- Phase 39 (P39-12): first run. `docket init` no longer bootstraps the home: with no model endpoint
  (`cli/_setup.py::readiness()`) it still builds the team and ends with `No model endpoint yet` and
  the single next step `docket setup`; the endpoint, baseline policies and permissions are
  `docket setup`'s.
- Phase 39 (P39-16): agent listing leaves this spec with `docket list`; members are read from
  `docket status`.

### Version 1.16.0 (2026-10-07)

- Phase 39 (P39-6): there are no shared agents. `docket init` provisions the pod only; `list` and
  `snapshot` show pod members; `delete` no longer has a specialist refusal because no specialist
  exists.

### Version 1.15.0 (2026-10-03)

- Legacy compatibility removed (no users; maintainer decision 2026-10-03): `maintain
  --distill-first` (a no-op affirmation of the default) is gone, so passing it is now an
  unrecognized flag (exit 2); `clean`/`reset`/error-recovery/performance text now describe
  distillation as the default rather than naming that flag. Return Codes gains `2` for usage
  errors.
- Dropped the `check` bullet claiming a specialist's missing `.docket-meta.json` is backfilled:
  the only implementation was `docket doctor`'s metadata backfill, deleted with the other legacy
  migrations; `maintain check` never did it.

### Version 1.14.0 (2026-09-25)

- Agent Deletion requirement 9: teardown deletes an Implementer's worktree branch only when it is
  merged into the codebase's current branch, and prints a manual `git branch -D` command otherwise
  instead of silently keeping (or losing) it.
- Agent Deletion requirement 10: whole-pod teardown now removes the project's
  `.pod-provision-locks/<hex>/` directory; it previously accumulated forever.

### Version 1.13.0 (2026-09-21)

- `rebuild` scoped to legacy flat agents only (W36-C5): it refuses a pod member (non-empty `pod`/`role` in meta) with exit 1 before any prompt or write, and no longer deletes `memory/*.md`.

### Version 1.12.1 (2026-09-18)

- Truth pass: creation is `docket init` (21abc85); `docket add` only adds roles to an existing pod.
  Retired the gateway-restart SHOULD (no gateway since D-19). Delete confirmation is a typed id,
  skipped for a non-interactive pod delete, specialists refused, flat-agent workspace removal
  asked separately. `maintain sessions` reports and never trims; `clean`/`reset`/`rebuild` all
  confirm, with no force flag. Signatures list `distill`/`--no-distill-first`; example output
  replaced with the real `docket init` output.

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
