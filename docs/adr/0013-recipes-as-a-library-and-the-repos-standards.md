# ADR 0013 (D-47): recipes as a library, and the repository's standards (AGENTS.md, skills)

**Question:** A recipe is a directory in the `.docket/` shape (`pod.yaml`, `roles/`, `pipeline.yaml`,
`policies/`, `plugins/`) and `core/pod_apply.py::plan_apply` treats every part as optional: a
directory with only `policies/` already applies as a policy pack, one with only `pipeline.yaml`
as a pipeline. Yet nothing says what a recipe brings — `pod.yaml` has no `description`, the only
listing of names is the error text of `resolve_recipe`, and the three shipped recipes are all
whole teams, so a reader concludes a recipe *is* a team. `apply` records `configSource` only
from the last directory that changed something, so composing two recipes leaves the record
pointing at the second. Meanwhile the agent-orchestration ecosystem has settled on two shapes docket
already has but does not show: single-concern files in the repository (GitHub Copilot's
`.github/agents/*.agent.md`, Claude Code subagents, CrewAI's `agents.yaml` beside `tasks.yaml`)
and versioned bundles with a manifest (Claude Code plugins), and on two repository-level
standards docket does not read at all: `AGENTS.md` (instructions for coding agents, one file at
the root, the same file Codex, Copilot, Cursor and Claude Code read) and Agent Skills
(`skills/<name>/SKILL.md`: `name` + `description` in frontmatter, the body loaded on demand).
The 2026-09-27 request: recipe handling that is robust, extensible and maintainable; example
recipes that apply the methodologies practised in autonomous-agent orchestration; stronger
policy and pipeline recipes; and AGENTS.md plus skills so the product extends under the
standards rather than beside them. What is the shape, and what earns a card?

**Where decided:** 2026-09-27, as Phase 31. **Activation gate:** none (Phase 30 and Wave 52
closed at `e3a765b`); the integrator batches by function-level contention as usual.

**Evidence** (read at `e3a765b`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| Every recipe part is optional; a policy-only or pipeline-only directory already applies | `core/pod_apply.py::plan_apply` (`manifest = {}` when `pod.yaml` is absent; `_plan_roles`/`_plan_policies`/`_plan_pipeline` each return empty for a missing part) |
| The manifest key set is closed and has no `description` | `core/pod_apply.py::_MANIFEST_KEYS`; `core/config_docs.py::PodDocument` |
| Nothing derives or prints what a directory contains; the names are listed only in an error | `core/pod_apply.py::resolve_recipe`; `cli/_validate.py::run_validate` prints one `ok` line per file |
| `configSource`/`configDigest` are written only when at least one item changed | `core/pod_apply.py::apply` (`if plan.has_changes():`) |
| The three shipped recipes are whole teams; the policy files match prose, not the call | `templates/recipes/*/pod.yaml`; `secure-build/policies/require-approval-secret-writes.yaml` (`matches: '...\.env\b.*write...'`) |
| Structured policy predicates exist and are unused by the recipes | `core/policy.py::_predicate_matches` (`tool`, `path`, `branch`, `anyOf`) |
| Project instructions are opt-in per pod and read `AGENTS.md` only when the operator names it | `core/pod.py::PodSettings.project_instructions`; `core/identity.py::_project_instructions_raw` |
| The system prompt has no skills section and no on-demand instruction loader; the built-in tool set is `read`/`write`/`edit`/`glob`/`grep`/`bash`/`fetch` | `core/identity.py::compose_agent_prompt`; `core/tools.py::build_default_registry` |
| A `ToolContext` already carries the project and the resolved roots a skill lookup needs | `core/tools.py::ToolContext` |
| ADR 0012 deferred user blueprints and said "no `docket recipes` command; a recipe is data" while the library had three entries | `docs/adr/0012-the-team-lives-in-the-repo.md` verdict table; `docs/CONFIGURATION.md` §3.10 |
| The ecosystem shapes | Claude Code plugins (`plugin.json`, marketplaces); GitHub Copilot custom agents (`.github/agents/<name>.agent.md`, org-level); CrewAI `config/agents.yaml` + `tasks.yaml`; the AGENTS.md convention; Agent Skills (`SKILL.md` frontmatter, progressive disclosure) — `internal-docs/recipes-scope-analysis-2026-09-27.md` (gitignored) holds the sources |

The trigger is an explicit scoped request; no quantitative threshold is invented.

## Decision

**A recipe is a directory whose scope is derived from its contents and shown, never declared.
The library ships single-concern recipes beside whole teams. The repository's `AGENTS.md` and
`.docket/skills/` are read as instructions under their standards; rules from the repository are
still applied only by an operator command.**

### 1. Recipes: what one is, how it says so, where it lives

1. **Scope is derived.** `core/pod_apply.py::summarize_recipe(directory)` counts what a directory
   holds — roles, policies, plugins, skills, members, settings, and whether it binds a pipeline —
   and `docket validate <dir>`, `docket pod <p> apply --dry-run`, `docket init --recipe` and
   `docket recipes show` all print that one summary. A declared `scope:` field is refused as an
   unknown key: a declaration can disagree with the directory, the drift shape this repository has
   paid for five times, and a derived count cannot.
2. **A recipe describes itself.** `pod.yaml` gains an optional `description` (the fourth
   manifest key beside `members`, `settings`, `pipeline`); `export` preserves it; the schema
   publishes it. It is prose for a listing, never read on the dispatch path.
3. **The record follows every validated apply.** `apply` records `configSource`/`configDigest`
   whenever a plan was validated against a directory, an all-`skip` plan included; the audit
   entry keeps its "only when something changed" rule. Composition is then honest: apply a team,
   apply a policy pack, `export --force` to `.docket/`, `apply` (all skip), commit — and the
   record names the repository. The repository stays the point of composition; recipes are seeds.
4. **Three scopes, nearest wins by name.** A directory path as given; else the operator's own
   `~/.docket/recipes/<name>/`; else the shipped `templates/recipes/<name>/`. This is the
   extension point: dropping a directory under `~/.docket/recipes/` makes it addressable from
   `init --recipe` and `pod apply` with no code and no registration.
5. **A listing, because discovery is the one thing data cannot do for itself.** `docket recipes
   list [--json]` and `docket recipes show <name|dir>` are read-only views over the three scopes:
   name, scope, description, derived summary. This reverses ADR 0012's "no `docket recipes`
   command" on its own rule of three: the library grows from three whole-team recipes to twelve
   of three kinds, and `init --help` cannot carry that table.
6. **The library is documented from data.** `scripts/gen_recipe_docs.py` renders
   `docs/recipes.md` from each recipe's manifest, derived summary and README body, checked in CI
   like `docs/commands.md`; a recipe cannot be documented differently from what it ships.

### 2. The library (twelve recipes, three kinds)

| Kind | Recipes | What "apply" plans on a lean pod |
| --- | --- | --- |
| Team | `secure-build`, `research-review`, `ops-approval` (existing; policies re-written on structured predicates) | roles + members + pipeline + policies |
| Policy pack | `git-safety`, `no-egress`, `secrets-guard`, `prod-approval` | policy items only |
| Methodology | `tdd` (red → check → green → test), `spec-first` (spec → critic gate → build → review), `reflexion` (build → critique loop, bounded → test), `dual-review` (build → parallel reviewer + critic), `frugal` (budget, one rework cycle, cheap-tier planning) | members it needs from the built-in and starter roles, a pipeline, and for `frugal` settings |

Each methodology recipe is the smallest pipeline that *is* the practice, expressed only with the
dialect that exists (`verify`, `verdict`, `on:` with `max`, `parallel`, `run:`, `model:`,
`settings`), and its README states the practice, the source idea, and what docket's gates make
structural about it. A policy pack uses `tool`/`path`/`anyOf` predicates over the call where the
call is what matters and `matches` only for text; every pack applies to every role it names,
accumulates most-restrictive with the operator's policies, and can be tested with `docket
policies test` before any agent runs.

### 3. The repository's standards

7. **`AGENTS.md` is read by default.** When a pod's `projectInstructions` is unset and the
   codebase root holds `AGENTS.md`, that file composes as the project-instructions section
   exactly as an explicitly named file does: screened through `pre_input` as untrusted, capped,
   reported under `projectInstructions`, shown by `config explain` with its source (`default` or
   `set`). An explicit `projectInstructions` list replaces the default entirely (it never adds).
   Nested `AGENTS.md` files (nearest-to-the-edited-file) are deferred: a turn has one root.
8. **Skills follow the Agent Skills shape.** `skills/<name>/SKILL.md` with frontmatter `name`
   (equal to the directory name) and `description`, an optional body and optional
   `scripts/`/`references/`/`assets/`. Three scopes, nearest wins by name: `<codebase>/.docket/
   skills/`, the pod's `config/skills/` (a recipe's `skills/` is applied there and exported
   back), `~/.docket/skills/`. Progressive disclosure is literal: the system prompt carries a
   `skills` section of `name: description` lines (descriptions screened through `pre_input`,
   the section capped and reported like every other); the body and a skill's files are read on
   demand through one new built-in tool, `skill`, of kind `read`, dispatched through the same
   chokepoint and deniable per role like any other. `allowed-tools` and other frontmatter keys
   are accepted and ignored: a role's denials are the only capability statement.
9. **Instructions from the repository are read live; rules are not.** `AGENTS.md` and repository
   skills are prose an agent could edit, and they reach a model only as screened instructions.
   Roles, policies, pipelines and settings from `.docket/` keep ADR 0012 rule 1: applied by an
   operator command, never re-read by dispatch. That line is what lets docket adopt the
   standards without an agent being able to loosen its own gates.

### 4. Amended spec rules (one owner each, listed so no two documents disagree)

| Spec | Rule | Card |
| --- | --- | --- |
| pod-blueprints "Pod manifests: apply" | manifest key set gains `description`; `apply` records source/digest on every validated apply; new "Recipe summary" requirement; `resolve_recipe` order adds the operator scope; `skills/` planned, applied, exported and digested | P31-1, P31-2, P31-6 |
| pod-blueprints, new "The recipe library" | the twelve shipped recipes by kind and what each plans on a lean pod | P31-3, P31-4 |
| config-format "The pod manifest key set" | `description` | P31-1 |
| cli-interface | `validate` summary line; `apply`/`init --recipe` header; `docket recipes list\|show`; `config explain` `projectInstructions` source and `skills` lines | P31-1, P31-2, P31-5, P31-6 |
| agent-loop "System prompt composition" | requirement 30: the `AGENTS.md` default; a `skills` section; the `skill` built-in tool | P31-5, P31-6 |
| cli-json-shapes | `config explain --json`: `projectInstructions` object and `skills` list | P31-5, P31-6 |
| workspace-structure | `~/.docket/recipes/` and `~/.docket/skills/` | P31-2, P31-6 |

Rules that stand: ADR 0009's additive, idempotent `apply`; ADR 0010's closed predicate
vocabulary and no new `kind`; ADR 0011's credentials by name; ADR 0012's operator-command-only
application; D-24's single operator.

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| Derived summary, `description`, source recorded on every validated apply | **DO** | P31-1 | the sentence a recipe needs to say about itself |
| `docket recipes list\|show`, operator scope `~/.docket/recipes/` | **DO** | P31-2 | rule of three fired (3 → 12); extension without code |
| Four policy packs; the two existing policies on structured predicates | **DO** | P31-3 | the request; the predicates exist and were unused |
| Five methodology recipes | **DO** | P31-4 | the request; each is data over the existing dialect |
| `AGENTS.md` by default | **DO** | P31-5 | one standard file, one existing section, zero new surface |
| Skills: three scopes, prompt index, `skill` tool | **DO** | P31-6 | the standard's own progressive disclosure, through the chokepoint |
| `docs/recipes.md` generated; docs; README lines; prose tests rebuilt | **DO** (integrator) | P31-7 | D-37 |
| `kind: recipe` with a declared `scope` | **CUT** | — | a declaration that can lie; §1 rule 1 |
| A recipe shipping MCP servers or credentials | **CUT** | — | a server's `kind` is an audited operator assertion (P27-3); ADR 0011 |
| Auto-loading a skill body into the prompt by task match | **CUT** | — | the standard says on demand; a tool call is auditable, a heuristic is not |
| `configSource` as a list of sources | **CUT** | — | the repository is the composition point (§1 rule 3) |
| Nested `AGENTS.md` (nearest to the file) | **DEFER** | — | **Trigger:** a monorepo pod asking for per-directory instructions |
| A remote recipe source (git URL, marketplace) | **DEFER** | — | **Trigger:** a second operator sharing packs across machines |
| `skills:` on a role to preload a body | **DEFER** | — | **Trigger:** a skill read on every turn of one role, seen in traces twice |

## Test discipline

One RED behavioural test per card in the module's `SUBJECT` file or the integration file the card
names; a negative case only for a fail-closed property (P31-1: `scope:` refused; P31-5: an
explicit list never gains the default; P31-6: a denied `skill` tool is a typed denial). The
library's proof is executable: every shipped recipe validates, applies onto a lean fixture pod,
and leaves every step resolvable (`tests/integration/test_recipes.py`, extended to the three
kinds); `reflexion` dispatches once against the fake driver and takes its bounded loop. Goldens
change only where a card lists the lines (`completions` for the new top-level command).
