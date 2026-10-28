# ADR 0035 (D-75): prompts are versioned configuration, and the harness is one a small model can use

**Question:** A prompt reaches the model from four places that do not know of each other: three
fixed strings in the hop composer, a role archetype's templates, an applied `roles.json` and the
`SOUL.md` rendered from it. None has a hash that reaches the hop's record, the resolution order
differs by kind, and the message a hop receives mixes the identity, the task and the hop in one
block that repeats the repository map every time. A small local model is hurt most by three of
those: the mixed layers, the map in every hop, and a verdict that depends on a last-line
convention. What shape makes a prompt a document that can be tested alone, varied by model class
and measured by version, and which of those three costs does docket remove?

**Where decided:** 2026-10-28, by the maintainer, as a scoped request from an audit of Tack's
prompts through docket to a local model (private document "Auditoría de prompts"). The trigger is
the request; no metric, threshold or saving is invented here. A card that can measure before it
ships names its free oracle (`scripts/maint/context_replay.py`, the captured-payload tests), and any
number it reports before that measurement is an estimate. The same day, the maintainer asked that
Phase 52 be validated and consolidated with this phase so that no file is opened twice for work one
pass can do: §"One schedule with Phase 52" records the result. Phase 53 on `TODO.md` is the card
list.

## What was found

Read at `52c22f89`; every locator is a symbol or a line, re-locate with `rg -n` before use.

1. **Three of four built-in hop prompts are code.** `hops/application/compose.py::_role_instructions`
   (`:69-101`) returns fixed strings for implementer, reviewer and tester; a step's `instructions`
   overrides them; a custom role resolves through `teams/role_schema.py::resolve_hop_instruction`
   (`:188`). Only the Lead is a registry archetype (`teams/builtin_roles.py:82`,
   `BUILTIN_ARCHETYPES`). No version, hash or test covers the three strings.
2. **One prompt per role, whatever the model.** `RoleArchetype` (`teams/role_schema.py:51-81`)
   carries `version: int`, `model_class` (`cheap|strong`), `token_budget`, `denied_tools`,
   `hop_instruction`, `soul_template`, `agents_template`. `model_class` is read only by
   `teams/model_selection.py:251` to pick a tier.
3. **Three copies, no link.** The authored pair `<role>.yaml` + `<role>.md` (recipes,
   `.docket/roles/`), the applied `roles.json` (`teams/roles.py::_pod_roles_file`, `:119-122`) and
   each member's rendered `SOUL.md`. The hashes docket already keeps are the bound pipeline's
   (`hops/application/steps.py:61`, `teams/pod_settings.py:113`), the applied directory's
   `configDigest` (`teams/pod_settings.py:187-195`, ADR 0012), and the per-turn sha256 of each
   codebase file a prompt composed from (`teams/workspace/repo_view.py`), which is not recorded on
   the hop.
4. **The system prompt has no identity.** `teams/identity.py::compose_agent_prompt` (`:531`) folds
   `SOUL.md`, `INSTRUCTIONS.md`, `AGENTS.md`, opt-in codebase files and the skills index per turn.
   `PromptComposition` (`agent/ports.py:294-303`) carries text, sections and budget: no hash, no
   sources.
5. **One mixed message per hop.** `_hop_message` (`compose.py:184`) joins the description, the root
   block (`teams/workspace/repo_map.py::task_root_block`, `:76`: working directory plus the
   tracked-file map), operator answers, gate failure, rework note, prior artifacts and the
   instruction. The map is already capped in characters (`render_repo_map`, `:40-55`,
   `Home.repo_map_max_chars`); it is not bounded by relevance, so every hop of every role pays for
   the same whole-tree summary. The layers are neither separable nor ordered for a cached prefix.
   P52-3 fixes the finalization request only.
6. **The verdict is a convention with a tool beside it.** `hops/application/verdict_tool.py`
   offers `verdict` to verdict-gated steps; the fallback is the last matching line read by
   `pipeline/domain/plan.py::parse_verdict` (`:347`), re-asked once by
   `hops/application/runner.py::_reask_unmarked_verdict` (`:45`). P52-7 forces `tool_choice` on
   the closing call for the `local` profile.
7. **The handoff is not the model's.** `HandoffArtifact` (`kernel/handoff.py:127`) is built by
   `tasks/application/record.py` (`:356-363`) with `summary` set to the raw output and
   `files_changed`/`diff` from the git probe (`:342`). The next hop gets the whole text, trimmed to
   budget.
8. **Resolution orders differ by kind.** Skills `codebase .docket/skills > pod config/skills >
   ~/.docket/skills` (`teams/workspace/skills.py::discover_skills`, `:109`); pipelines `pod
   config/pipelines > ~/.docket/recipes > shipped` (`steps.py::_task_pipeline_file`, `:136`);
   roles `pod roles.json > starter > built-in`; policies global plus pod, as a union
   (`governance/policy.py:380-382`); plugins global plus pod (`governance/plugins.py:78`); MCP
   servers pod plus global (`teams/mcp_servers.py:26-32`). A pod binds its pipeline by sha256:
   that is the model for the rest.
9. **Configuration and state share a level.** `kernel/home.py` puts `recipes/`, `skills/`,
   `policies/`, `plugins/`, the model and MCP catalogs beside `sessions/`, `traces/`,
   `workspaces/`, `cache/`, `audit.log` and secrets; a pod's authored overlay lives inside state,
   at `workspaces/pods/<pod>/config` (`Home.pod_config_dir`, `:502-504`).
10. **A hop does not say which prompt produced it.** `HopResult` (`tasks/domain/task.py:43`)
    records role, output, cost, usage and trace. Tack forwards hop evidence downstream, and the
    trajectory it could carry stays empty for that reason.
11. **The envelope loader is `teams/config_docs.py`** (found while planning, like 12-15) (539 lines, the `kind:` table). `governance`
    sits below `teams` in the layer order (ADR 0030), so a scope order that policies and plugins
    must share cannot live in `teams/`; `kernel/home.py` (`Home`) is the one place both read.
12. **`glob` exists** (`hops/application/builtin_tools.py:430`) and returns tracked paths by
    pattern.
13. **Repeated calls are already detected.** `agent/loop_steps.py::_ProgressDetector` (`:43-76`)
    ends a turn after `no_progress_rounds` rounds whose set of (tool, canonical args, ok, output
    sha256) was already seen.
14. **The CLI nests verbs under what they act on** (D-57, ADR 0022): ten top-level commands; a
    pod's configuration verbs are `pod update|export|validate|plan|check`
    (`interfaces/cli/commands/pod_config.py`).
15. **Files the phase touches sit near the 700-line rule:** `hops/application/driver.py` 678,
    `teams/identity.py` 659, `governance/policy.py` 658, `interfaces/cli/commands/agents.py` 643,
    `tasks/application/record.py` 601.

## Decision

1. **One authored form per kind, and a `prompt` kind.** A prompt is a file with YAML front matter
   and a Markdown body (the shape of `SKILL.md`, Prompty, dotprompt): `kind: prompt`, `name`,
   `version` (semver), `layer: identity|task|hop`, `for: <role>`, `modelClass:
   cheap|strong|any`, `inputs` (declared variables with a type; an undeclared `${var}` is a load
   error), `output` (a schema name such as `handoff/v1`), `tests` (a sibling file). Static text is
   the body; dynamic text is a declared slot. The kind joins the envelope table in
   `teams/config_docs.py`; its parsing lives in a new `teams/prompts.py` (finding 11 keeps
   `config_docs.py` under the cap). The three strings of `_role_instructions` and the built-in
   soul templates become shipped files under `src/docket/templates/prompts/`, with a published
   `prompt.schema.json` beside the other kinds'; `builtin_roles.py` keeps only
   what cannot be data. A role's `version` stays an integer: it is the major a reference names. The
   applied `roles.json` goes away: a pod overlay is the same authored files plus a lockfile.
2. **Four scopes, one order, one loader, one lockfile.** Repository `.docket/` > pod overlay >
   operator `~/.docket/config/` > shipped `templates/`, the same for roles, prompts, pipelines,
   skills, policies, plugins and MCP servers. The order is a `Home` method (finding 11) so that
   `governance` reads it without importing `teams`. Three rules bound it:
   - **For roles, prompts, pipelines, skills and MCP servers the first scope that has a name
     wins.**
   - **For policies and plugins the scopes are a union, as today.** A repository file never
     replaces an operator file of the same name, and a deny in any scope stands
     (`governance/policy.py:380-382`).
   - **Only text is read from the repository at turn time.** Prompts and skills are read live
     from the task's base commit through `teams/workspace/repo_view.py`, never from the writable
     worktree, as `AGENTS.md` and skills are today; otherwise an Implementer could rewrite the
     prompt its Reviewer runs. The kinds that grant or run something enter from the repository
     only through `docket pod update`, an operator command (ADR 0012): roles carry
     `deniedTools` (`role_schema.py:75`), pipelines run `verifyCmd`, MCP servers are commands, and
     plugins are code. A repository is untrusted input.

   One loader resolves a reference (`implementer@2`, `prompt:hop/implementer@2`) and computes its
   sha256. `docket pod update` writes `applied.lock` (path, scope, version, sha256), and
   `configDigest` becomes the sha256 of that lockfile, so the drift check `pod show` already does
   reads one source. `docket pod validate` checks that every reference resolves and every declared
   input is supplied. Authored configuration and state stop sharing a level: `~/.docket/config/`
   (catalogs, recipes, skills, policies, plugins, `pods/<pod>/`) and `~/.docket/state/`
   (sessions, traces, workspaces, cache, audit, secrets). `docket init` migrates the layout one
   way, and the old layout is read for one minor version. That reader is a compatibility reader,
   which board rule 7 forbids. It is the maintainer's explicit, time-boxed exception for this
   request (compatibility is decided per change under the amended D-57). It is deleted at the next
   minor release, and the follow-up carries that trigger.
3. **Versioning.** Semver is intent, the hash is identity. Major: the output schema or the layer
   changes (consumers break). Minor: behaviour changes, and the card re-measures. Patch: wording
   without measured effect. A published version is never edited. A reference names a major (`@2`)
   and the loader takes the newest file of that major. The hop manifest and the lockfile carry the
   hash.
4. **Three layers in a fixed order,** each a named section with its own token count: identity (the
   system prompt from identity-layer prompts), task (the brief and the bounded map, with paths
   relative to the repository root, so the section is byte-identical across the hops of one task),
   and hop (working directory, instruction, prior artifacts, gate failure, rework, operator
   answers). The order serves the cached prefix. This extends P52-3, which only moved
   finalization.
5. **The handoff is a tool call.** `verdict_tool.py` generalizes to `handoff` (`summary`,
   `files_changed`, `verdict`, `assumptions`, `questions`), validated against the prompt's `output`
   schema. `verdict` is deleted, with no shim (board rule 7). `_build_hop_result` takes the
   artifact from the call and keeps today's derivation as the fallback. `parse_verdict` reads the
   field first and the marker second. `questions` informs the next hop and the operator view; it
   never parks a task, because a question that needs an answer is a `consult` and one escalation
   record (D-72). P52-7's forced `tool_choice` names the step's closing tool rather than
   `verdict`, so this change needs no edit in `models/`.
6. **A manifest per hop.** `HopResult.promptManifest` holds, per layer, `{name, version, sha256,
   scope}`, the tokens per layer, and the model, family, class and profile. It is exposed on the
   task's `GET` (additive; API 7). `PromptComposition` returns its hash and its sources.
7. **Variants by model class, and a floor.** A role's prompts may exist per `modelClass`. The
   loader picks by the resolved model's class, which P52-7's profile names. `docket pod test
   <prompt>` (finding 14: under `pod`, not a new top-level `prompt` command) runs the prompt's
   `tests` file against a configured model. The `tests` file holds cases (inputs) and assertions
   (contains, matches schema, called `handoff`, under N tokens). A role refuses a model that
   fails its floor, with a fixed reason and never a silent fallback. The result is recorded once
   per model and prompt hash, by the store.
8. **The repository map is bounded by relevance.** `task_root_block` renders the paths the brief
   names (the Lead's locators and, after P53-8, the structured task's `paths`) plus one level.
   The Lead, which has no brief yet, keeps today's capped map. The block names `glob` for the
   rest (finding 12): no `repo_map` tool. P52-5's locators are absorbed into the same card.
9. **Tools and calls per hop.** The archetype and the step may declare `tools` (an allow-list)
   and `maxToolCalls`. `teams/role_composer.py` is the one place that decides what a hop sees: the
   profile's surface (P52-7), narrowed by the allow-list, minus the capabilities the role denies.
   An allow-list never grants a denied capability. A repeated identical call is
   `_ProgressDetector`'s business (finding 13): the role or profile sets its limit, and no second
   detector is written.
10. **A structured `task` on `POST /tasks/<pod>`** (objective, doneWhen, acceptance, constraints,
    risk, answers, verify, kind, paths) beside `description`, which stays for API 6 callers. Its
    consumer in docket is the task layer of decision 4, so the field is not unwired. Its consumer
    outside is Tack: named, not built here.

## What this phase refuses

| Refused | Why |
| --- | --- |
| A prompt registry service or database | Files, a loader and a lockfile; docket has no daemon to host one (D-20, D-24) |
| A template engine beyond `${var}` | Declared slots are testable; logic in templates is not |
| Per-model heuristics by name | ADR 0033 decision 1: adaptation is data on the catalog row |
| Any default sampling | The endpoint's own stays unless a row declares it (P52-7) |
| A second form for any kind | The applied `roles.json` is the second form this phase removes |
| A compatibility shim once a card deletes a name | Board rule 7. The one exception is decision 2's one-minor read of the old home layout, granted by the maintainer and deleted at the next minor |
| A `repo_map` tool | `glob` exists (`builtin_tools.py:430`) |
| A top-level `prompt` command | D-57: verbs nest under what they act on; prompts are pod configuration |
| A repository file shadowing an operator policy or plugin, or a repository role, pipeline, MCP server or plugin read at turn time | A repository is untrusted input; these grant or run something, so they enter only by `docket pod update` (ADR 0012) |

## One schedule with Phase 52

Phase 52 was validated against `52c22f89` the same day. Its line locators still land except
`compose.py:181` (now `:184`). Five things were stale or doubled, and they are fixed on the board:

- **Dependencies on closed work.** P52-5 waited on P51-6, and P52-9 and P52-12 on P51-9. Phase 51
  is closed.
- **Spec versions.** Phase 51 bumped `pod-dispatch` (11.0.0), `pipeline-format` (4.2.0),
  `serve-read-api` (5.0.0), `trace-store` (4.0.0) and `security-gates` (2.0.0) past the numbers
  the cards named.
- **The integration branch is `develop`.** `plan/phase-46-structure` merged as PR #5.
- **`driver.py` is at 678 of 700 lines** with three cards adding to it. The first card to cross
  makes a pure-move split by script, in its own commit.
- **Pairs of cards edited the same files in two passes.** They are merged:

| Merged | Into | Why one pass |
| --- | --- | --- |
| P52-8 (artifact store) | P52-2 | Same cut (`kernel/text.py`, `toolbox.py`), same condensation notice (`session.py`) |
| P52-3's `sampling` half | P52-7 | `sampling` is a profile field (ADR 0033 decision 1); same four files: catalog, loop types, wire, driver |
| P52-10 steps 1-3 and 5 | P52-9 | Same `ToolContext` (`registry.py`), `builtin_tools.py`, `driver.py`: the turn owns its clock and its processes |
| P52-10 step 4 (the `&` marker) | P52-4 | Same function, `classify_command`, the same corpus, the same spec row |
| P52-11's `fetch` description | P52-7 | P52-7 rewrites every tool description for the compact form |
| P52-5 (Lead locators) | P53-4 | Same function, `_hop_message`, and the bounded map reads the same locators |
| P52-7's surface in `role_composer.py` | P53-6 | One place decides what a hop sees: surface, then allow-list, then denials |
| P53 decisions 1 and 2 (`prompt` kind, built-ins as files) | P53-1 | A loader with no consumer is unwired machinery; the byte-identical composition is its proof |
| P53 decisions 5 and 6 (handoff, manifest) | P53-5 | Both change what a hop records, in `record.py` and `task.py` |

Phase 52 keeps nine cards (P52-1, 2, 3, 4, 6, 7, 9, 11, 12) and Phase 53 has nine. Both run on one
wave table, on `TODO.md` under Phase 52's run block.

## Cards

| Card | Owner files | Wave |
| --- | --- | --- |
| P53-1 the `prompt` kind, the loader, built-ins as files | `teams/prompts.py` (new), `teams/config_docs.py`, `teams/role_schema.py`, `teams/builtin_roles.py`, `compose.py::_role_instructions`, `pod_config.py::cmd_validate`, `src/docket/templates/prompts/` | 1 |
| P53-2 config beside state, one scope order in `Home` | `kernel/home.py`, `interfaces/cli/commands/agents.py` (init), `governance/policy.py`, `governance/plugins.py` | 1 |
| P53-3 one resolution order and `applied.lock` | `teams/roles.py`, `teams/apply/write.py`, `teams/apply/plan.py`, `steps.py`, `skills.py`, `teams/mcp_servers.py`, `pod_config.py`, `teams/prompts.py` | 2 |
| P53-4 three layers and the bounded map (absorbs P52-5) | `compose.py::_hop_message`, `agent/context.py`, `kernel/brief.py`, `teams/workspace/repo_map.py`, the Lead's hop prompt file | 4 |
| P53-5 the hop's record: `handoff` and the manifest | `verdict_tool.py`, `kernel/handoff.py`, `record.py`, `pipeline/domain/plan.py`, `hops/application/runner.py`, `tasks/domain/task.py`, `agent/ports.py`, `teams/identity.py` | 3 |
| P53-6 tools and calls per hop | `teams/role_composer.py`, `teams/role_schema.py`, `agent/loop_steps.py`, `agent/loop_types.py`, `pipeline/domain/spec.py` | 3 |
| P53-7 variants and the floor | `teams/prompts.py`, `teams/model_selection.py`, `interfaces/cli/commands/pod_prompt.py` (new), the CLI registry | 3 |
| P53-8 a structured `task` on the operator API | `interfaces/http/routes/task_create.py`, `tasks/domain/task.py`, `tasks/application/queue.py`, `compose.py` (task layer) | 5 |
| P53-9 docs | `docs/CONFIGURATION.md`, `docs/recipes.md`, `README.md`, `docs/AGENT-TEAMS.md` | close |
