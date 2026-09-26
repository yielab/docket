# Wave 44–46 worker packets — Phase 28, configuration format v1 and the two extension points (D-44)

Coordinator: the session that opened Phase 28 on 2026-09-26. Base commit for Wave 44: the commit
that added this file (`git log -1 --format=%h -- .agents/handoffs/wave-44-worker-packets.md` on
`main`); Waves 45 and 46 rebase onto the rollup commit that closed the previous wave. One card,
one Sonnet worker, one isolated worktree each. Decision, the format, the control-flow rule and
the plugin trust boundary:
[docs/adr/0010-config-format-v1-and-extension-points.md](../../docs/adr/0010-config-format-v1-and-extension-points.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P28-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 44 | P28-1, P28-2, P28-3, P28-4 | P28-2, P28-3, P28-4, P28-1 |
| 45 | P28-5, P28-6 | P28-5, P28-6 |
| 46 | P28-7 ∥ P28-8 | P28-7, P28-8 |

**Spec versions actually free at the base** (the ADR pre-assigned some that Phase 27 consumed):
new `specs/functional/config-format.spec.md` 1.0.0 (P28-1), 1.1.0 (P28-8); security-gates
0.26.0 (P28-2), 0.27.0 (P28-7); pipeline-format 2.7.0 (P28-3), 2.8.0 (P28-5), 2.9.0 (P28-6);
**role-archetypes 1.18.0** (P28-4; 1.16.0/1.17.0 exist); **pod-blueprints 1.10.0** (P28-8);
**pod-dispatch 6.19.0** (P28-5); cli-interface 1.36.0 (P28-1), 1.37.0 (P28-6), 1.38.0 (P28-7),
1.39.0 (P28-8). Inside Wave 44 no two cards touch the same spec file.

## 0. Rules for every worker

- **Isolation.** One branch `p28-<N>-<slug>` in your own worktree. Never touch `~/.docket`: every
  CLI run sets `export W=$(mktemp -d) HOME=$W/home DOCKET_HOME=$W/home/.docket`. pytest already
  isolates `DOCKET_HOME` through autouse fixtures. Never call a real model endpoint; tests use
  the fake drivers the neighbouring tests use.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Your worktree may start from a commit older than `main`: run `git merge --ff-only <base>`
  first (the base hash is in your prompt). Run everything with `env -u VIRTUAL_ENV uv run ...`:
  a worktree inherits the parent's `VIRTUAL_ENV` and it points at the wrong venv. If `click` is
  missing, `uv sync --extra mcp` once.
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the version + changelog entry (header **and** a `### Version
  X.Y.Z (2026-09-26)` changelog entry; the agent lane fails when one is missing). 3. Write the
  RED test and see it fail on the base for the stated reason. 4. Smallest implementation.
  5. Gates.
- **Test rule (ADR 0010).** One RED behavioural test in the module's existing `SUBJECT` file
  (round trip for a normaliser); a second only for the card's named negative case. Existing
  tests, goldens and specs are the no-change oracle. No agent-lane tests, no guards, no new test
  files unless the card names one. Do not add tests for every row of the acceptance table.
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints. Docket-owned JSON only through `edges/store.py`. Every tool call through
  `core/tools.py::dispatch_tool`. Every shell-out through `edges/adapters/system.py`.
- **The `kind` key.** Every parser in Wave 44 accepts and strips an optional top-level
  `kind: <its own kind>` (`policy`, `pipeline`, `role`) and refuses any other value with a
  message naming the expected one. P28-1's `load_document` only dispatches on it; it does not
  strip it for you. A document without `kind` still loads.
- **Comments.** No card or wave ids in code comments or docstrings (`tests/guards/
  test_comment_hygiene.py`); say what is true, not what changed. Docstrings are budgeted:
  run `scripts/maint/comment_lint.py --check` on every `.py` you touch.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `docs/` except `docs/commands.md`
  regeneration. Return the README/CHANGELOG line you would add instead of writing it. Never edit
  `scripts/metrics.py` or `scripts/validate-specs.sh`. Never touch `specs/functional/
  provider*.spec.md`, `core/provider.py` or anything Phase 29 (a separate planned phase).
- **Goldens.** `bash tests/golden/run.sh verify-all` stays byte-identical unless your packet
  names a case; then regenerate only that case and list every changed line with its reason.
- **Worker gates** before returning:

  ```bash
  env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src
  env -u VIRTUAL_ENV uv run pytest -q
  bash tests/golden/run.sh verify-all
  bash scripts/validate-specs.sh
  env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check   # if it fails on a missing `click`, say so; the integrator regenerates
  env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <every .py you touched>
  env -u VIRTUAL_ENV uv run pytest -q tests/guards/test_comment_hygiene.py
  ```

  `scripts/metrics.py --check` is expected to fail on a branch that adds tests; say so.
- **Commit.** One commit per card. Subject `Type: description` (`Add:`/`Fix:`/`Docs:`), ASCII,
  body says what was false and what is now true. **No AI mention, no `Co-Authored-By` trailer of
  any kind.** Before committing: `git diff --cached | command grep -nE '/home/|/tmp/claude|@gmail'`
  prints nothing. Do not push, do not merge into `main`.
- **Return** a delta of 1,500–3,000 characters, no logs: card / branch / commit; outcome;
  user-visible behaviour; changed paths and owned functions; spec sections + one changelog line
  per spec; README/CHANGELOG line for the integrator; RED evidence (test id, base failure reason);
  focused tests -> result; worker gates -> pass or first failing gate; goldens changed;
  missing/failed; pending in this card; later follow-ups (locators only); contention note.

Line numbers below were measured at the base commit and drift; re-locate every symbol with
`rg -n` before editing.

## P28-1 — every configuration file says what it is, and one command validates them all

Branch `p28-1-config-docs`. Spec: **new** `specs/functional/config-format.spec.md` 1.0.0 (a
functional spec needs the H2 sections `Purpose`, `Scope`, `Requirements`, `Interface Contracts`,
`Examples`, `Validation`, `Changelog` and the `**Version**`/`**Status**`/`**Last Updated**`
header lines the other specs carry; copy `pod-blueprints.spec.md`'s skeleton);
`specs/api/cli-interface.spec.md` -> 1.36.0 (a `docket validate` entry under "Configuration
Commands", Return Code Convention unchanged).

- **Where.** New `src/docket/core/config_docs.py`: `KINDS = ("role", "pipeline", "policy",
  "pod")`, `Document` (frozen dataclass: `kind`, `name`, `path`, `doc: dict`, `deprecated: bool`),
  `ConfigDocError(ValueError)` carrying `path`, `line`, `field`, `message`, `valid: tuple[str,
  ...]`, `suggestion: str` and a `__str__` that renders `file:line field: message (valid: a, b,
  c; did you mean "b"?)`; `load_document(path) -> Document` (YAML via the same defensive PyYAML
  import `core/pipeline.py::_load_yaml_text` uses; JSON is YAML), `validate_directory(dir) ->
  list[ConfigDocError]` (every `*.yaml|*.yml|*.json` under `roles/`, `policies/`, the directory's
  `pipeline.yaml`, `pod.yaml`, or a single file argument). Line numbers come from PyYAML's
  `yaml.compose`/node marks for the top-level key that failed; `0` when unknown. `did you mean`
  uses `difflib.get_close_matches`. The `provider` arm is **absent** (Phase 29 owns it; say so
  in the spec's Scope).
- **Dispatch, not parsing.** `kind: role` -> `core.archetypes.from_wire(name, doc)`; `kind:
  pipeline` -> `core.pipeline.load_pipeline(text)`; `kind: policy` -> `core.policy.
  validate_policy(path)` (P28-2 makes it read YAML on its branch; on the base it reads JSON, so
  test with a JSON policy file); `kind: pod` -> `core.pod_apply`'s manifest keys (add `kind`
  and `name` to `_MANIFEST_KEYS`, `pod_apply.py` L37). A file without `kind` dispatches by
  location (`roles/`, `policies/`, `pipeline.yaml`, `pod.yaml`) or by the caller's stated kind,
  and sets `deprecated=True`; the CLI prints one line per command: `note: <file> has no
  'kind:' -- add 'kind: <k>' (files without it stop loading one release after v1)`.
- **CLI.** New `src/docket/cli/_validate.py::run_validate(args) -> int`; register
  `@app.command("validate")` in `src/docket/cli/__init__.py` next to `cmd_completions`
  (~L2554) with a docstring that becomes `docs/commands.md` (`scripts/gen_cli_docs.py`).
  Default target `<cwd>/.docket` when it exists, else the cwd; a file argument validates one
  file. Prints every file (`ok <file> (<kind> <name>)` or the error), invalid first, exit 1 if
  any is invalid. Call-site swaps, one line each, leaving each command's own messages intact:
  `cli/_roles.py` `_add`/`_validate` (`parse_yaml_file` L139/L156 -> `load_document(...).doc`),
  `cli/_pipeline.py::_load_spec_file` (L121), `cli/_policies.py::_validate` (L254, only the
  file-path branch), `core/pod_apply.py::_plan_roles` (L174) and the manifest read in
  `plan_apply`. P28-2 owns `_plan_policies` and every other line of `cli/_policies.py`;
  P28-3 owns `load_pipeline`; P28-4 owns `from_wire`/`parse_yaml_file`. Touch nothing else in
  those files.
- **Goldens.** Adding a top-level command changes `tests/golden/cases/writers/completions_bash.
  golden` (the `commands=` line), `completions_zsh.golden` (the same list) and `tests/golden/
  cases/readonly/help.golden` (one line under the configuration group). Regenerate those three
  and list each changed line. Nothing else.
- **RED:** new `tests/unit/core/test_config_docs.py` (`SUBJECT = "docket.core.config_docs"`):
  `from docket.core import config_docs` fails on the base. Tests: a `kind: policy` YAML with
  `then: require_approval`... is P28-2's vocabulary; on this branch test `kind: banana` ->
  `ConfigDocError` whose `valid` names all four kinds and whose `str()` matches the format above
  (the RED), and a role YAML without `kind` -> loads, `deprecated=True`, `doc` byte-identical to
  `parse_yaml_file` (the negative/compat case). One CLI test in **new** `tests/integration/
  test_validate_cli.py` (`SUBJECT = "docket.cli._validate"`): a directory with one good role and
  one `kind: banana` file exits 1, prints both, the bad one first.

## P28-2 — policies read as "when this, then that", with predicates over the tool and its arguments

Branch `p28-2-policy-short-form`. Spec `specs/functional/security-gates.spec.md` -> 0.26.0: a
new `### Policy format v1 (short form and structured predicates)` subsection under Requirements
after "Policy engine on the live path" (~L311–415), and requirement 8 of that section names the
new `policies test` facts.

- **Where.** `src/docket/core/policy.py`: `normalize_policy(short: dict) -> dict` (pure; the
  canonical dict is today's `{id, applies_to, hook, match, action, message}` plus an optional
  `when: {tool?, path?, matches?, branch?, anyOf?: [...]}` copied through; mapping `name` ->
  `id`, `appliesTo` -> `applies_to`, `on: input|toolCall|output` -> `hook`, `when.matches` ->
  `match.pattern` (when no other predicate is present the canonical form is exactly today's, so
  the round trip holds), `then: allow|warn|ask|block|redact` -> `action` with `ask` ->
  `require_approval`); `read_policy(path) -> dict` (YAML or JSON, short or canonical, always
  returns canonical; the single reader `validate_policy`, `policy_eval_detail`, `install_policies`
  and the CLI use); `_validate_doc` (L42) validates the canonical form including `when`
  (unknown predicate key -> error naming the four; `anyOf` items are predicate mappings; `path`
  and `branch` are globs, `matches` compiles); `policy_files` (L87) globs `*.json`, `*.yaml`,
  `*.yml` in each directory, sorted by name. `install_policies` (L211) copies every template
  whatever its extension.
- **Facts beside the text.** New frozen dataclass `ToolCallFacts(tool: str, args: dict[str,
  Any], branch_of: Callable[[], str])`; `policy_eval_detail(..., call: ToolCallFacts | None =
  None)` and the same keyword on `policy_eval`/`policy_test`. Predicate evaluation: `tool` equals
  the tool name; `path` is `fnmatch` over the call's path argument (`path`, `file_path` or
  `file` -- whichever the args carry; a call with none never matches `path`); `matches` is the
  regex over the rendered text as today; `branch` is `fnmatch` over `call.branch_of()`, called
  at most once per evaluation and only when some loaded policy has a `branch` predicate. A
  policy with `when.tool`/`path`/`branch` and `call is None` never matches (text-only hooks).
  Implicit AND across keys; `anyOf` is OR over its items, AND with the siblings.
- **The one call in `core/tools.py`.** `evaluate_tool_call` (L216): build
  `ToolCallFacts(tool.name, args, branch_of=lambda: _sys.git_current_branch(str(ctx.roots[0]))
  if ctx.roots else "")` (`from docket.edges.adapters import system as _sys`, an inward import
  the module already makes for `toolbox`) and pass `call=` to `policy_eval_detail`. Nothing else
  in that file. `cli/_policies.py`: replace the four `json.loads` reads (L91, L114, L126, L280)
  with `read_policy`; `--tool` in `_test` already exists, add `--arg key=value` (repeatable) so
  `policies test pre_tool_call implementer "" --tool write --arg path=.github/x.yml` builds a
  `ToolCallFacts` (branch_of returns `""`). `core/pod_apply.py::_plan_policies` (L192): glob
  the three extensions; `_export_policies` copies by name unchanged.
- **Templates.** Rewrite the six `src/docket/templates/policies/*.json` as `*.yaml` in short
  form (`kind: policy`, `name`, `description`, `appliesTo`, `on`, `when: {matches: ...}`,
  `then`, `message`), same ids, same patterns (YAML single-quoted so backslashes survive), same
  actions; `git mv` so history follows. Existing `tests/unit/core/test_policy.py` and
  `tests/integration/test_gates_policies_approve_deny.py` fixtures that copy `*.json` templates
  need their glob widened (that is a fixture edit, not a new test). Recipe policies under
  `templates/recipes/*/policies/*.json` stay JSON (P28-8 converts them).
- **Goldens.** `tests/golden/cases/writers/policies_list.golden` changes only where a file name
  or extension is printed; regenerate it and list the lines.
- **Do not touch:** `core/archetypes.py`, `core/pipeline.py`, `cli/_roles.py`, `cli/_pipeline.py`,
  `cli/__init__.py`, `core/config_docs.py` (P28-1 creates it).
- **RED:** `tests/unit/core/test_policy.py`: `normalize_policy` does not exist on the base.
  The test is the round trip: the short form of `block-destructive` normalises to the dict
  `json.load` gives for the JSON template, and `policy_eval_detail` returns identical hits for
  both renderings. Negative case: `{tool: write, path: ".github/**", then: ask}` with
  `call=ToolCallFacts("write", {"path": "src/x.py"}, lambda: "")` -> `allow`; with
  `{"path": ".github/x.yml"}` -> `require_approval`.

## P28-3 — a pipeline step reads as "who, what is checked, where it goes"

Branch `p28-3-pipeline-short-form`. Spec `specs/functional/pipeline-format.spec.md` -> 2.7.0: new
`### Short form` subsection under Requirements after "Loading and validation" (~L275), plus one
line in "Document shape" saying `kind: pipeline` is accepted.

- **Where.** `src/docket/core/pipeline.py`: `normalize_pipeline(doc: dict) -> dict` (pure; the
  canonical mapping `PipelineSpec.model_validate` accepts today). Detection: a step entry is
  short when it is a one-key mapping `{<id>: <role-or-agent>}` or a mapping with an `<id>` key
  whose value is a string plus sugar keys (`verify`, `verdict`, `approval`, `instructions`,
  `timeout`, `retries`, `on`). Mapping: `verify: true` -> `gate: {type: mechanical}`; `verify:
  "<cmd>"` -> `{type: mechanical, command}`; `verdict: [A, B]` -> `{type: verdict, pattern:
  '^\s*(A|B)\b', passValues: [a]}` (first value passes, the rest are outcomes; `re.escape` each
  marker); `approval: <msg>` -> `{type: approval, message}`; `on: {<label>: {goto: <earlier
  step>, max: N}}` with exactly one backward edge and a verdict gate -> `rework: {to, when:
  [label lowercased], maxCycles: N}`. A target that is `lead|implementer|reviewer|tester` or a
  known role slug becomes `role:`; an id containing a `-`-separated pod member form (`pod.
  parse_member_id`-shaped, e.g. `myshop-implementer`) becomes `agent:`; do not import `pod`
  for it, use the slug shape rule the module already uses for `archetype`. A step with no gate
  key gets no `gate` (the role's contract applies, as today). `load_pipeline` (L396) calls
  `normalize_pipeline` before `model_validate` and strips `kind: pipeline`.
- **Refusal for what P28-5 has not shipped.** Any `on:` value other than the single backward
  `{goto, max}` on a verdict step (a forward `goto`, `fail`, `stop`, a bare step name, two
  edges, a backward edge without `max`) is a load error: `step '<id>': outcome routing beyond
  one bounded rework edge is not available yet`; a backward `goto` without `max` names the
  step and says `max` is required. The canonical models stay unchanged (P28-5 adds fields).
- **Recipes.** Rewrite the three `src/docket/templates/recipes/*/pipeline.yaml` in short form
  with `kind: pipeline`; `docket pipeline plan <file>` on each must be byte-identical to the
  base's output (capture the three outputs on the base first). `cli/_pipeline.py::_validate`
  help text may mention the short form; no other CLI change.
- **Do not touch:** `core/orchestrator.py`, `core/archetypes.py`, `core/policy.py`,
  `core/pod_apply.py`, `cli/__init__.py`, the recipe `roles/` and `policies/` files.
- **RED:** `tests/unit/core/test_pipeline__spec.py` (`SUBJECT = "docket.core.pipeline"`):
  `normalize_pipeline` does not exist on the base. The test is the round trip: the short form
  of `secure-build` -> `PipelineSpec.model_validate(normalize_pipeline(short)) ==
  load_pipeline(long).spec` for the base's long text. Negative case: a backward `goto` without
  `max` -> one error naming the step.

## P28-4 — a role file carries only what is enforced, and its prose lives in Markdown

Branch `p28-4-role-short-form`. Spec `specs/functional/role-archetypes.spec.md` -> **1.18.0**:
"Wire format (a user archetype YAML file)" (~L499) gains the short form with the `.md`
convention; "Archetype schema" notes `editRights` is derived from `cannot` in the short form.

- **Where.** `src/docket/core/archetypes.py`: `normalize_role(short: dict, base_dir: Path) ->
  dict` (pure except reading the named `.md`; returns the canonical wire dict `from_wire`
  accepts today). Mapping: `kind: role` stripped; `name`, `description` as is; `model: cheap|
  strong` -> `modelClass` (any other value is an `ArchetypeError` naming `docket models set
  <role> <id>` as the way to pin a model -- an archetype has no model-id field and this card
  adds none); `cannot: [...]` -> `deniedTools`, and `editRights` derived (`write` in `cannot`
  -> `read-only`, else `write`); exactly one of `verdict: [A, B]` -> `gateContract: {kind:
  verdict, regexes: [A, B]}`, `verify: true` -> `{kind: mechanical}`, `approval: true` ->
  `{kind: approval}`, none -> `{kind: none}`; two of them -> `ArchetypeError`; `instructions:
  <file.md>` (default `<name>.md` beside the YAML) -> `soulTemplate` = the Markdown up to an
  optional `## AGENTS` heading, `agentsTemplate` = the text after it, or the built-in default
  agents text when absent (find the constant the built-ins share, `_AGENTS_*` near L300+).
  `scope` defaults to `pod`, `version` to 1, `tokenBudget` to 6000. `parse_yaml_file` (L886)
  returns the document; add `load_role_file(path) -> dict` that parses and normalises when the
  document is short (`kind: role`, or any of `cannot|verdict|verify|approval|instructions|model`
  present) and returns it unchanged when canonical; `from_wire` (L202) accepts and strips
  `kind: role`. `cli/_roles.py` and `core/pod_apply.py::_plan_roles` call `load_role_file`
  where they call `parse_yaml_file` today (P28-1 swaps those same lines to `load_document`; the
  integrator reconciles -- keep your change to the one call expression).
- **Recipes.** Rewrite `src/docket/templates/recipes/secure-build/roles/security-vetter.yaml`
  in short form with `security-vetter.md` beside it; the rendered `SOUL.md` and `AGENTS.md` for a
  sample pod must be byte-identical to the base's (render both on the base first with `render`
  and the sample variables `validate_archetype` uses). `tests/integration/test_recipes.py`
  reads the recipe; adjust its fixture only if it globs `*.yaml` in a way the `.md` breaks.
- **Do not touch:** `core/policy.py`, `core/pipeline.py`, `cli/_policies.py`,
  `cli/_pipeline.py`, `cli/__init__.py`, `registry_for_role`, `load_registry`, `to_wire`
  (export in short form is P28-8), `docket roles show` output.
- **RED:** `tests/unit/core/test_archetypes.py`: `normalize_role` does not exist on the base.
  The test is the round trip: `from_wire("security-vetter", normalize_role(short, dir)) ==
  from_wire("security-vetter", long)` for the base's long YAML. Negative case: `verdict` and
  `verify` both present -> `ArchetypeError`.

## Wave 45 and 46 packets

Written by the integrator when Wave 44's rollup merges green; the card text in `TODO.md` and
the ADR's wave table are the contract until then.

---

## Wave 45 — control flow (written 2026-09-26 after the Wave 44 rollup `ea9e354`)

**Where the executor really lives.** The ADR and the two cards say `core/orchestrator.py` owns
outcome routing. It does not: `core/orchestrator.py` is the pure planner (`resolve_plan`,
`resolve_gate`, `render_plan`, `parse_verdict`, `run_group`); the loop that walks a task through
its steps is `core/dispatch.py::_run_pipeline` (~L1699), the gates are evaluated by
`_evaluate_mechanical_gate` (~L1384) and `_evaluate_verdict_gate` (~L1443), one hop is
`_execute_unit` (~L1564), an outcome is `_UnitOutcome` (~L962, `kind` in advance | rework |
blocked | waiting_approval | failed | cancelled), and a resumed task replays its history in
`_replay_pipeline_position` (~L835). `PlannedUnit` (orchestrator ~L40) is what the loop sees for
a step. Both Wave 45 cards edit `core/dispatch.py`, `core/orchestrator.py` and `core/pipeline.py`;
ownership below is by **function**, and the integrator resolves a same-function conflict by
keeping both blocks and importing the module.

| Card | `core/pipeline.py` | `core/orchestrator.py` | `core/dispatch.py` |
| --- | --- | --- | --- |
| P28-5 | `Step.on`, `Step.until`/`Step.max`, the `PipelineSpec` route validators, the `on`/`until` arms of `normalize_pipeline` (lifting P28-3's refusal) | `PlannedUnit.on`, the route suffix in `_gate_label`/`_render_unit` | `_UnitOutcome.label`, `_evaluate_mechanical_gate`/`_evaluate_verdict_gate` return values, **new** `_route_outcome` called from `_run_pipeline` after an outcome, `HopResult.next_step` + `_hop_record`/`_hop_from_record`, `_replay_pipeline_position` |
| P28-6 | `Step.when`, `Step.run`, the `run` arm of `_normalize_short_step` | `PlannedUnit.when`/`run`, `_resolve_unit` for a command step, the `when`/`run` text in `_render_unit` | **new** `_step_skipped` and **new** `_run_command_step`, each called from the top of `_run_pipeline`'s loop body before `_execute_unit` |

Spec versions: pipeline-format 2.8.0 (P28-5) and 2.9.0 (P28-6) -- both add a changelog entry
under the same `## Changelog`, the integrator keeps both newest first; pod-dispatch **6.19.0**
(P28-5, "Generalized gate execution" + the trace-event list) and **6.20.0** (P28-6, a new
"Conditional steps and command steps" subsection + the trace-event list); cli-interface 1.37.0
(P28-6) only if `docket pipeline` help text changes. Base commit for Wave 45: the commit that
appended this section (`git log -1 --format=%h -- .agents/handoffs/wave-44-worker-packets.md`).

## P28-5 — outcomes route the pipeline, and every loop has a bound

Branch `p28-5-outcome-routing`. Specs: `pipeline-format.spec.md` -> 2.8.0 (new `### Outcome
routing` subsection after "Short form"; "Rework edges" gains one sentence saying `rework` is the
canonical spelling of the one bounded backward verdict edge and `on:` generalises it);
`pod-dispatch.spec.md` -> 6.19.0 ("Generalized gate execution" item 2 gains the routing rule; the
"Trace events this pipeline emits" block gains `route_taken`).

- **Model.** `Step.on: dict[str, Route] | None` where a `Route` is a mapping `{goto: <step id>,
  max: <int >= 1, required when the target is at or before this step>}`, or one of the strings
  `fail` | `stop` | `<step id>` (a bare forward target). Keys are outcome labels, compared
  case-insensitively: a verdict gate's matched value, `pass`/`fail` for a mechanical gate,
  `approved` for an approval gate (a denial never reaches routing: it fails the task before the
  hop, as today). `Step.until: Literal["verify"] | None` with `Step.max: int | None` is sugar the
  normaliser rewrites to `on: {fail: {goto: <this step>, max: N}}` (only valid with a mechanical
  gate); the canonical form never carries `until`. PyYAML reads a bare `on:` as `True`: reuse
  P28-3's `_get_on` so both spellings load, and make the canonical key the string `"on"`
  (`Field(alias="on")` on a Python attribute named `on_` or similar). `PipelineSpec` validators:
  every `goto` names a step in the document; a backward or self `goto` without `max` is an error
  naming the step; a step no path reaches (walk from step 0 through the default next step and
  every `goto`, stopping at `fail`/`stop`) is an error naming it. Byte-identity: a verdict step
  whose only `on:` entry is one backward `{goto, max}` keeps normalising to `rework` exactly as
  P28-3 shipped (the three recipes and `render_plan` on them stay byte-identical); every other
  `on:` shape now becomes the canonical `on` field instead of the "not available yet" error --
  delete that error and its test, and replace the test with the round trip below.
- **Executor.** `_UnitOutcome` gains `label: str = ""` (the outcome label above, `""` for a step
  with no gate). `_evaluate_mechanical_gate` sets `label="pass"|"fail"`; `_evaluate_verdict_gate`
  sets `label=<verdict>` and, **before** its rework/fail handling, returns
  `_UnitOutcome(kind="routed", label=verdict, hops=[hop])` when the unit's `on` map has an entry
  for that label (so `on:` beats the built-in fail; a label the map does not name behaves exactly
  as today, including the legacy trace event names). Same for a mechanical `fail` with an `on`
  entry. New `_route_outcome(ctx, node, outcome, pipeline_index) -> tuple[int | None, str]`
  resolves a `routed` outcome: `fail` -> the task fails with reason `step '<id>' outcome <LABEL>
  routed to fail`; `stop` -> the task ends `done` (return `None` and a reason the loop records);
  `goto` -> the target index, a backward jump counting against `max` in a `ctx.route_counts`
  dict keyed by `(step_id, label)` (add it beside `rework_counts`), exhausted -> the task fails
  naming step, label and max. Every decision emits a `route_taken` trace event with
  `{"step", "outcome", "target"}` (`target` is `fail`/`stop`/the step id). `_run_pipeline`
  handles `kind == "routed"` by calling `_route_outcome`; nothing else in the loop changes.
  `HopResult` gains `next_step: str | None = None`, persisted by `_hop_record`/`_hop_from_record`
  and set by the router on the routed hop, so `_replay_pipeline_position` follows it on resume
  (recounting backward jumps into `route_counts`, which `_UnitContext` must carry in).
  `PlannedUnit` gains `on: dict[str, Any] | None` copied from the step by `_resolve_unit`;
  `_render_unit` appends ` on FAIL->escalate, PASS->stop` (labels upper-cased, targets as
  written) when the step has an `on` map.
- **Do not touch:** `_execute_unit`'s body, `_compose_hop`, the approval gate functions,
  `core/pod_apply.py`, `cli/`, and anything P28-6 owns above (`when`, `run`, command steps).
- **RED:** `tests/unit/core/test_pipeline__spec.py` (`SUBJECT = "docket.core.pipeline"`):
  `until: verify, max: 2` normalises to `on: {fail: {goto: <self>, max: 2}}` and loads (on the
  base `on` is refused as "not available yet"); negative case: an unreachable step is a load
  error naming it. One execution test in `tests/integration/test_generalized_gates.py`
  (`SUBJECT = "docket.core"`, copy its fixture shape and `FakeDriver`): a verdict step with
  `on: {FAIL: escalate}` where `escalate` is a later approval step reaches `waiting_approval` at
  `escalate` after the fake driver answers `FAIL`, and the trace has one `route_taken`. No other
  new tests; the existing rework tests are the byte-identity oracle.

## P28-6 — a step can be skipped on a closed predicate, and a step can be a command

Branch `p28-6-when-and-command-steps`. Specs: `pipeline-format.spec.md` -> 2.9.0 (new
`### Conditional steps and command steps` subsection after "Short form"; "Steps" gains the
`run` xor `role`/`agent` rule); `pod-dispatch.spec.md` -> 6.20.0 (a new `### Conditional steps
and command steps` requirements subsection after "Generalized gate execution"; the trace-event
list gains `step_skipped` and `command_step`); `cli-interface.spec.md` -> 1.37.0 only if you change
`docket pipeline` help text.

- **Model.** `Step.when: When | None` where `When` is a Pydantic model with `extra="forbid"` and
  exactly three optional predicates: `changed: str` (glob), `var: str` with `is: str` (alias
  `is_`), `memberPresent: str` (alias `member_present`); at least one must be set; more than one
  is AND. `Step.run: str | None`: a command step targets `run` instead of `role`/`agent` (xor with
  both), may carry `timeout`, `when` and P28-5's `on`, and must not carry `gate`, `instructions`,
  `retries`, `archetype` or `parallel`. Short form: `- lint: {run: "ruff check ."}` (a one-key
  mapping whose value is a mapping with `run`) becomes `{id: lint, run: ..., <sugar>}` in
  `_normalize_short_step`; `- lint: "ruff check ."` is **not** a command step (a string target is
  a role or agent, as P28-3 defined).
- **Planner.** `PlannedUnit` gains `when: dict[str, Any] | None` and `run: str | None`;
  `_resolve_unit` gives a command step `member_id=None`, `skipped=False` (it needs no member),
  and `core/pod_apply.py::unresolvable_pipeline_steps` must not report it (one `if unit.run` guard
  -- the only line you touch in that file). `_render_unit` prints `run 'ruff check .' [gate: exit
  code]` for a command step and appends ` when changed=src/**` (or `var=name is value`,
  `memberPresent=role`) for any step with `when`.
- **Executor.** Two new functions in `core/dispatch.py`, each called at the top of
  `_run_pipeline`'s loop body for a `PlannedUnit` before `_execute_unit` runs (P28-5 adds a call
  *after* the outcome; keep your two calls together at the top). `_step_skipped(ctx, node,
  prior) -> bool` evaluates `when`: `changed` = any path from `_sys.git_changed_files(cwd)`
  matches the glob (`fnmatch`), `cwd` being the latest successful Implementer worktree
  (`_prior_implementer_worktree(prior)`) or the Lead's codebase; `var`/`is` compares the resolved
  pipeline variable's string form (find where `_UnitContext` carries the resolved variables, or
  add `variables: dict[str, str]` to it from `dispatch_task`'s resolved mapping); `memberPresent`
  checks `ctx.id_to_index`'s roster source (`pod_full_roster(ctx.project)`). A false predicate
  emits `step_skipped` `{"step", "when"}` and the loop advances to the next index with no hop.
  `_run_command_step(ctx, node, prior) -> _UnitOutcome` runs `node.run` through
  `_sys.run_verify_cmd(cmd, cwd, node.timeout or ctx.resolved_verify_timeout)` in the same `cwd`
  rule, after `classify_command(cmd, extra_bins=<the pod's allowCommands>)`: `allow` runs;
  anything else is refused as `failed` with the classifier's reason under `approvalMode refuse`,
  and under `wait` goes through `_gate_pre_hop_approval` exactly like an approval gate (the step
  id is the role name in the approval record). The outcome is a `HopResult` with `role=<step
  id>`, `member_id=""`, `output=<captured, redacted>`, `ok=<exit 0>`; a `command_step` trace
  event `{"step", "cmd", "exit"}`; `_UnitOutcome(kind="advance"|"failed", label=...)` where the
  label is `pass`/`fail` unless the last stdout line is a single uppercase token, which becomes
  the label (P28-5's `on:` reads it). No model call, no cost, no session.
- **Do not touch:** `_execute_unit`, `_evaluate_*_gate`, `_replay_pipeline_position`,
  `_UnitOutcome`'s fields (P28-5 adds `label`; construct yours with the fields that exist on your
  base and say so -- the integrator wires the label), `Step.on`, `cli/`.
- **RED:** `tests/unit/core/test_pipeline__spec.py`: a `run:` step is rejected as an unknown key
  on the base; it loads and `render_plan` shows `run 'false' [gate: exit code]` after. Two
  execution tests in `tests/integration/test_generalized_gates.py`: `run: "false"` fails the
  task with no `FakeDriver` call for that step and a `command_step` event; `when: {changed:
  "src/**"}` on a tree whose only change is under `docs/` skips the step (`step_skipped` event)
  and the next step runs. No other new tests.
