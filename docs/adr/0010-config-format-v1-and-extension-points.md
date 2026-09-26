# ADR 0010 (D-44): Configuration format v1 and the two extension points

**Question:** After Phase 27 decides *where* each configuration file lives (ADR 0009), the files
themselves still use two languages (YAML, JSON), two casings (camelCase, `applies_to`), three
vocabularies for one idea (`gateContract`, `gate`, `action`), runtime jargon (`hook:
pre_tool_call`, `match.type: regex`, `action: require_approval`) and a hand-written regex to say
"this role emits a verdict". Real pipelines need control flow, real policies need predicates over
the tool and its arguments, and a team with a genuinely complex case needs an escape into code —
the way Drupal's migrate YAML declares a chain of named `process` plugins and lets a custom plugin
carry the rest. What should the format be, what control flow does it carry, and how does code
extend it without dissolving the governance guarantee?

**Where decided:** 2026-09-26, as Phase 28. **Activation gate:** Phase 27 closes (Phase 27 decides
scope and location; this phase decides shape; mixing them in one card set would leave neither
clean).

**Evidence** (read at `88f184e`):

| Fact | Locator |
| --- | --- |
| Policies are JSON with snake_case keys and runtime vocabulary | `core/policy.py` module docstring: `{ "id", "applies_to", "hook", "match", "action" }`; `templates/policies/*.json` |
| A verdict gate is a user-written regex plus three lists | `core/pipeline.py::VerdictGate` (`pattern`, `pass_values`, `rework.when`); every shipped recipe repeats `'^\s*(APPROVE\|REQUEST-CHANGES)\b'` |
| A role carries a descriptive field that enforces nothing beside the one that does | `core/archetypes.py::RoleArchetype.edit_rights` ("descriptive only") next to `denied_tools` |
| The policy engine sees rendered text, not the tool and its arguments | `core/tools.py::evaluate_tool_call` calls `policy_eval_detail(ctx.role, "pre_tool_call", render_tool_call(tool.name, args))` |
| Control flow is one backward edge | `core/orchestrator.py`: a step reworks only through its own `VerdictGate.rework`; there is no outcome map, no bounded self-retry, no conditional skip, no command step |
| No file says what it is | no `kind` key anywhere; the loader is chosen by the caller |
| Prior ruling on formats | `internal-docs/positioning-audit-2026-09-26.es.md` §10 (gitignored) |

The trigger is an explicit scoped request (2026-09-26: "a standard structure easy to read for
someone who is not a docket expert, pipelines and policies in a clear language, and an extension
mechanism for complex customization"). No quantitative threshold is invented.

## Decision

**One language, one casing, one envelope; a short form for people over the canonical form the
engine already runs; control flow as bounded data; and two extension points — a command for
pipelines, a hashed Python predicate for policies — never an expression language.**

### 1. The envelope

Every configuration file is YAML (JSON stays valid YAML, so nothing existing stops loading),
camelCase, and starts with `kind:` and `name:`. Four kinds: `role`, `pipeline`, `policy`, `pod`
(the Phase 27 manifest). One entry point, `load_document(path)`, dispatches on `kind` with a
`match` over four values; a file without `kind` loads through today's parser with a deprecation
line, for one release. `docket validate [dir]` validates every kind and the manifest with errors
that name file, line, field, the valid values and a suggestion.

### 2. Short form over canonical form

The user writes sugar; a normaliser turns it into the canonical form that exists today; the
engine, `plan`, `run`, `policy_eval` and `registry_for_role` never see the sugar. Three pure
functions, each proven by one round-trip test (`normalize(short) == long`). `export` writes the
short form.

```yaml
kind: role
name: security-vetter
model: strong                        # cheap | strong | a model id
cannot: [write, edit, bash]          # the only enforcement field; editRights is dropped
verdict: [APPROVE, REQUEST-CHANGES]  # or verify: true | approval: true | nothing
instructions: security-vetter.md     # prose in Markdown, same ${variables}
```

```yaml
kind: pipeline
name: secure-build
steps:
  - plan: lead
  - build: implementer
    verify: true                     # the member's verify command, or a command string
  - vet: security-vetter             # gate inherited from the role
    on: {REQUEST-CHANGES: {goto: build, max: 1}}
  - ship: operator
    approval: Review the change before it runs
```

```yaml
kind: policy
name: ask-before-secret-writes
appliesTo: [implementer]             # or "*"
on: toolCall                         # input | toolCall | output (default toolCall)
when: {tool: write, matches: 'api[_-]?key\s*='}
then: ask                            # allow | warn | ask | block | redact
```

Mapping: `hook: pre_tool_call` → `on: toolCall`; `match.type: regex` → `matches:`; `action:
require_approval` → `then: ask`; `gateContract.kind + regexes` → `verdict | verify | approval`;
`deniedTools` → `cannot`; `soulTemplate`/`agentsTemplate` → one Markdown file.

### 3. Control flow as bounded data

A pipeline is a state machine described as data, never a program:

- **`on:`** maps each outcome label of a step to `goto: <earlier or later step>` with a mandatory
  `max` on any backward edge, or to `fail | stop`. It generalises today's `rework` (which stays the
  canonical representation of the one backward edge to an earlier step).
- **`until: verify` + `max`** repeats a step until its mechanical gate passes.
- **`when:`** skips a step on a **closed** predicate vocabulary implemented in code and listed by
  `validate`: `changed: <glob>`, `var: <name>, is: <value>`, `memberPresent: <role>`. A skipped
  step emits a trace event.
- **A command step** `- lint: {run: "ruff check ."}` runs without an agent; its exit code and last
  stdout line are its outcome for `on:`. This is the language-agnostic escape hatch for pipelines,
  on the cold path.
- `plan` and `validate` reject a cycle without `max` and an unreachable step, and render the whole
  graph without running anything.

Policies gain structured predicates, evaluated with implicit AND and an `anyOf` list for OR:
`tool`, `path` (glob over a path argument), `matches` (regex over the rendered call), `branch`
(the worktree branch). No `not`, no arithmetic, no variables. `evaluate_tool_call` passes the tool
and its arguments to the engine beside the rendered text.

### 4. The extension points, and the trust boundary that shapes them

The analogy is Drupal migrate: YAML declares a chain of named plugins; a custom plugin is code with
a small fixed interface, discovered by convention. Python's own precedents are `conftest.py`,
MkDocs `hooks:`, Ansible's local `library/` and Airflow's `python_callable`: a file the framework
imports by convention, no packaging, `importlib` from the standard library, zero dependencies.
Technically this is a small module.

The difference that changes the design: a migration runs once, offline, as trusted code; a docket
policy runs on every tool call, inside the gate, in a repository the agent edits. A plugin loaded
from `<codebase>/.docket/plugins/` would let an agent rewrite its own gate for the next turn. So:

- **Predicate plugins for policies** (hot path, in process): a Python file defines
  `@predicate("touches_migrations")` over a typed `ToolCall` and `PolicyContext`, returning `bool`;
  the YAML uses it as `when: {plugin: touches_migrations, with: {paths: [migrations/]}}` and
  `then:` still decides. The public API is `docket.plugins` with `PLUGIN_API_VERSION`, versioned
  like the harness contract.
- **Loaded only from operator scope:** `~/.docket/plugins/` and the pod's `config/plugins/`.
  `docket pod <p> apply` copies a recipe's `plugins/*.py` into pod scope with its sha256, exactly as
  the bound pipeline is copied; a later edit in the codebase changes nothing until an operator
  applies again. The engine never imports from the codebase.
- **Fail closed, audited:** a plugin that raises, times out its budget or returns a non-bool
  yields `deny` naming the plugin; every invocation is audited with name, scope and hash;
  `docket plugins list` shows name, scope, file and hash; `docket policies test` runs them.
- **Command steps and gates for pipelines** (cold path): the escape is a command, which any
  language can provide and which needs no plugin API. Python gate plugins are deferred.
- **When a full policy language is genuinely needed,** rent the protocol: `kind: policy` with
  `engine: cedar | rego` delegating to an external engine, the same move as MCP and the model
  endpoint. A home-grown expression language is the one piece that never finishes being right.

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| `kind` envelope, `load_document`, `docket validate` | **DO** | P28-1 | one entry point, four values; backward compatible for one release |
| Policy short form + structured predicates (`tool`, `path`, `matches`, `branch`, `anyOf`) | **DO** | P28-2 | the largest practical gain; the engine gains the tool and args it already had at the call site |
| Pipeline short form (`id: role`, `verify/verdict/approval`, `on`) | **DO** | P28-3 | normaliser only; canonical unchanged |
| Role short form (`cannot`, `verdict/verify/approval`, `model`, `instructions.md`); drop `editRights` from the short form | **DO** | P28-4 | removes a field that enforces nothing |
| `on:` outcome map with `goto/max`, `until/max`, termination and reachability checks | **DO** | P28-5 | control flow that `plan` can draw |
| `when:` closed predicates and command steps | **DO** | P28-6 | conditional skip and the pipeline escape hatch |
| Predicate plugins, operator-scoped, hashed, fail-closed, audited | **DO** | P28-7 | the policy escape hatch with the trust boundary kept |
| Generated JSON Schemas, `export` in short form, docs and recipes converted | **DO** | P28-8 | editors autocomplete; what the user reads is what they would write |
| Python gate/step plugins | **DEFER** | — | command steps cover it. **Trigger:** a gate that needs typed access to hop artifacts, asked twice |
| Action plugins (`then: {plugin}`) | **DEFER** | — | **Trigger:** a redaction or transformation no built-in action expresses |
| Entry-point (`docket.plugins` group) packaging | **DEFER** | — | **Trigger:** one plugin shared by two installs or organisations |
| `engine: cedar \| rego` | **DEFER** | — | **Trigger:** a policy the predicate vocabulary cannot express, asked twice |
| Removing the pre-`kind` format | **DEFER** | — | one release after v1 ships |
| Expressions (`${{ a == b }}`), `not`, arithmetic, mutable variables, unbounded loops, `include`, pipeline inheritance, `pluggy` or any hook framework | **CUT** | — | the moment YAML stops being data, the non-expert needs an expert again |

## Test discipline

The Phase 27 rule stands: one RED behavioural test per card in the module's `SUBJECT` file. The
three normalisers are proven by one round-trip test each. P28-7 carries the phase's two negative
cases, because they are the guarantee: a plugin file present only in the codebase is **not**
loaded, and a raising plugin yields `deny`. No agent-lane tests, no guards; goldens change only
where CLI surface is added (`validate`, `plugins list`) and the card lists the lines.

## Waves (proposed; the integrator confirms from function-level contention)

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 44 | P28-1, P28-2, P28-3, P28-4 | new `core/config_docs.py` → P28-1; `core/policy.py` + the `policy_eval_detail` call in `core/tools.py::evaluate_tool_call` → P28-2; `core/pipeline.py` normaliser → P28-3 (the models stay canonical); `core/archetypes.py::from_wire`/`parse_yaml_file` → P28-4 |
| 45 | P28-5, P28-6 | `core/orchestrator.py`: P28-5 owns outcome routing and the termination/reachability checks; P28-6 owns step skipping and the command-step executor; `core/pipeline.py`: P28-5 the `on`/`until` fields, P28-6 the `when`/`run` fields |
| 46 | P28-7 ∥ P28-8 | new `core/plugins.py` + `cli/_plugins.py` + the predicate hook in `core/policy.py` → P28-7; schema generation, `export`, docs, recipes → P28-8 |

Pre-assigned spec versions (after Phase 27's): new `specs/functional/config-format.spec.md` 1.0.0
(P28-1), 1.1.0 (P28-8); security-gates 0.26.0 (P28-2), 0.27.0 (P28-7); pipeline-format 2.7.0
(P28-3), 2.8.0 (P28-5), 2.9.0 (P28-6); role-archetypes 1.16.0 (P28-4); pod-blueprints 1.8.0 (P28-8,
export); cli-interface 1.36.0 (P28-1), 1.37.0 (P28-6), 1.38.0 (P28-7), 1.39.0 (P28-8).

## Consequences

- A team member who has never read docket's docs can read a pipeline as a list of "who, then
  what is checked, then where it goes", and a policy as "when this, then that".
- The engine does not change shape; every guarantee Phase 26 and 27 made about consumers, fail-
  closed governance and provenance carries over because the canonical form is unchanged.
- The plugin API becomes a second published contract beside harness v1, with the same
  maintenance cost: a field renamed breaks someone else's plugin. Version it, and pin it by test.
- The README sentence after this phase: *define the team in files a newcomer can read, extend the
  rare complex case with a hashed plugin the operator applies, and never write a program in YAML.*
