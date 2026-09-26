# ADR 0009 (D-43): Per-pod configuration and portable teams

**Question:** Phase 26 (D-42) made every operator setting typed, validated, consumed and
explainable. Three registries a team needs in order to shape a pod are still global per machine:
the role overlay (`~/.docket/docket-roles.json`), the policy store (`~/.docket/policies/`) and the
MCP server registry. A recipe that bundles them is applied by hand with six commands per pod and
per machine. Every MCP tool is registered as a write, so a read-only role gets none. The Lead's hop
instruction is a fixed string. The request of 2026-09-26: each pod must carry robust, standard
customization; recipes must apply to any pod; the global layer is only the structural base that
works for everyone; configuration is per pod; MCP and tool permissions must be versatile — without
overengineering, and with only the tests that are strictly necessary. What is the architecture,
and which cards earn a place on the board?

**Where decided:** 2026-09-26, as Phase 27. Opens when the integrator confirms batching.

**Evidence** (read at `88f184e`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| One role overlay, no pod argument anywhere on the lookup path | `core/archetypes.py::load_registry` reads `ARCHETYPE_REGISTRY_FILE` only; `registry_for_role(base, role)`; callers `core/agent_loop.py::run_agent_turn`, `core/pod_provisioning.py` (two `load_registry().get(member.role)`), `cli/_pod.py` (`add`, `config set pipeline` plan), `core/dispatch.py` hop-message builder |
| One policy directory | `core/policy.py::policy_files` globs `POLICIES_DIR`; `policy_eval_detail(role, hook, text)` has no project; `core/tools.py::ToolContext.project` exists and is not passed to the policy call |
| Every MCP tool is a write; every server loads in every turn | `core/mcp_tools.py::_build_tool` registers `kind="write"` unconditionally; `McpServerConfig` has `name/command/args/env/timeout` only; `edges/adapters/docket_runtime.py::_load_mcp_tools(registry, role)` loads `load_mcp_servers()` whole |
| The Lead's instruction is fixed and step `instructions` skip it by design | `core/dispatch.py` hop-message builder, the `role == "lead"` branch ("plan for the Implementer (you never edit code yourself)") and its docstring's stated scope boundary |
| A recipe is six commands | `src/docket/templates/recipes/*/README.md` "Apply it"; `tests/integration/test_recipes.py` plans and dispatches `secure-build` |
| The manifest was deferred with a trigger that this request fires | ADR 0008 verdict table: "Declarative pod manifest (apply/diff/export) — DEFER — trigger: a pod reproduced on a second machine, or `POST /pods` needing a full spec" |
| Positioning finding | `internal-docs/positioning-audit-2026-09-26.md` §9 (gitignored): "the format exists, the distribution does not" |

The trigger is an explicit scoped request (2026-09-26) plus the deferred-item trigger above; no
quantitative threshold is invented for it.

## Decision

**Three scopes, one resolution rule, one directory per pod, and the recipe directory as the
manifest.** Wiring and one new command over machinery that exists; no registry framework, no
second file format, no reconciliation engine.

### The three scopes

| Scope | Holds | Lives in | Changed by |
| --- | --- | --- | --- |
| **Built-in** (structural, code) | the ten role archetypes, five blueprints, `SAFE_BINS`, baseline policy templates, the pipeline dialect | `src/docket/` | a release |
| **Global** (the operator, fleet-wide) | role overlay, policy store, the MCP server **catalog** (commands, credentials), model registry and policy, org specialists | `~/.docket/` as today | `docket roles add`, `docket policies`, `docket mcp servers`, `docket models` |
| **Pod** (this team) | role overlay, policies, member roster, the bound pipeline, pod settings, MCP server **selection**, extra tool denials | `PODS_DIR/<p>/config/` (`roles.json`, `policies/`) plus the existing Lead meta and bound pipeline copy | `docket pod <p> ...` and `docket pod <p> apply <dir>` |

`PODS_DIR/<p>/` already exists per pod (scratch, workdir). One new helper,
`config.py::pod_config_dir(project)`, names the subdirectory; nothing else moves. The bound
pipeline copy stays where P26-6 put it (the Lead's workspace) — moving it is a migration with no
measured need; `config explain` prints both paths.

### The resolution rule

- **Shape resolves nearest-wins by name:** pod overlay → global overlay → built-in. This is
  today's overlay semantics (`docket-roles.json` shadows a built-in by name) extended one level.
  It applies to role archetypes and to the Lead's hop instruction.
- **Governance only adds:** policies from the pod directory join the global files in the same
  most-restrictive-wins evaluation `policy_eval_detail` already performs, so a pod can add a
  `block` or `require_approval` and can never cancel a global one. A pod-level `deniedTools`
  is a union with the role's denials. `SAFE_BINS`, high-risk classes and opaque names are not
  scoped and stay as they are (`allowCommands` remains the one audited, per-pod loosening, with
  its P26-8 limits).
- A role overlay at any scope may shadow `reviewer` with fewer denials — exactly as the global
  overlay can today. That is why fleet-wide guarantees belong in **global policies**, which a pod
  cannot loosen; the README's "a Reviewer cannot write" is a statement about the shipped
  archetype and the policies you keep, not about a name.

### MCP and tool permissions

- The server catalog stays global (it holds commands and credentials). Each catalog entry gains
  two optional fields: `kind: read | write` (default `write`, today's behaviour) and `tools:
  [names]` (an allowlist of the server's tools to expose; default all). Both are **operator
  assertions**, set by `docket mcp servers add --kind read --tools a,b`, stored in the same file,
  and shown by `config explain`. Nothing in docket can prove a remote tool is read-only; the
  operator can, and is accountable for saying so. `_build_tool` registers the declared kind, and
  `registry_for_role`'s existing kind-based removal then lets a read-declared server reach a
  read-only role. This closes limit 1's remaining gap ("a read-only role gets zero MCP tools")
  without a false oracle.
- A pod selects servers by name with the setting `mcpServers` (default: every catalog entry,
  byte-identical to today). The consumer is `DocketDriver`'s loader seam; a name absent from the
  catalog refuses dispatch naming it.
- A pod can deny extra built-in tools for every member with the setting `deniedTools` (a union
  with the role's list, applied in `registry_for_role`). Per-agent overrides stay deferred with
  their D-42 trigger.

### The Lead is a role like the others

The built-in Lead text becomes the `lead` archetype's `hopInstruction`; a pipeline step's
`instructions` apply to the Lead as to any other step; the research, content and ops blueprint
pipelines carry their own Lead instruction. A research pod's planner stops being told to "plan for
the Implementer". No new field: `hopInstruction` and step `instructions` already exist.

### The recipe directory is the manifest

`docket pod <p> apply [<dir>] [--dry-run]` reads the shape the three shipped recipes already have —
`roles/*.yaml`, `policies/*.json`, `pipeline.yaml` — plus one small `pod.yaml`:

```yaml
members: [security-vetter]      # roles to add to the pod if absent
settings:                        # any `docket pod <p> config` key, same validation
  approvalMode: refuse
  mcpServers: [search]           # catalog names; an unknown name refuses before anything is written
pipeline: pipeline.yaml          # optional; defaults to pipeline.yaml when the file exists
```

`<dir>` defaults to `<codebase>/.docket/` so a team commits its team next to its code. `apply`
validates everything first (roles, policies, pipeline against the roster *as it will be after*
`members`), then writes to **pod scope only**: roles into the pod overlay, policies into the pod
directory, members via the existing provisioning, the pipeline via the existing bind, settings via
the existing setter. It is additive and idempotent: an identical item is skipped, a differing one
is replaced and named in the plan, nothing is ever removed. It is audited as `pod.apply`. `--dry-run`
prints the plan and writes nothing. `docket pod <p> export <dir>` writes the same shape back from
pod scope; **export → apply on a fresh home → identical `config explain --json`** is the
acceptance that makes "a pod reproduced on a second machine" true. Removal stays the explicit
`pod remove`, `config unset` and file deletion commands.

### Observability

`config explain` labels every resolved role, policy, MCP server and denial with its scope
(`built-in | global | pod`). `docket doctor` reports a malformed pod overlay entry or pod policy
file the way it reports the global ones (a broken pod *policy* fails closed at evaluation, as
P26-1 made the global ones).

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| Pod-scoped role overlay, nearest-wins by name | **DO** | P27-1 | one overlay file and a `project` argument through four lookup sites |
| Pod-scoped policies, most-restrictive-wins with global | **DO** | P27-2 | the pod directory joins the file list; `ToolContext.project` already exists |
| Declared MCP server `kind` and `tools` allowlist | **DO** | P27-3 | two optional fields; the kind-based narrowing already exists |
| Pod settings `mcpServers` and `deniedTools`, each with its consumer in the same card | **DO** | P27-4 | contract property 3: a setting ships with its reader |
| Lead instruction as data; step instructions reach the Lead | **DO** | P27-5 | removes a fixed string, adds no field |
| `docket pod <p> apply`, `.docket/` default, recipes converted to one command | **DO** | P27-6 | composes existing validated writers; the deferred trigger fired |
| `docket pod <p> export` and the round-trip oracle | **DO** | P27-7 | the "second machine" proof |
| Scope labels in `config explain`, doctor checks, `docs/CONFIGURATION.md` map | **DO** | P27-8 | contract property 5 |
| A pod-local MCP server catalog (own commands/credentials) | **DEFER** | — | **Trigger:** two pods need different credentials for the same server |
| Model per pipeline step | **DEFER** | — | role policy + `docket profile` pins cover it. **Trigger:** two steps of one role in one real pipeline need different models |
| Relative `agent:` references for fan-out (`implementer-2`) | **DEFER** | — | **Trigger:** a shipped recipe needs parallel members |
| Per-agent tool overrides | **DEFER** (unchanged) | — | D-42's trigger stands |
| Moving the bound pipeline copy under `config/` | **DEFER** | — | **Trigger:** the two-locations question reaches doctor or a user twice |
| `docket blueprints add` / `init --recipe` | **DEFER** | — | `pod.yaml` `members:` shapes a team on an existing pod. **Trigger:** the same custom shape provisioned at `init` a third time |
| `apply --prune`, `diff`, reconciliation | **CUT** | — | apply is additive and idempotent; removal is explicit. **Trigger to revisit:** an operator asks to undo a recipe in one step |
| Auto-apply on `docket init` | **CUT** | — | explicit only, like dispatch |
| A registry/loader abstraction, a plugin system, a second file format | **CUT** | — | §4.5 stands; three functions gain one argument |

## Test discipline for this phase (the "strictly necessary" rule)

- Each card adds **one** RED behavioural test in the owning unit or integration file (the file
  that already has the module's `SUBJECT`) and relies on the existing suite, goldens and specs as
  the no-behaviour-change oracle. A second test is allowed only for a fail-closed or
  most-restrictive property (P27-2, P27-4), because a governance claim without its negative case
  is the failure shape this repository keeps finding.
- P27-7's round-trip test is the phase's one integration proof; P27-6 reuses
  `test_recipes.py` by switching the recipe fixture to `pod apply` instead of adding a parallel
  file.
- No new agent-lane tests, no new guards, no golden regeneration except where a card adds CLI
  surface (`completions_*`, `help`) and says so line by line.

## Waves (proposed; the integrator confirms from function-level contention)

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 41 | P27-1, P27-2, P27-3 | `core/archetypes.py` → P27-1 only; `core/policy.py` → P27-2 only; `core/tools.py` → P27-2 owns the `policy_eval_detail` call inside `evaluate_tool_call` and nothing else; `core/mcp_tools.py`, `cli/_mcp.py` → P27-3 only; `edges/adapters/docket_runtime.py` → P27-1 the `registry_for_role`/meta plumbing, P27-2 the `ToolContext(...)` construction |
| 42 | P27-4, P27-5 | `core/pod.py`, `cli/_pod.py` config table → P27-4; `core/archetypes.py`: P27-4 owns `registry_for_role`, P27-5 owns the built-in `lead` literal and `resolve_hop_instruction`; `core/dispatch.py` hop-message builder, `core/blueprints.py` → P27-5; `docket_runtime.py::_load_mcp_tools` → P27-4 |
| 43 | P27-6 ∥ P27-8, then P27-7 | new `core/pod_apply.py` + `cli/_pod.py` `apply` → P27-6, then `export` in the same module → P27-7 serially; `cli/_config.py`, `cli/_doctor.py` (own check function), `docs/CONFIGURATION.md` → P27-8 |

Pre-assigned spec versions (the Wave 40 lesson): role-archetypes 1.12.0 (P27-1), 1.13.0 (P27-4),
1.14.0 (P27-5), 1.15.0 (P27-6, recipes section); security-gates 0.25.0 (P27-2); mcp-client 1.5.0
(P27-3), 1.6.0 (P27-4); pod-dispatch 6.16.0 (P27-4), 6.17.0 (P27-5); pipeline-format 2.6.0
(P27-5); pod-blueprints 1.5.0 (P27-5), 1.6.0 (P27-6), 1.7.0 (P27-7); cli-interface 1.30.0 (P27-1),
1.31.0 (P27-2), 1.32.0 (P27-3), 1.33.0 (P27-6), 1.34.0 (P27-7), 1.35.0 (P27-8).

## Consequences

- After Phase 27, the honest sentence becomes: *define the team in files next to the code, apply
  it to any pod in one command, reproduce it on any machine, and ask docket what is in effect and
  from which scope.* Before it, the sentence stops at "apply it in six commands".
- `docs/CONFIGURATION.md`'s ownership map gains a "scope" column and §3.10 shrinks to one
  command per recipe; the three recipe READMEs shrink the same way (P27-6/P27-8).
- README limit 1 loses its "zero MCP tools" clause once P27-3 ships and gains "as declared by the
  operator"; the integrator rewrites that sentence in the same commit (D-37).
- The unwired-machinery rule applies to every new setting here: `mcpServers` and `deniedTools`
  ship only with their readers (P27-4), never ahead of them.
