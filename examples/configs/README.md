# Example configurations

Two kinds of example live here:

- **`agents.yaml` / `agents.json`** — declarative fleet specs for `docket init --from <file>`.
  Verified against the real loader (`docket.cli._agents._cmd_add_declarative`): every entry
  actually provisions.
- **`*-agent-meta.json`** — sample `.docket-meta.json` files, one per workspace directory. These
  are illustrative snapshots of what docket itself writes, not files you hand-author and feed to
  a loader — validated against the real `AgentMeta` model (`core/models.py`).

## Declarative fleet specs

```bash
docket init --from examples/configs/agents.yaml
```

Re-applying is safe: an entry whose `id` already exists is skipped. Each entry needs an explicit
`id` (there is no auto-slugify from `name`) and `name`. Set `blueprint: software` (or `research`/
`content`/`ops`/`agentic-product` — see `docket roles list`) to provision a full **pod** (a Lead
plus that blueprint's worker roles); omit `blueprint` and you get a single flat legacy agent
instead, with no Lead/Implementer split. See the comments in `agents.yaml` for the full field
list.

## `.docket-meta.json` files

### repo-agent-meta.json

An Implementer inside a **pod** (`blueprint: software`), anchored to a codebase, with the
runtime-resource fields docket allocates once at pod provisioning: a disjoint port range, a
scratch directory, and (for a git codebase) a dedicated worktree/branch.

### task-agent-meta.json

A flat agent (no `blueprint`, no `role`, no `pod`) with no fixed codebase (`"codebase": ""`) and
a model **pinned** directly rather than following the role policy.

### multi-project-agent-meta.json

A pod Lead with a non-default `projectKey`/`sessionKey` (`agent:ecommerce:staging` instead of
`agent:ecommerce:default`) — the isolation primitive that keeps staging work from bleeding into
production context for the same codebase. Set with `docket scope <id> set <project-key>`.

### premium-agent-meta.json

A pod Implementer **pinned** to a stronger model (`modelSource: "pinned"`) for reasoning-heavy
work — set with `docket profile <id> <provider/model>`. A pinned agent is skipped by
`docket models set`/`preset` re-resolution; `docket profile <id> default` re-attaches it to the
role policy.

## Field reference

The authoritative shape is `AgentMeta` in `src/docket/core/models.py` (`extra="allow"`, so unknown
fields round-trip harmlessly — see `notes` in the examples above). The fields that matter day to
day:

| Field | Type | Notes |
|-------|------|-------|
| `kind` | `"project"` \| `"specialist"` | required |
| `role` | string | pod role (`lead`/`implementer`/`reviewer`/`tester`), empty for a flat agent |
| `pod` | string | which pod this member belongs to, empty for a flat agent |
| `blueprint` | string | which pod shape provisioned it (`software`, `research`, ...) |
| `model` / `modelSource` | string / `"policy"` \| `"pinned"` | `policy` follows the role→model table; `pinned` was set explicitly |
| `codebase` | string | absolute path; empty for a task agent with no fixed codebase |
| `sessionKey` / `projectKey` | string | isolation coordinate — see [docs/AGENT-TEAMS.md](../../docs/AGENT-TEAMS.md) |
| `portRangeStart` / `portRangeCount` / `scratchDir` | int / int / string | Implementer-only, allocated once at pod provisioning |
| `worktreeDir` / `worktreeBranch` | string | Implementer-only, present when the codebase is a git repo |

## Where these files live

```
~/.docket/workspaces/projects/<agent-id>/.docket-meta.json
```

(`DOCKET_HOME` relocates the whole tree; default is `~/.docket`.)

## Inspecting and fixing metadata

```bash
docket info <id>                   # formatted view
docket doctor                      # fleet-wide health, including metadata drift
docket doctor --fix                # re-sync what it can
docket maintain <id> rebuild       # deep: regenerate workspace files from metadata
```

There is no bare-JSON-editing helper shipped anymore (the old Bash `meta_get`/`meta_set`
functions were part of the pre-M6 Bash implementation and no longer exist) — read/write
`.docket-meta.json` directly with any JSON tool, or go through the commands above.

## See also

- [docs/commands.md](../../docs/commands.md) — full command reference
- [docs/AGENT-TEAMS.md](../../docs/AGENT-TEAMS.md) — the pod model (roles, scope, isolation)
