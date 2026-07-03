# Changelog

All notable changes to **docket** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0-beta.1] - 2026-07-03

**Four feature waves land together in this release, none of which had been cut before now:**
Phase 10 (agent pods — provisioning, real dispatch, the opt-in Portfolio Manager), Phase 11
(competitive differentiation, CD-1…CD-8 — runtime-resource isolation, a mechanical verify
gate, governance/HITL, the scheduled/webhook control plane, the versioned read API),
**Phase 12 (Consolidation & hardening)** — the audit-driven pass that closed gaps the other two
left behind: a single enforced JSON-writer chokepoint, ACL-only OpenClaw shell-outs, no UI
printing from `core`/`edges`, retirement of the never-dispatched `docket team` command, a hard
exit on the deprecated tier-name vocabulary, deletion of an unused role-drift engine, a
4,194→1,702-line split of the CLI's largest module, a re-armed CI drift guard, and a spec/docs
truth pass — and **Phase 13 (Close the differentiation gaps)** — a second audit-driven pass
that found Phase 11's CD-1/CD-2/CD-3/CD-4 had already built most of what a fresh competitive
read asked for, and closed the five real residual gaps instead of rebuilding: pod resources now
reach the Implementer's actual process environment (not just TOOLS.md prose), `verifyCmd` is
settable via a public flag, the Tester hop is structurally gated on PASS/FAIL, a built-in
high-risk action-class policy always routes money-movement/secret-access actions to approval,
every approval (any channel) is now audit-logged, and exec-approval gates are **on by default**
for new installs. Full detail: `ROADMAP.md` (Phase 10/11/12/13 sections),
`internal-docs/architecture-audit.md`, and TODO.md's CH-0…CH-13 / FD-0…FD-7 cards.

> *Section consolidated 2026-07-02, extended 2026-07-03: duplicate `Added`/`Changed` headings
> merged, and the Phase 10 (agent pods) + Phase 11 (competitive differentiation, CD-1…CD-8)
> feature waves — previously missing entirely — backfilled. Two stale Bash-era claims corrected
> in place (noted inline). Phase 13 (FD-0…FD-7) folded in on 2026-07-03, the day this version
> was actually tagged.*

### Added

- **Agent pods (Phase 10).** `docket add <project>` now provisions an **isolated pod** of
  project-scoped agents — Lead + Implementer by default; `--pod full` or `--with
  reviewer,tester` for the rest — each member with its own workspace and `.docket-meta.json`.
  `docket pod <project>` manages members (`add <role> [--count N]` / `remove <member-id>` /
  listing). **programmer/reviewer/tester are no longer global shared specialists** — they are
  per-pod roles; `scope` (org vs project) is a first-class metadata axis, and `docket doctor`
  flags leftover pre-pod global role workspaces and backfills `scope` on legacy metadata.
- **Real pod dispatch.** `docket pod <project> delegate "<task>"` / `queue` / `dispatch` run a
  per-pod task queue (one queue per Lead — never shared across pods) through a hop pipeline
  (Implementer, then optional Reviewer/Tester) with per-hop cost recorded; `docket serve
  --dispatch` runs it as a background loop.
- **Org Portfolio Manager (opt-in).** `docket install --portfolio` provisions a single
  `scope: org` planning/visibility agent over fleet metadata (never project code).
- **Pod runtime-resource isolation** (CD-1, completed by Phase 13's FD-0) — each pod gets a
  **disjoint port range** and a private scratch dir, injected into the Implementer's **real
  dispatch subprocess environment** (`DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`,
  `DOCKET_SCRATCH_DIR`) — not just documented as TOOLS.md prose the agent has to read and
  remember to follow — shown by `docket pod <p>`, and reclaimed on `docket delete`/`pod remove`.
- **Git-worktree Implementer isolation** for repo pods (CD-5) — the Implementer works in a
  dedicated `git worktree`/branch, torn down with the pod; documented fallback when the daemon
  can't target a worktree.
- **Deterministic pre-merge verification gate** (CD-2, completed by Phase 13's FD-1/FD-2) — an
  opt-in per-pod `verifyCmd` — now settable via a public `docket pod <project> add --verify
  "<cmd>"` / `set-verify <member-id> "<cmd>"` (previously only an internal debug command could
  set it) — runs in the Implementer's workspace before a dispatched task can be marked done;
  non-zero exit blocks completion and emits a redacted `verification_failed` trace event; unset
  ⇒ visibly logged skip. If the pod has a Tester, its hop is now **also** gated: the first
  non-blank line of its report must read `PASS`/`FAIL` (case-insensitive); `FAIL` or unparseable
  output blocks the pipeline (`tester_verdict_failed`) instead of the Tester's word being taken
  on faith.
- **Policy template presets** (CD-3) — `templates/policies/*.json` ships curated,
  human-reviewable policy presets (`block-destructive`, `high-risk-payment`,
  `high-risk-deploy`, `high-risk-credentials`, `prompt-injection`, `secret-pii-redact`) an
  operator can inspect/apply via `docket policies show` / `policies test`.
- **Built-in high-risk action-class policy** (Phase 13's FD-3 — distinct from the CD-3 policy
  *templates* above) — `core/security.py`'s `HIGH_RISK_PATTERNS` (money-movement, prod-deploy,
  secret-access) is wired directly into what `docket gates enable` seeds, visible read-only via
  `docket gates classes`. Money-movement and secret-access are **fully enforced today** (their
  bins were never on the curated allowlist to begin with). Prod-deploy's overlap with `git`/`npm`
  is **documented policy, not daemon-enforced** — the OpenClaw exec-allowlist gates by binary
  path only, so excluding those two constantly-used bins wholesale to force enforcement would
  also block benign use (`git status`, `npm test`); per-argument enforcement is a tracked
  backlog item, not shipped behavior.
- **Headless approval channel** (CD-4, completed by Phase 13's FD-4/FD-5) — token-guarded `GET
  /approvals` + `POST /approvals/<token>` on `docket serve` (local-bind by default) alongside
  `docket approve/deny`; fail-closed expiry preserved. Every grant/deny, on **any** channel
  (CLI, HTTP, Telegram), now writes an `audit_log()` entry tagged with the channel — previously
  only a trace event was recorded. This closed condition is what unblocked **gates-on-by-default
  for new installs** (`docket install`, `--no-gates` to opt out) — see Changed, below.
- **Scheduled & webhook-triggered dispatch** (CD-6) — cron-like schedules and a token-guarded
  `POST /dispatch/<project>` endpoint turn the `serve --dispatch` poller into an event-driven
  control plane.
- **Versioned read-only API** (CD-8) — `/status.json`, `/metrics` (Prometheus text format),
  `/health` documented and contract-pinned in `specs/data/serve-read-api.spec.md`, so external
  dashboards can consume docket state; mutation stays in the CLI.
- **Lobster workflow `validate` + `plan`** (CD-7) — schema/lint a workflow and render the
  resolved pipeline docket would hand the daemon, explicitly without executing it.
- **`docket eval [--live] [--tier <t>] [--role <r>] [--recommend]`** — real specialist-role
  eval harness. Each of the six roles has a structural mode (fast SOUL.md contract check) and a
  live mode (`DOCKET_EVAL_LIVE=1`) that sends a golden task via `openclaw agent --local --json`
  and checks the response against acceptance criteria. Results are stored in
  `tests/evals/results/YYYY-MM-DD.jsonl`; `docket eval --recommend` and `docket doctor`
  surface per-role suggestions. Infrastructure failures (quota, auth, timeout) are SKIP —
  evals stay non-blocking in CI.
- **`docket cost --history [id] [--days N] [--json]`** — daily per-agent cost/turn/token
  series bucketed by session timestamp, cached in `.cost-history.json`, with a regression flag
  for any day costing more than 2× its trailing 3-day average.
- **Template/prompt versioning** — `_create_workspace` stamps `TEMPLATE_VERSION` into each
  agent's `.docket-meta.json`; `docket doctor` flags agents on stale templates and points at
  `docket maintain <id> rebuild`.
- **Declarative provisioning** — `docket add --from <agents.yaml|agents.json>` provisions a
  whole fleet from a spec file; idempotent, so a fleet file can be re-applied and kept in git.
  Example specs in `examples/configs/`.
- **`docket completions <bash|zsh>`** — emits a shell completion script (`eval "$(docket
  completions bash)"`) completing commands, subcommands, and live agent ids. Generated at
  runtime from the live Typer command registry (Phase 12 CH-8), so it cannot silently desync
  from the router the way the original hand-maintained literals did.
- **`scripts/metrics.py`** — LOC / command / test / spec counters with `--json` and `--check`
  (a CI step fails the build when the README's quoted numbers drift from the tree). Replaces
  the original `scripts/metrics.sh`, which counted the Bash `lib/` tree deleted at the M6
  cutover and had been silently blind ever since (Phase 12 CH-9).
- **`NOTICE`** — trademark/affiliation statement ("Independent project. Not affiliated with or
  endorsed by OpenClaw or the OpenClaw Foundation"), mirrored at the top of the README.
- **`COMPATIBILITY.md`** — OpenClaw version / schema support matrix, platform requirements, and
  break-reporting policy; linked from the README's Compatibility section.

### Changed

- **Exec-approval gates are now on by default for new installs** (Phase 13, FD-5) — `docket
  install` applies conservative exec-approval defaults + a curated allowlist automatically;
  `--no-gates` is the explicit opt-out (previously `--gates` was required to opt in). The
  security-gates spec's own blocking condition — a headless (non-Telegram) approval channel —
  was already met by CD-4's CLI/HTTP channels; this flip and the FD-4 audit-log parity above are
  what closed the remaining gap honestly before flipping the default. Docker workspace isolation
  (`docket gates isolate on`) remains a separate, still-opt-in layer.
- **Bash → Python rewrite (M6 cutover).** docket is now a Python package (`src/docket/`)
  built on Typer + Rich + Pydantic (plus pydantic-settings and filelock), installed via
  `uv`/pip. `bin/docket` is now a thin Bash launcher that execs `python -m docket "$@"`; all
  command logic moved to Python and the entire Bash `lib/` (commands, helpers, core) was
  removed. The code is organized in three layers — `cli/` (Typer commands) → `core/` (Pydantic
  models + pure services) → `edges/` (atomic JSON store + adapters) — with
  `edges/adapters/openclaw.py` as an **Anti-Corruption Layer**: the single module allowed to
  know the `openclaw.json` / auth-profiles / provider-config formats. Templates moved from
  `lib/templates/` to `src/docket/templates/` and ship in the wheel. Command aliases and
  removed-command notices live in `src/docket/__main__.py`.
  - **User-facing behavior is unchanged.** A golden suite (`tests/golden/run.sh verify-all`,
    17 cases at the M6 cutover, 16 as of this release — Phase 12 CH-4 retired one command)
    diffs CLI output byte-for-byte against frozen goldens, and every surviving command and
    alias still works exactly as before.
  - **Testing/tooling:** the Bash unit/lifecycle tests are replaced by a `pytest`
    suite (`tests/python/` — 416 tests at cutover, 739 as of this release), the golden parity
    suite, and the eval harness. New quality gates
    `ruff check` + `ruff format --check` + `mypy --strict` run in CI. CI jobs are now
    `python`, `golden`, `shell`, and `macos`.
  - The remaining shell surface is just the launcher, `install.sh`/`uninstall.sh`,
    `scripts/*.sh`, and the golden/eval harnesses (all ShellCheck-linted).

- **README repositioned around the ops layer** — leads with the one-line positioning
  ("cost-aware ops layer for OpenClaw agent fleets"), a pain-first *Why*, a 60-second tour,
  and a *How it relates to OpenClaw* differentiation table, with the command reference demoted
  below the fold. Replaces the prior feature-firehose ordering. The "actively used in real
  environments" line is replaced with an honest authorship note.

- `sync_session_key` now warns and skips (instead of aborting) when `openclaw.json` is absent,
  so one missing config can't halt a multi-agent provision.
- **CI lint gate raised** from `-S error` to `-S warning` (with curated excludes for
  cross-file shared vars and dynamic `source`), and the `SC2155`/`SC2188`/`SC2164`/`SC2076`/
  `SC2010`/`SC2011`/`SC2046`/`SC2115`/`SC2050` warning backlog cleared so the gate stays green.
- **Test harness hardened** — counter increments use `n=$((n + 1))` instead of `((n++))`
  (which returns non-zero at 0 and would abort a `set -e` harness); direct unit tests added
  for the `load_model_registry` overlay. *(Bash-era entry; the harness is now pytest.)*
- **`docket doctor --json` is now a usable health probe** — exits non-zero when the report is
  unhealthy (previously always exited 0), so it can gate monitoring/CI. JSON payload unchanged
  (`healthy`/`issues` were already present).
- **docket-owned JSON now has a single writer** (Phase 12 CH-1) — every write goes through
  `edges/store.py`'s atomic + filelocked + 0600 chokepoint (append-only JSONL logs in
  `core/trace.py`/`core/audit.py` are the sole, documented exemption). Closes 8+ places that
  had hand-rolled their own atomic-write logic, several without the filelock or `.bak`
  rotation the chokepoint provides.
- **`openclaw` binary shell-outs now go through the Anti-Corruption Layer** (Phase 12 CH-2) —
  `edges/adapters/openclaw.py` gained typed wrappers (`openclaw_version`, `agents_add`,
  `auth_setup_token`, `auth_paste_token`, `onboard`); `core/utils.py` no longer imports
  `subprocess` at all.
- **`core/` and `edges/` no longer print** (Phase 12 CH-3) — `core/provider.py` and
  `system.restart_gateway()` return typed results (`ProviderRegistration`, `RestartResult`);
  the `cli/` layer renders them. A new `cli/_provider.py` hosts the interactive provider flow
  that used to live in `core/`.
- **`cli/__init__.py` split from 4,194 to 1,702 lines** (Phase 12 CH-7) — `keys`/`auth` moved
  to `cli/_keys.py`, `context` to `cli/_context.py`, `workflow` to `cli/_workflow.py`, `cost`
  to `cli/_cost.py`, and agent add/info/delete/maintain to `cli/_agents.py`. No behavior
  change; goldens stayed byte-identical through every extraction stage.

### Removed

- **`docket team`** (Phase 12 CH-4, D-11) — the org-wide manual task queue never had a
  dispatcher; nothing ever executed a queued task. Running any `docket team <subcommand>` now
  prints a removed-command notice mapping to the real, executing replacement: `docket pod
  <project> delegate/queue/dispatch`. Any pre-existing
  `~/.openclaw/workspaces/manager/TASK_LIST.json` is left on disk, untouched but no longer
  read. The opt-in Portfolio Manager (`docket install --portfolio`) covers the cross-pod view
  `team` used to gesture at.
- **Tier names as model input** (Phase 12 CH-6, D-2 exit) — `economy`/`standard`/`premium` are
  no longer accepted anywhere a model or role value is expected; `docket profile <id> premium`
  and `docket models set premium <model>` now fail with an error naming a full
  `provider/model` id. A legacy `profiles:` key in `~/.openclaw/docket-models.json`
  auto-migrates to `roles:` once on load (`docket doctor` flags a residual `profiles:` key if
  `roles:` was already present and the migration left it alone).
- **`core/drift.py`** (Phase 12 CH-5) — the role-success-rate drift engine had exactly one
  caller (the opt-in `serve --dispatch` sweep) and fed a Telegram notification that was never
  implemented. Deleted along with its 3 dedicated config knobs. Unrelated to, and does not
  affect, `docket doctor`'s config-drift check (meta ↔ `openclaw.json`) or template-version
  staleness detection, both of which are unchanged.

### Security docs

- **`SECURITY.md` expanded** — explicit threat model (what runs with what privileges), the
  approval-gate model, a homelab-vs-public-VPS guidance box, secret-storage backends as
  first-class safety features, a "what docket does NOT protect against" list, and a 90-day
  responsible-disclosure timeline.

### Fixed

- **`docket --version` after install** — the installer never copied `VERSION` to the
  install prefix, so installed users got `docket (version unknown)`. `VERSION` is now
  shipped beside `lib/` and the launcher checks `$LIB_DIR/VERSION` in the installed layout.
- **Brittle installer source-patching** — `install.sh` no longer rewrites the `LIB_DIR=`
  line with `sed` (which broke silently on any whitespace change). `bin/docket` now
  auto-detects the installed (`<prefix>/lib/docket-cli`) vs repo (`<repo>/lib`) layout at
  runtime, and honors a `DOCKET_LIB_DIR` override for packagers/tests.
- **`uninstall.sh` left files behind** — it removed `lib/docket` while `install.sh` installed
  to `lib/docket-cli`. Paths now match; legacy `lib/docket` is also cleaned up, and `DOCKET_PREFIX`
  is honored to mirror the installer.
- **`docket team upgrade` in installed layout** — read templates from `$DOCKET_CLI_ROOT/lib/templates`,
  which doesn't exist once installed; now uses `$LIB_DIR/templates`.
- **README-numbers CI drift guard re-armed** (Phase 12 CH-9) — `scripts/spec-coverage.sh` and
  the original `scripts/metrics.sh` both counted the deleted Bash `lib/` tree and had been
  silently broken since the M6 cutover, masked by a `|| true` on the CI step. The new
  `scripts/metrics.py --check` counts the real Python tree and Typer registry and now actually
  fails CI on drift; `spec-coverage.sh` was deleted outright rather than rewritten, since a
  faithful rewrite would immediately red-flag documentation gaps that a later fix (CH-11)
  closed separately.
- **Documentation and specification drift** (Phase 12 CH-0, CH-10, CH-11) — a full-repo audit
  found and fixed a batch of stale claims accumulated across Phases 10–11: `docs/commands.md`
  was missing sections for 8 real commands (`keys`, `auth`, `gates`, `audit`, `eval`,
  `snapshot`, `completions`, `context`); its alias table had drifted from `__main__.py`'s real
  `_ALIASES`/`_REMOVED` dicts; `docket doctor` was described as read-only despite having
  `--fix`; `specs/functional/workflow-integration.spec.md` documented a `.yaml` extension that
  was never real (the actual extension is `.lobster.yml`) and invented return codes the
  command never used; several docs (`AGENT-TEAMS.md`, `WORKFLOW-GUIDE.md`, `DOCKET.md`) still
  described the retired `docket team` as live; `QUICK-START-DOCKET.md` and `DOCKET.md` had the
  `docket context` argument order backwards. All corrected; see `internal-docs/architecture-audit.md`
  for the full findings this phase worked from.
- **Spec/data truth pass for Phase 13's changes** (FD-6) — `specs/data/docket-meta.spec.md` and
  `specs/api/cli-interface.spec.md` updated for the `--verify`/`set-verify` surface and
  env-injection behavior; a new `specs/functional/pod-dispatch.spec.md` documents the dispatch
  pipeline's hop order, gates, and failure semantics — no spec previously owned that contract;
  `specs/functional/security-gates.spec.md` brought current for the real approval-channel set,
  the high-risk action-class policy's honest (partial) enforcement scope, and the
  gates-on-by-default status.

## [0.1.0] - 2026-06-10

First tagged release. Establishes the security and write-safety baseline
("a tool I'd run on a real machine") on top of the existing agent-lifecycle CLI.

### Added

- **`docket gates`** command (`status` / `enable` / `disable` / `isolate`) — opt-in
  exec-approval enforcement on the OpenClaw daemon's native primitives: conservative
  defaults (`security: allowlist`, `ask: on-miss`, `askFallback: deny`) with a curated
  safe-bin allowlist, plus `docket install --gates`.
- **Approval routing** — `docket gates enable` writes `approvals.exec` (`mode: session`) so an
  agent's gated prompts reach its own channel, answerable via `/approve`.
- **Workspace isolation** — `docket gates isolate on` applies the daemon's Docker sandbox
  (`agents.defaults.sandbox`), Docker-gated and reversible.
- **Secret storage backends** — pluggable `file` (default, 0600 JSON) or `keyring`
  (`DOCKET_SECRETS_BACKEND=keyring`, libsecret); keyring keeps no plaintext values at rest.
- **`docket keys rotate`** and key-age hygiene (0600 `secrets.meta.json` sidecar); `docket doctor`
  flags keys past the rotation threshold (`DOCKET_KEY_MAX_AGE_DAYS`, default 90d).
- **`docket doctor`** security section — exec-approval policy, approval routing, isolation,
  config-permission hardening, the `openclaw security audit` summary, and the active secret backend.
- **`docket --version`** / `-V`, a `VERSION` file, and this changelog.
- Write-safety primitives `json_atomic_write` and `with_docket_lock` (`flock`).

### Changed

- **Scoped secret distribution** — `docket keys` syncs only the provider key an agent's model
  needs (not every key to every agent); custom/shared secrets still fan out. Atomic `.env`
  writes that preserve user-authored lines.
- All JSON writers (`meta_set`, `upsert_binding`, `remove_binding`, `remove_agent_config`,
  `oc_set`) now write atomically (validate → `.bak` → tmp → `os.replace` → 0600) under an
  exclusive `flock`, so a crash or concurrent invocation can't corrupt or lose state.
- `meta_get` / `oc_get` warn loudly when a state file exists but won't parse, instead of
  silently returning the default.
- `docket install` Step 6 hardens `openclaw.json` / `secrets.json` permissions to `600`.

### Fixed

- **Code injection in `keys.sh`** — secret values are never interpolated into Python source
  (passed via env/argv/stdin); regression-tested with a hostile value.
- `docket doctor` aborted before later checks under `set -e`/pipefail when no sandbox browser
  process was running; all sections now run to completion.
- Cleared one `shellcheck` error (SC2199, array membership test in `maintain`).

### Security

- Phase 0 (security hardening) and Phase 1 (write-safety) of the [ROADMAP](ROADMAP.md) are
  complete. Exec-approval enforcement and Docker isolation ship **opt-in** by design; on-by-default
  is deferred pending per-agent headless approval routing (see `specs/functional/security-gates.spec.md`).

[Unreleased]: https://github.com/yielab/docket/compare/v0.2.0-beta.1...HEAD
[0.2.0-beta.1]: https://github.com/yielab/docket/compare/v0.1.0...v0.2.0-beta.1
[0.1.0]: https://github.com/yielab/docket/releases/tag/v0.1.0
