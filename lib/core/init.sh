#!/usr/bin/env bash
# Core initialization - strict mode and debug settings

# docket uses Bash 4+ features (associative arrays, ${var,,}, etc.). macOS ships
# Bash 3.2 by default — fail early with a clear message instead of cryptic errors.
if [[ -z "${BASH_VERSINFO:-}" || "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "docket requires Bash 4.0+ (found ${BASH_VERSION:-unknown})." >&2
  echo "  On macOS: brew install bash, then run docket with the newer bash." >&2
  exit 1
fi

# Strict mode for better error handling
set -euo pipefail

# Debug mode (export DEBUG=1 or pass --debug)
DEBUG="${DEBUG:-0}"
