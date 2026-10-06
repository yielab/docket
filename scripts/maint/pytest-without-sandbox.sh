#!/usr/bin/env bash
# Run pytest as a host with neither bwrap nor docker would (a stock macOS CI runner).
#
# DOCKET_SANDBOX_BACKEND=none is not the same check: a test fixture that deletes that variable
# for hermeticity falls back to auto-detection and finds this machine's bwrap. Here the binaries
# are absent from PATH, so detection itself reports "none".
#
# Usage: scripts/maint/pytest-without-sandbox.sh [pytest args...]
set -euo pipefail
shopt -s nullglob

bin="$(mktemp -d "${TMPDIR:-/tmp}/docket-nosandbox.XXXX")"
trap 'rm -rf "$bin"' EXIT
IFS=: read -r -a dirs <<<"$PATH"
for dir in "${dirs[@]}"; do
    [ -d "$dir" ] || continue
    for path in "$dir"/*; do
        name="$(basename "$path")"
        case "$name" in bwrap | docker | dockerd | docker-*) continue ;; esac
        [ -e "$bin/$name" ] || ln -s "$path" "$bin/$name"
    done
done

env -u DOCKET_SANDBOX_BACKEND PATH="$bin" uv run --extra mcp python -c \
    "from docket.edges.adapters import system; b = system.sandbox_availability().backend; assert b == 'none', b"
env -u DOCKET_SANDBOX_BACKEND PATH="$bin" uv run --extra mcp pytest -p no:cacheprovider "$@"
