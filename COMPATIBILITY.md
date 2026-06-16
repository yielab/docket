# Compatibility

rack wraps the [OpenClaw](https://openclaw.dev) daemon, which renames and reshapes its config
periodically. This document records what rack is known to work with and how breaks are handled.

## Support matrix

| rack-cli | Tested OpenClaw | `openclaw.json` schema | Notes |
|----------|-----------------|------------------------|-------|
| 0.1.x    | current release line (developed against the 2026.x line) | v1 | Manual verification only; no automated version pin yet |

rack reads the live OpenClaw version (`openclaw --version`) for display but does not currently
enforce a minimum. It writes the v1 `openclaw.json` schema (preserving unknown keys on every
atomic write, so forward-compatible fields survive a round-trip).

## Platform

- **Bash 4.0+** — required (associative arrays, `${var,,}`). macOS ships Bash 3.2; install a
  newer Bash via Homebrew. rack's launcher resolves symlinks and refuses to run on Bash 3.
- **Linux** — primary, CI-gated.
- **macOS** — supported on a best-effort basis; the macOS CI job is currently informational
  (`continue-on-error`) and slated to become a required gate. BSD vs GNU `sed`/`date`
  differences are handled in the helpers.
- **Python 3.7+** — required for all JSON manipulation.
- **systemd** — used for gateway service management on Linux; non-systemd hosts degrade
  gracefully (restart steps are skipped with a warning).

## Policy

- **Schema changes** in OpenClaw are absorbed where possible via the unknown-key-preserving
  atomic writer. A genuinely breaking schema change will be pinned in the matrix above and
  called out in [CHANGELOG.md](CHANGELOG.md).
- **Reporting a break:** open a `compatibility-break` issue with your `rack --version`,
  `openclaw --version`, and the failing command. See `.github/ISSUE_TEMPLATE/`.

## Roadmap

Automated weekly CI that installs the latest OpenClaw, runs the integration suite, and opens an
auto-issue on break is a tracked roadmap item (see [ROADMAP.md](ROADMAP.md)). Until then the
matrix reflects manual verification, and this file is the single place that claim lives.
