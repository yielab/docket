# Wave 41–43 worker packets — Phase 27, per-pod configuration and portable teams (D-43)

Coordinator: the session that opened Phase 27 on 2026-09-26. Base commit for Wave 41: the commit
that added this file (`git log -1 --format=%h -- .agents/handoffs/wave-41-worker-packets.md` on
`main`); Waves 42 and 43 rebase onto the rollup commit that closed the previous wave. One card,
one Sonnet worker, one isolated worktree each. Decision and the three-scope model:
[docs/adr/0009-per-pod-configuration-and-portable-teams.md](../../docs/adr/0009-per-pod-configuration-and-portable-teams.md).
The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P27-<N>`) is the
contract; this file is the map. Read §0 and your own packet only.

| Wave | Cards (parallel inside the wave) | Merge order |
| --- | --- | --- |
| 41 | P27-1, P27-2, P27-3 | P27-3, P27-2, P27-1 |
| 42 | P27-4, P27-5 | P27-5, P27-4 |
| 43 | P27-6 ∥ P27-8, then P27-9, P27-7, P27-10 | P27-8, P27-6, P27-9, P27-7, P27-10 |

## 0. Rules for every worker

- **Isolation.** One branch `p27-<N>-<slug>` in your own worktree. Never touch `~/.docket`: every
  CLI run sets `export W=$(mktemp -d) HOME=$W/home DOCKET_HOME=$W/home/.docket`. pytest already
  isolates `DOCKET_HOME` through autouse fixtures (`repoint_docket_home` for a second home).
  Never call a real model endpoint; tests use the fake drivers the neighbouring tests use.
- **Never `git stash`.** Set work aside with a WIP commit on your branch.
- Run everything with `env -u VIRTUAL_ENV uv run ...`: a worktree inherits the parent's
  `VIRTUAL_ENV` and it points at the wrong venv.
- **Order of work.** 1. Read the owning spec *section* and the neighbouring tests. 2. Amend the
  spec requirement text and add the pre-assigned version + changelog line. 3. Write the RED test
  and see it fail on the base for the stated reason. 4. Smallest implementation. 5. Gates.
- **Test rule (ADR 0009).** One RED behavioural test in the module's existing `SUBJECT` file; a
  second only for the card's fail-closed / most-restrictive negative case. Existing tests,
  goldens and specs are the no-change oracle. No agent-lane tests, no guards, no new test files
  unless the card names one.
- **Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py`, never
  prints. Docket-owned JSON only through `edges/store.py`. Every tool call through
  `core/tools.py::dispatch_tool`.
- **Forbidden files:** `TODO.md`, `ROADMAP.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `specs/README.md`, `.agents/`, `internal-docs/`, `docs/` except `docs/commands.md`
  regeneration and, for P27-8 only, `docs/CONFIGURATION.md`. Return the README/CHANGELOG line
  you would add instead of writing it. Never edit `scripts/metrics.py` or
  `scripts/validate-specs.sh`.
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

## P27-1 — a pod has its own role overlay, resolved nearest-wins

Branch `p27-1-pod-roles`. Spec `specs/functional/role-archetypes.spec.md` -> 1.12.0 (section
"User registry overlay", plus a sentence in "CLI surface"); `specs/api/cli-interface.spec.md`
-> 1.30.0 (the `docket roles` entry).

- **Where.** `src/docket/config.py` (`ARCHETYPE_REGISTRY_FILE` L26, `PODS_DIR` L35): add
  `pod_config_dir(project: str) -> Path` = `PODS_DIR / project / "config"`.
  `src/docket/core/archetypes.py`: `load_registry` (L680), `find_overlay_problems` (L696),
  `registry_for_role(base, role)` (L746), `add_user_archetype(doc)` (L837).
  Lookup sites that gain the `project` argument and nothing else:
  `core/agent_loop.py` L546 `registry_for_role(registry, ctx.role)` (pass `ctx.project`),
  `core/pod_provisioning.py` member lookups, `cli/_pod.py` `add` + pipeline plan,
  `core/dispatch.py` hop-message builder. `edges/adapters/docket_runtime.py::run_turn` (L162)
  already builds `ToolContext(project=trace_project or agent_id)` (L218–230); do not change that
  construction (P27-2 owns it) — read `ctx.project` where the registry is narrowed.
- **CLI.** `src/docket/cli/_roles.py` (`_list` L49, `_show` L77, `_add` L104): `--pod <p>`
  on `add`, `list`, `show`; `source` value `pod:<p>`. Tests for the CLI live in
  `tests/integration/test_archetypes.py` (`SUBJECT = "docket.cli._roles"`); core tests in
  `tests/unit/core/test_archetypes.py`.
- **Semantics.** Pod overlay (`pod_config_dir(p)/roles.json`, same wire format as
  `docket-roles.json`) resolves above the global overlay, above built-ins, by name.
  `project=""` everywhere is byte-identical to today. The pod directory is created 0700 on
  first write only.
- **Do not touch:** `registry_for_role`'s kind-based removal logic beyond adding the argument
  (P27-4 will change its body next wave); `core/policy.py`; `core/mcp_tools.py`; `cli/_doctor.py`.
- **RED:** `tests/unit/core/test_archetypes.py` — pod overlay `vetter` with `deniedTools:
  [write]`, global overlay `vetter` with `[]`: `registry_for_role(base, "vetter", project=p)`
  keeps `write` on the base (no `project` parameter). Negative case: `project=""` keeps `write`.
- **Goldens:** none expected. If `roles list` output changes without `--pod`, that is a defect.

## P27-2 — a pod has its own policies, and they only add

Branch `p27-2-pod-policies`. Spec `specs/functional/security-gates.spec.md` -> 0.25.0 (section
"Policy engine on the live path" ~L308 and "`docket policies` command" ~L809);
`specs/api/cli-interface.spec.md` -> 1.31.0 (the `docket policies` entry).

- **Where.** `src/docket/core/policy.py`: `policy_files()` (L80), `policy_eval_detail`
  (L99, note the early `POLICIES_DIR.is_dir()` return at L105 must not skip a pod directory),
  `policy_eval` (L166), `policy_test` (L174). `src/docket/core/tools.py::evaluate_tool_call`
  — you own **only** the call at L234 `policy_eval_detail(ctx.role, "pre_tool_call", rendered)`
  (add `project=ctx.project`); nothing else in that file.
  `src/docket/edges/adapters/docket_runtime.py::run_turn` L218–230: `ToolContext(project=
  trace_project or agent_id)`. A dispatch hop supplies `trace_project` = the pod; a standalone
  member turn does not. Resolve the pod once with `_pod.pod_of(agent_id)` (already used at L91
  and L109) so `project` is the pod for members and stays the agent id otherwise. If an existing
  test pins trace filing under the bare member id, keep that behaviour and report it.
- **Pod directory.** `pod_config_dir(project) / "policies" / "*.json"`. `pod_config_dir` is
  added by P27-1 in `config.py`; to stay independent, define the path locally in
  `core/policy.py` as `_cfg.PODS_DIR / project / "config" / "policies"` and leave a one-line
  note; the integrator collapses it onto `pod_config_dir` at merge.
- **Semantics.** Most-restrictive-wins across all files is the whole mechanism; a pod file adds
  and never overrides a global `block`/`require_approval`. Malformed pod file = `deny` naming
  the file through the existing fail-closed path (P26-1).
- **CLI.** `src/docket/cli/_policies.py` (`_list` L57, `_test` L140, `_validate` L233):
  `--pod <p>`. CLI tests: `tests/integration/test_gates_policies_approve_deny.py`; core tests:
  `tests/unit/core/test_policy.py`.
- **Do not touch:** `core/archetypes.py`, `core/mcp_tools.py`, `cli/_mcp.py`, any other
  function in `core/tools.py`.
- **RED:** `tests/unit/core/test_policy.py` — pod `p` blocks `make deploy`, no global file:
  `policy_eval("implementer", "pre_tool_call", "make deploy", project="p")` returns `allow` on
  the base. Negative case: global `block` + pod `allow`-shaped file still `deny`.
- **Goldens:** `policies_list` stays byte-identical without `--pod`.

## P27-3 — an MCP server declares its kind and its exposed tools

Branch `p27-3-mcp-kind`. Spec `specs/functional/mcp-client.spec.md` -> 1.5.0 (sections
"Configuration" L91, "Enumeration and adaptation" L103, "CLI (`docket mcp servers`)" L172,
"Wire format" L309, "CLI syntax" L328); `specs/api/cli-interface.spec.md` -> 1.32.0.

- **Where.** `src/docket/core/mcp_tools.py`: `McpServerConfig` (L61) gains
  `kind: Literal["read", "write"] = "write"` and `tools: list[str] = []`; `load_mcp_servers`
  (L97) must load an existing file without the keys unchanged; `_build_tool` (L215, the
  `kind="write"` literal at L241 becomes the declared kind — never `"exec"`); `McpToolSkip`
  (L249) gets a reason for "not in the server's `tools` list"; `load_mcp_tools` (L267).
  Also rewrite the module docstring sentence at L7 that states every tool is `kind="write"`.
  `src/docket/cli/_mcp.py::_servers_add` (L381): `--kind read|write`, `--tools a,b`; the list
  renderer shows both; a bogus kind exits 1 naming the field.
- **Tests.** `tests/unit/core/test_mcp_tools.py` (core), `tests/integration/test_mcp_servers_cli.py`
  (CLI). Registry narrowing is `core/archetypes.py::registry_for_role` — call it in the test,
  do not edit it.
- **Audit.** The existing load report/audit entry names the declared kind.
- **Do not touch:** `core/archetypes.py`, `core/policy.py`, `edges/adapters/docket_runtime.py`
  (P27-4 wires pod selection next wave), `core/pod.py`.
- **RED:** `tests/unit/core/test_mcp_tools.py` — fake server declared `kind: read`, role with
  `deniedTools: [write, edit, bash]`: `registry_for_role(registry, role)` loses the server's
  tools on the base. Negative case: `kind: write` (or undeclared) still removes them.
- **Goldens:** any `mcp servers list` golden that renders the new columns — regenerate only that
  case and list the lines. Help text change -> regenerate `docs/commands.md`.

## P27-4 — pod settings `mcpServers` and `deniedTools`, each with its live reader

Branch `p27-4-pod-tool-settings`. Wave 42, after P27-1 and P27-3 merge. Specs:
`pod-dispatch.spec.md` -> 6.16.0 (pod settings), `mcp-client.spec.md` -> 1.6.0 (live-turn
wiring, section ~L199), `role-archetypes.spec.md` -> 1.13.0 (per-role tool sets ~L237).

- **Where.** `src/docket/core/pod.py::PodSettings` (L310; `load_for` L440) and its alias
  table; the `pod config` key table in `cli/_pod.py`; `core/archetypes.py::registry_for_role`
  (body only: remove the union of role + pod names, then kind-based removal on the union);
  `edges/adapters/docket_runtime.py::_load_mcp_tools(registry, role)` (L54) and its call
  `self.mcp_loader(registry, meta.role)` (L245) gain the pod.
- **Semantics.** `mcpServers` `None` = all (today); a selected name absent from the catalog
  refuses the dispatch with `DispatchError` naming it; validated against the catalog at write.
  `deniedTools` unknown name refused at write.
- **RED:** `tests/unit/core/test_pod.py` — `PodSettings.load_for` rejects `mcpServers` as an
  unknown key on the base.

## P27-5 — the Lead's instruction is data, and step instructions reach it

Branch `p27-5-lead-instruction`. Wave 42. Specs: `pod-dispatch.spec.md` -> 6.17.0 (hop
message), `pipeline-format.spec.md` -> 2.6.0 (step `instructions`), `pod-blueprints.spec.md`
-> 1.5.0, `role-archetypes.spec.md` -> 1.14.0 (hop instructions ~L276).

- **Where.** `core/dispatch.py` hop-message builder, the `role == "lead"` branch (~L614) and
  the docstring that scopes step `instructions` away from the Lead; `core/archetypes.py`: the
  built-in `lead` literal gains `hopInstruction` with the exact current text, and
  `resolve_hop_instruction` (L252) serves it; `core/blueprints.py`: research/content/ops
  pipeline literals gain a Lead `instructions` line naming their next role.
- **Oracle.** Capture the software pod's Lead message from the base first; it must stay
  byte-identical. `roles show lead` prints the `hopInstruction`.
- **RED:** `tests/unit/core/test_dispatch.py` — research-pod Lead message contains
  "Implementer" on the base.

## P27-6 — `docket pod <p> apply <dir>`

Branch `p27-6-pod-apply`. Wave 43, after Wave 42 merges. Specs: `pod-blueprints.spec.md` ->
1.6.0 (new section "Pod manifests: apply"), `role-archetypes.spec.md` -> 1.15.0 ("Shipped
recipes" ~L319), `cli-interface.spec.md` -> 1.33.0.

- **Where.** New `src/docket/core/pod_apply.py` (`plan_apply`, `apply`, typed `ApplyPlan` /
  `ApplyResult`, pure planning, writes only through existing writers:
  `add_user_archetype(..., project)`, the pod policy directory, member provisioning, the bind
  function behind `pod config set pipeline`, the `PodSettings` setter). `apply` subcommand in
  `cli/_pod.py` with `--dry-run`, `--json`; default dir `<codebase>/.docket/` from the Lead's
  meta. `src/docket/templates/recipes/*`: each gains `pod.yaml` (`members`), README "Apply it"
  becomes the one command. `tests/integration/test_recipes.py` switches to `plan_apply`/`apply`.
- **Audit** once as `pod.apply` with the item list; idempotent second run is all `skip`.
- **Goldens:** `completions_bash`/`completions_zsh` gain the subcommand; regenerate those two
  and `docs/commands.md`, listing the lines.
- **RED:** `from docket.core import pod_apply` fails on the base.

## P27-9 — pod-scoped custom roles resolve in the roster, and `apply` writes pod scope

Branch `p27-9-pod-roster`. Wave 43, serially after P27-6 merged, before P27-7. Specs:
`pod-dispatch.spec.md` -> 6.18.0 (the membership/roster section), `pod-blueprints.spec.md`
-> 1.7.0 ("Pod manifests: apply": remove the global-overlay workaround), `role-archetypes.spec.md`
-> 1.16.0 ("Shipped recipes").

- **Where.** `src/docket/core/pod.py`: `_role_names` (L41), `normalize_role` (L64),
  `members_of` (L122), `parse_member_id` (L152), `resolve_member` (L172). Callers:
  `cli/_pod.py` L123 and L315 (`normalize_role`), `cli/_status.py` L31, `core/dispatch.py`
  L367/384/486/561/2295 (`members_of`, already pass `project`), `edges/adapters/docket_runtime.py`
  L136 and `core/telegram.py` L169 (`parse_member_id`, already pass `project`).
  `src/docket/core/pod_apply.py`: `_plan_roles` (~L143, the `already_global` check) and the
  `add_user_archetype(role_write.doc)` call (~L360) become pod-scoped; fix the module docstring.
- **Do not touch:** `core/dispatch.py` beyond passing `project` where a signature changes (its
  `members_of` calls already do); `cli/_config.py`, `cli/_doctor.py`, `core/archetypes.py`.
- **RED:** `tests/unit/core/test_pod.py` — `vetter` only in pod `acme`'s overlay
  (`pod_config_dir("acme")/roles.json`, wire shape as in `tests/unit/core/test_archetypes.py::
  _write_vetter_overlay`): `parse_member_id("acme-vetter", "acme")` is `None` on the base.
- **Goldens:** none expected.

## P27-7 — `docket pod <p> export <dir>`

Branch `p27-7-pod-export`. Wave 43, serially after P27-6 merges. Specs: `pod-blueprints.spec.md`
-> 1.7.0 ("Pod manifests: export"), `cli-interface.spec.md` -> 1.34.0.

- **Where.** `export_pod(project, dir)` in `core/pod_apply.py` (pod scope only: `roles/*.yaml`
  via `to_wire`, `policies/*.json`, bound `pipeline.yaml`, `pod.yaml` with non-lead `members`
  and non-default `settings`); `export` subcommand in `cli/_pod.py` (`--force` for a non-empty
  dir). Round trip: export p -> fresh `DOCKET_HOME` -> init q -> apply q -> `config explain
  --json` equal after normalising ids and paths.
- **RED:** the round-trip test in `tests/integration/test_recipes.py` (or the file P27-6
  created) fails because `export_pod` does not exist.

## P27-8 — every resolved value says which scope it came from

Branch `p27-8-scope-labels`. Wave 43, parallel with P27-6. Spec `cli-interface.spec.md` ->
1.35.0 (`config explain`, `doctor`).

- **Where.** `cli/_config.py` explain renderer + JSON (`scope` per item: `built-in | global |
  pod` for the role, each policy file, each MCP server with declared kind and pod selection,
  each denied tool); one new check function in `cli/_doctor.py` plus its wiring line
  (`find_overlay_problems(project)` per pod, invalid pod policy files); `docs/CONFIGURATION.md`
  (scope column, pod config dir, §3.10 "apply a recipe in one command", drop "Tool denials are
  per role only" in §5).
- **Oracle.** No pod scope -> explain output byte-identical to the base (capture it).
- **Do not touch:** `core/pod_apply.py`, `cli/_pod.py` (P27-6/P27-7 own them).
- **RED:** `tests/unit/cli/test__config.py` — the JSON has no `scope` key on the base.

## P27-10 — `apply` carries a recipe's policies into the pod

Branch `p27-10-apply-policies`. Wave 43, serially after P27-7 merged. Specs:
`pod-blueprints.spec.md` -> 1.9.0 ("Pod manifests: apply" gains the policy item),
`role-archetypes.spec.md` -> 1.17.0 ("Shipped recipes": the policy is applied, not copied by hand).

- **Where.** `src/docket/core/pod_apply.py`: `plan_apply`, `apply`, the `_plan_*` helpers (add
  `_plan_policies`); the policy validator is `core/policy.py::validate_policy(path) -> str`
  (empty string = valid); the pod policy directory is `config.pod_config_dir(project) / "policies"`
  (what `core/policy.py::policy_files(project)` reads and `_export_policies` copies). Recipe
  READMEs: `src/docket/templates/recipes/secure-build/README.md` (the `cp ... ~/.docket/policies/`
  lines and the undo `rm`), `src/docket/templates/recipes/ops-approval/README.md`.
- **Do not touch:** `core/policy.py`, `cli/_pod.py`, `cli/_policies.py`, `export_pod` and its
  helpers, `core/pod.py`.
- **RED:** `tests/integration/test_recipes.py` — after `apply(plan_apply(p, secure-build))`,
  `pod_config_dir(p)/policies/require-approval-secret-writes.json` does not exist on the base.
- **Goldens:** none.
