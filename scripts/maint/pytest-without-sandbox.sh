#!/usr/bin/env bash
# Run pytest as a host with no sandbox backend would (a stock macOS CI runner):
# DOCKET_SANDBOX_PROBE=none hides the kernel's Landlock and macOS's sandbox-exec. Docker is never
# probed unless the operator chose it (`docket setup sandbox backend docker`), so PATH is left alone.
#
# DOCKET_SANDBOX_BACKEND=none is not the same check: a test fixture that deletes that variable
# for hermeticity falls back to detection. Here detection itself reports "none".
#
# Usage: scripts/maint/pytest-without-sandbox.sh [pytest args...]
set -euo pipefail

home="$(mktemp -d "${TMPDIR:-/tmp}/docket-nosandbox.XXXX")"
trap 'rm -rf "$home"' EXIT

export DOCKET_SANDBOX_PROBE=none
env -u DOCKET_SANDBOX_BACKEND DOCKET_HOME="$home" uv run --extra mcp python -c \
    "from docket.sandbox import launch; b = launch.sandbox_availability().backend; assert b == 'none', b"
env -u DOCKET_SANDBOX_BACKEND uv run --extra mcp pytest -p no:cacheprovider "$@"
