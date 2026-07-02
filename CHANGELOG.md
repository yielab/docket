# Changelog

All notable changes to **docket** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> *Section consolidated 2026-07-02: duplicate `Added`/`Changed` headings merged, and the
> Phase 10 (agent pods) + Phase 11 (competitive differentiation, CD-1…CD-8) feature waves —
> previously missing entirely — backfilled. Two stale Bash-era claims corrected in place
> (noted inline).*

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
- **Pod runtime-resource isolation** (CD-1) — each pod gets a **disjoint port range** and a
  private scratch dir, injected into the Implementer's `TOOLS.md`/env
  (`DOCKET_PORT_BASE`, `DOCKET_SCRATCH_DIR`, …), shown by `docket pod <p>`, and reclaimed on
  `docket delete`/`pod remove`.
- **Git-worktree Implementer isolation** for repo pods (CD-5) — the Implementer works in a
  dedicated `git worktree`/branch, torn down with the pod; documented fallback when the daemon
  can't target a worktree.
- **Deterministic pre-merge verification gate** (CD-2) — an opt-in per-pod `verifyCmd` runs in
  the Implementer's workspace before a dispatched task can be marked done; non-zero exit blocks
  completion and emits a redacted `verification_failed` trace event; unset ⇒ visibly logged skip.
- **High-risk action classes** (CD-3) — a `high-risk` policy class (money/payment,
  production-deploy, secret access) that **always** routes to approval even for allowlisted
  binaries; surfaced and testable via `docket policies show` / `policies test`.
- **Headless approval channel** (CD-4) — token-guarded `GET /approvals` + `POST
  /approvals/<token>` on `docket serve` (local-bind by default) alongside `docket approve/deny`;
  fail-closed expiry preserved. Unblocks a future gates-on-by-default decision.
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
  completions bash)"`) completing commands, subcommands, and live agent ids. *(Correction
  2026-07-02: the original entry claimed the command table was drift-guarded by the unit
  suite; that guard belonged to the Bash router and was lost in the Python port — restoring a
  registry-backed guard is tracked as Phase 12 CH-8.)*
- **`scripts/metrics.sh`** — LOC / command / test / spec counters with `--json` and `--check`
  (a CI step fails the build when the README's quoted numbers drift from the tree). *(Correction
  2026-07-02: the script still counts the Bash `lib/` tree deleted at the M6 cutover, so the
  drift guard has been blind since then — the Python-tree rewrite and CI re-arm are tracked as
  Phase 12 CH-9.)*
- **`NOTICE`** — trademark/affiliation statement ("Independent project. Not affiliated with or
  endorsed by OpenClaw or the OpenClaw Foundation"), mirrored at the top of the README.
- **`COMPATIBILITY.md`** — OpenClaw version / schema support matrix, platform requirements, and
  break-reporting policy; linked from the README's Compatibility section.

### Changed

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
  - **User-facing behavior is unchanged.** A 17-case golden suite (`tests/golden/run.sh
    verify-all`) diffs CLI output byte-for-byte against frozen pre-cutover goldens, and every
    prior command and alias still works exactly as before.
  - **Testing/tooling:** the Bash unit/lifecycle tests are replaced by a `pytest`
    suite (`tests/python/` — 416 tests at cutover, 688 as of 2026-07-02), the golden parity
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

[Unreleased]: https://github.com/yielab/docket/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yielab/docket/releases/tag/v0.1.0
