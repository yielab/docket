# Compatibility

docket wraps the [OpenClaw](https://openclaw.dev) daemon, which renames and reshapes its config
periodically. This document records what docket is known to work with and how breaks are handled.

## Support matrix

| docket-cli | Tested OpenClaw | `openclaw.json` schema | Notes |
|----------|-----------------|------------------------|-------|
| 0.1.x    | current release line (developed against the 2026.x line) | v1 | Manual verification only; no automated version pin yet |

docket reads the live OpenClaw version (`openclaw --version`) for display but does not currently
enforce a minimum. It writes the v1 `openclaw.json` schema (preserving unknown keys on every
atomic write, so forward-compatible fields survive a round-trip).

## Platform

- **Python 3.11+** — required; the primary runtime for all docket logic.
- **Linux** — primary, CI-gated.
- **macOS** — supported on a best-effort basis; the macOS CI job is currently informational
  (`continue-on-error`) and slated to become a required gate.
- **Bash 4.0+** — required only for the `bin/docket` launcher shim (three lines that locate
  a Python interpreter and exec `python -m docket "$@"`). Not required if you invoke
  `python -m docket` directly. macOS ships Bash 3.2; install via Homebrew if you use the shim.
- **systemd** — used for gateway service management on Linux; non-systemd hosts degrade
  gracefully (restart steps are skipped with a warning).

## Policy

- **Schema changes** in OpenClaw are absorbed where possible via the unknown-key-preserving
  atomic writer. A genuinely breaking schema change will be pinned in the matrix above and
  called out in [CHANGELOG.md](CHANGELOG.md).
- **Reporting a break:** open a `compatibility-break` issue with your `docket --version`,
  `openclaw --version`, and the failing command. See `.github/ISSUE_TEMPLATE/`.

## Roadmap

Automated weekly CI that installs the latest OpenClaw, runs the integration suite, and opens an
auto-issue on break is a tracked roadmap item (see [ROADMAP.md](ROADMAP.md)). Until then the
matrix reflects manual verification, and this file is the single place that claim lives.
