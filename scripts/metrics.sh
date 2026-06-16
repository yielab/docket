#!/usr/bin/env bash
#
# metrics.sh — single source of truth for project metrics.
#
# The README and docs quote line counts, command counts, and test counts.
# Hand-maintained, these drift and contradict each other. This script computes
# them from the tree so there is exactly one authority.
#
#   ./scripts/metrics.sh            # human-readable report
#   ./scripts/metrics.sh --json     # machine-readable (CI / badges)
#   ./scripts/metrics.sh --check    # verify README numbers match (non-zero on drift)
#
# Add new metrics here, not in prose.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- compute -----------------------------------------------------------------

# Core commands: one cmd_* per file in lib/commands (experimental excluded).
core_cmd_files=$(find lib/commands -maxdepth 1 -name '*.sh' | wc -l | tr -d ' ')
experimental_cmds=$(find lib/commands/experimental -name '*.sh' 2>/dev/null | wc -l | tr -d ' ')
helper_modules=$(find lib/helpers -maxdepth 1 -name '*.sh' | wc -l | tr -d ' ')

# Lines of Bash: the shipped CLI (lib + bin) vs. everything (incl. tests/tooling).
loc_cli=$(find lib bin -type f \( -name '*.sh' -o -name 'rack' \) -exec cat {} + | wc -l | tr -d ' ')
loc_all=$(find lib bin tests scripts -type f \( -name '*.sh' -o -name 'rack' \) -exec cat {} + | wc -l | tr -d ' ')

# Unit tests: trust the harness's own pass counter rather than grepping asserts.
unit_tests=$(./tests/unit/test-helpers.sh 2>/dev/null | grep -oE 'Passed:[[:space:]]+[0-9]+' | grep -oE '[0-9]+' || echo 0)

specs=$(find specs -name '*.spec.md' | wc -l | tr -d ' ')

# --- emit --------------------------------------------------------------------

case "${1:-}" in
  --json)
    cat <<EOF
{
  "core_commands": $core_cmd_files,
  "experimental_commands": $experimental_cmds,
  "helper_modules": $helper_modules,
  "loc_cli": $loc_cli,
  "loc_all": $loc_all,
  "unit_tests": $unit_tests,
  "spec_files": $specs
}
EOF
    ;;
  --check)
    fail=0
    grep -q "$unit_tests unit" README.md || { echo "DRIFT: README unit-test count != $unit_tests"; fail=1; }
    grep -qE "$core_cmd_files commands" README.md || { echo "DRIFT: README command count != $core_cmd_files"; fail=1; }
    [[ $fail -eq 0 ]] && echo "metrics: README in sync ($unit_tests tests, $core_cmd_files commands)"
    exit $fail
    ;;
  *)
    printf '%-26s %s\n' "Core commands:"        "$core_cmd_files"
    printf '%-26s %s\n' "Experimental commands:" "$experimental_cmds"
    printf '%-26s %s\n' "Helper modules:"       "$helper_modules"
    printf '%-26s %s\n' "Lines of Bash (CLI):"  "$loc_cli"
    printf '%-26s %s\n' "Lines of Bash (all):"  "$loc_all"
    printf '%-26s %s\n' "Unit tests:"           "$unit_tests"
    printf '%-26s %s\n' "Spec files:"           "$specs"
    ;;
esac
