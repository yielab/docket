# Changelog

All notable changes to **rack** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **README repositioned around the ops layer** — leads with the one-line positioning
  ("cost-aware ops layer for OpenClaw agent fleets"), a pain-first *Why*, a 60-second tour,
  and a *How it relates to OpenClaw* differentiation table, with the command reference demoted
  below the fold. Replaces the prior feature-firehose ordering. The "actively used in real
  environments" line is replaced with an honest authorship note.

### Added

- **`scripts/metrics.sh`** — single source of truth for LOC / command / helper / unit-test /
  spec counts (`--json`, `--check`). A new CI step (`metrics --check`) fails the build if the
  README's quoted numbers drift from the tree. Reconciles prior contradictions (README claimed
  241 tests / ~7,200 LOC / 21 commands; actual: 247 / ~8,700 / 25).
- **`NOTICE`** — trademark/affiliation statement ("Independent project. Not affiliated with or
  endorsed by OpenClaw or the OpenClaw Foundation"), mirrored at the top of the README.
- **`COMPATIBILITY.md`** — OpenClaw version / schema support matrix, platform requirements, and
  break-reporting policy; linked from the README's new Compatibility section.

### Security docs

- **`SECURITY.md` expanded** — explicit threat model (what runs with what privileges), the
  approval-gate model, a homelab-vs-public-VPS guidance box, secret-storage backends as
  first-class safety features, a "what rack does NOT protect against" list, and a 90-day
  responsible-disclosure timeline.

### Fixed

- **`rack --version` after install** — the installer never copied `VERSION` to the
  install prefix, so installed users got `rack (version unknown)`. `VERSION` is now
  shipped beside `lib/` and the launcher checks `$LIB_DIR/VERSION` in the installed layout.
- **Brittle installer source-patching** — `install.sh` no longer rewrites the `LIB_DIR=`
  line with `sed` (which broke silently on any whitespace change). `bin/rack` now
  auto-detects the installed (`<prefix>/lib/rack-cli`) vs repo (`<repo>/lib`) layout at
  runtime, and honors a `RACK_LIB_DIR` override for packagers/tests.
- **`uninstall.sh` left files behind** — it removed `lib/rack` while `install.sh` installed
  to `lib/rack-cli`. Paths now match; legacy `lib/rack` is also cleaned up, and `RACK_PREFIX`
  is honored to mirror the installer.
- **`rack team upgrade` in installed layout** — read templates from `$RACK_CLI_ROOT/lib/templates`,
  which doesn't exist once installed; now uses `$LIB_DIR/templates`.

### Added

- **`rack eval [--live] [--tier <t>] [--role <r>] [--recommend]`** — real specialist-role
  eval harness. Each of the six roles (programmer, reviewer, tester, knowledge, security,
  manager) has a structural mode (fast SOUL.md contract check) and a live mode
  (`RACK_EVAL_LIVE=1`) that sends a golden task via `openclaw agent --local --json` and
  checks the response against acceptance criteria. Results (pass/fail, cost, tokens) are
  stored in `tests/evals/results/YYYY-MM-DD.jsonl`; `rack eval --recommend` and
  `rack doctor` (section 16) surface per-role tier suggestions from stored results.
  Infrastructure failures (quota, auth, timeout) are SKIP — evals stay non-blocking in CI.
- **`rack cost --history [id] [--days N] [--json]`** — daily per-agent cost/turn/token
  series bucketed by session timestamp, cached in `.cost-history.json` by the same
  (mtime, size) signatures as the cost index, with a regression flag for any day costing
  more than 2× its trailing 3-day average.
- **Template/prompt versioning** — `_create_workspace` stamps the current `TEMPLATE_VERSION`
  into each agent's `.rack-meta.json` (on `rack add` and `rack maintain rebuild`); `rack doctor`
  flags agents whose stamp is older than (or absent versus) the current template and points at
  `rack maintain <id> rebuild`.
- **Declarative provisioning** — `rack add --from <agents.yaml|agents.json>` provisions a whole
  fleet from a spec file (JSON always; YAML when PyYAML is installed). Supports a single agent
  mapping, a list, or `{agents: [...]}`; only `name` is required. Idempotent (existing agents
  skipped) so a fleet file can be re-applied and kept in git. Example specs in `examples/configs/`.

### Changed

- `sync_session_key` now warns and skips (instead of aborting) when `openclaw.json` is absent,
  so one missing config can't halt a multi-agent provision.
- **CI lint gate raised** from `-S error` to `-S warning` (with curated excludes for
  cross-file shared vars and dynamic `source`), and the `SC2155`/`SC2188`/`SC2164`/`SC2076`/
  `SC2010`/`SC2011`/`SC2046`/`SC2115`/`SC2050` warning backlog cleared so the gate stays green.
- **Test harness hardened** — counter increments use `n=$((n + 1))` instead of `((n++))`
  (which returns non-zero at 0 and would abort a `set -e` harness). Added 6 direct unit
  tests of the `load_model_registry` overlay (corrupt-file fallback, role/default/anchor
  overrides, unknown-role rejection); unit suite is now 247 assertions.

## [0.1.0] - 2026-06-10

First tagged release. Establishes the security and write-safety baseline
("a tool I'd run on a real machine") on top of the existing agent-lifecycle CLI.

### Added

- **`rack gates`** command (`status` / `enable` / `disable` / `isolate`) — opt-in
  exec-approval enforcement on the OpenClaw daemon's native primitives: conservative
  defaults (`security: allowlist`, `ask: on-miss`, `askFallback: deny`) with a curated
  safe-bin allowlist, plus `rack install --gates`.
- **Approval routing** — `rack gates enable` writes `approvals.exec` (`mode: session`) so an
  agent's gated prompts reach its own channel, answerable via `/approve`.
- **Workspace isolation** — `rack gates isolate on` applies the daemon's Docker sandbox
  (`agents.defaults.sandbox`), Docker-gated and reversible.
- **Secret storage backends** — pluggable `file` (default, 0600 JSON) or `keyring`
  (`RACK_SECRETS_BACKEND=keyring`, libsecret); keyring keeps no plaintext values at rest.
- **`rack keys rotate`** and key-age hygiene (0600 `secrets.meta.json` sidecar); `rack doctor`
  flags keys past the rotation threshold (`RACK_KEY_MAX_AGE_DAYS`, default 90d).
- **`rack doctor`** security section — exec-approval policy, approval routing, isolation,
  config-permission hardening, the `openclaw security audit` summary, and the active secret backend.
- **`rack --version`** / `-V`, a `VERSION` file, and this changelog.
- Write-safety primitives `json_atomic_write` and `with_rack_lock` (`flock`).

### Changed

- **Scoped secret distribution** — `rack keys` syncs only the provider key an agent's model
  needs (not every key to every agent); custom/shared secrets still fan out. Atomic `.env`
  writes that preserve user-authored lines.
- All JSON writers (`meta_set`, `upsert_binding`, `remove_binding`, `remove_agent_config`,
  `oc_set`) now write atomically (validate → `.bak` → tmp → `os.replace` → 0600) under an
  exclusive `flock`, so a crash or concurrent invocation can't corrupt or lose state.
- `meta_get` / `oc_get` warn loudly when a state file exists but won't parse, instead of
  silently returning the default.
- `rack install` Step 6 hardens `openclaw.json` / `secrets.json` permissions to `600`.

### Fixed

- **Code injection in `keys.sh`** — secret values are never interpolated into Python source
  (passed via env/argv/stdin); regression-tested with a hostile value.
- `rack doctor` aborted before later checks under `set -e`/pipefail when no sandbox browser
  process was running; all sections now run to completion.
- Cleared one `shellcheck` error (SC2199, array membership test in `maintain`).

### Security

- Phase 0 (security hardening) and Phase 1 (write-safety) of the [ROADMAP](ROADMAP.md) are
  complete. Exec-approval enforcement and Docker isolation ship **opt-in** by design; on-by-default
  is deferred pending per-agent headless approval routing (see `specs/functional/security-gates.spec.md`).

[Unreleased]: https://github.com/santiagoyie/rack-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/santiagoyie/rack-cli/releases/tag/v0.1.0
