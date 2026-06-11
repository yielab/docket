# Changelog

All notable changes to **rack** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
