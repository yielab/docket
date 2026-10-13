# Wave 100 worker packets — Phase 40, the D-59 flow (P40-5, P40-13)

Coordinator: the session that closed Waves 98–99 on 2026-10-12. **Base commit: the commit that
opens Wave 100 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-100-worker-packets.md`).
Two cards, **sequential**: P40-13 builds on P40-5's merge (it uses the review store and the
digest compare), so P40-13 starts from the commit that merges P40-5. The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P40-<N>`) is the contract; this
file is the map. Symbols drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bump | Shared-file note |
| --- | --- | --- | --- |
| P40-5 | Sonnet | `pod-blueprints.spec.md` minor, `security-gates.spec.md` 0.42.0 | adds `InitRequest.accept`; `cli/_pod_config.py` rendering |
| P40-13 | Sonnet | `cli-interface.spec.md` minor (rename + `run`), `pod-blueprints.spec.md` patch | regenerates `docs/commands.md`; recaptures goldens that print `pod --help`/`status` |

## 0. Rules for every worker

**Exactly §0 of [wave-98-worker-packets.md](wave-98-worker-packets.md)**, with `w100` in place of
`w98` in the worktree and branch names and the base commit above. Read that section and your own
packet only. One addition: the console copy below is the acceptance text; match its wording and
layout (two groups, the exact command per run item, the three ways on).

## P40-5 — a repository's commands need the operator's OK (Sonnet)

- Decision locators: `docs/adr/0024-one-execution-envelope.md` §6; ROADMAP §6 row D-59.
- Live path today: `cli/_agents.py::_apply_repo_config` (plan, render, apply at once),
  `run_init`, `InitRequest` (same module or `cli/_init.py`; `rg -n "class InitRequest"`),
  `core/pod_apply.py::plan_apply`/`apply`/`summarize_recipe`/`config_digest` (the digest helper
  `apply` records as `configDigest`), `cli/_pod_config.py::render_apply_plan`/`_render_items`,
  `core/pod.py::_parse_allow_commands` (refuses opaque names today; the shell list is new and
  applies only to a plan that came from a repository, so the check lives in the plan
  classification, not the validator).
- New: `core/reviewed_repos.py` — `review_code(items) -> str` (sha256 over the canonical items,
  first 6 hex shown), `lookup(repo_root) -> ReviewedRepo | None`, `remember(repo_root, code,
  items)`; file `config.py::REVIEWED_REPOS_FILE = DOCKET_HOME / "reviewed-repos.json"`, written
  through `edges/store` (0600). Audit `repo.allow` with `repo=<root> code=<code> items=<n>`.
- Classification (`core/pod_apply.py::classify_plan(plan) -> PlanReview` with `adds` and
  `runs`): a run item is `{kind, name, runs}` where `kind` in `pipeline-step` (a `run:` step's
  command), `verify` (a member's verify command), `mcp-server` (command + args), `plugin`
  (file name + sha256), `allow-commands` (the list), `network` (`open`), `role-loosens`
  (role + the denial removed). Everything else is an add.
- Console copy (TTY), after the plan header the CLI already prints:
  ```
  Adds to the team
    role     api-reviewer
    policy   no-secrets
  Runs on this machine
    1. pipeline step "migrate"     sh scripts/migrate.sh --env dev
    2. MCP server "db-inspector"   npx -y @acme/db-mcp@1.4.2
  They run with your user's permissions.
  Allow them? You will only be asked again if they change. [y/N]
  ```
  No TTY: `x Not set up. The repository brings 2 commands that need your OK, and there is no
  terminal to ask on. Nothing was created.` + the numbered items + `To continue, either: run
  docket init once on a terminal on this machine, or allow exactly these from the script:
  docket init --accept 8c41e2`. Wrong `--accept`: `x Not set up. The repository changed what runs
  on this machine since review code <old>:` + before/now per changed item + `Review the new
  version with: docket pod update --dry-run` (P40-13 adds `update`; until then say `docket init
  --no-apply` then `docket pod apply --dry-run`). Shell: `x Not set up. The repository lets the
  agent run bash. A shell runs whatever command follows it, so docket's command checks never see
  what it actually does.` + `Ask the repository to list the tools the team uses instead, like:
  make, npm`.
- Tests: `tests/unit/core/test_pod_apply.py` (classification, review code stability and
  ordering independence), `tests/unit/core/test_reviewed_repos.py` (new), `tests/unit/cli/
  test__agents.py` (the init flows with CliRunner `input="y\n"` and no input; `--accept`;
  `--json`), fixture repos built in `tmp_path`. Keep `tests/integration/test_install.py` green.
- Spec: `pod-blueprints.spec.md` "Pod manifests: apply" (the review requirement, the store, the
  exemption for shipped recipes); `security-gates.spec.md` 0.42.0 Tool-approval gates item 1
  (a repository can never allowlist a shell).

## P40-13 — `docket run` picks changes up; `pod apply` -> `pod update` (Sonnet)

- Starts from the commit that merges P40-5. Decision locators as above.
- Live path: `cli/_run.py::cmd_run` (before it calls dispatch; `rg -n "def cmd_run"`),
  `cli/_pod_config.py::cmd_apply` -> `cmd_update` (same options; routes through P40-5's review
  on a TTY, `--accept` off one), `cli/__init__.py` (`pod_app.command("apply")` -> `"update"`),
  `cli/_status.py::_pod_status` + the human renderer (two lines per pod when a review exists),
  `core/pod_apply.py` (a `repo_changes(project, repo_dir) -> RepoChanges` with `adds_changed`,
  `runs_changed` (before/now pairs), built from `classify_plan` + the stored review).
- `docket start`, `dispatch_pod`, `docket exec` never call it (pin with an AST or call-site test
  like `tests/guards/test_no_suppressed_dispatch.py`'s shape).
- Console copy: `-> Updated from the repository: skill style-guide.`; TTY ask: `The repository
  changed a command since you allowed it on <date>:` + before/now + `Allow the new version?
  [y/N]`, on `n`: `-> Running with the version you allowed on <date>.`; no TTY: `! The repository
  changed a command that needs your OK. Running with the version you allowed on <date>. To
  review it, run docket run on a terminal.`; status: `Commands   2 allowed on 2026-10-12 (code
  8c41e2)` and `           1 changed in the repository, waiting for your OK: docket run asks`.
- Rename: no alias (D-57); `docs/commands.md` regenerated with `scripts/gen_cli_docs.py`;
  `scripts/maint/lint_cli_invocations.py --self-check`; every prose mention of `pod apply` in
  `README.md`, `docs/*.md`, `specs/` is reported to the integrator with file:line (the README is
  the integrator's; specs you own you fix).
- Tests: `tests/unit/cli/test__run.py` (monkeypatched dispatch; a changed skill, a changed run
  step on/off TTY), `tests/unit/cli/test__pod_config.py` (rename), `tests/unit/cli/test__status.py`
  (the two lines), goldens recaptured with each changed line explained in the return.
