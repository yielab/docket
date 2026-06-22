#!/usr/bin/env bash
# spec-coverage.sh — mechanical spec↔code linter (CDD-5).
#
# Extracts the LIVE command set from router.sh and the DOCUMENTED command set
# from cli-interface.spec.md, then fails if either set has entries the other
# does not. Exit 0 = green; exit 1 = red (missing or stale entries found).
#
# Usage:
#   scripts/spec-coverage.sh           # check only, color output
#   scripts/spec-coverage.sh --ci      # same but no color (for CI logs)
#   scripts/spec-coverage.sh --fix-hint  # print exact lines to add/remove
#
# What counts as "documented"?
#   A command is documented when cli-interface.spec.md contains a markdown
#   heading that names it: "#### docket <cmd>" (exact prefix match).
#   Bare prose mentions and alias lines do NOT count.
#
# What counts as "routed"?
#   The case arm label in router.sh: the FIRST word of each "word) cmd_*"
#   pattern. Aliases (e.g. "list|ls)") yield the first token.
#   Removed/renamed commands (reset, repair, model, …) are excluded — they
#   are in the router only to print migration hints and exit 1, not to expose
#   real functionality.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROUTER="$REPO_ROOT/lib/core/router.sh"
CLI_SPEC="$REPO_ROOT/specs/api/cli-interface.spec.md"

# ── Color support ──────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--ci" ]]; then
  RED="" GREEN="" YELLOW="" BOLD="" RESET=""
else
  RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m'
  BOLD='\033[1m' RESET='\033[0m'
fi

# ── Extract routed commands from router.sh ─────────────────────────────────────
# Matches lines like:  "  list)              cmd_list  "$@" ;;"
# or                   "  install|setup)     cmd_install "$@" ;;"
# Captures the first token before ) or |.
# Excludes the stale-command block (reset, repair, cleanup, model, billing,
# monitor, memory, smart, ai, mode, terminal, term, browser, brave) — these are
# shim routes that print a migration hint and exit 1, not real commands.

_REMOVED_CMDS="reset|repair|cleanup|clean|model|billing|credits|monitor|mon|memory|mem|smart|ai|mode|terminal|term|browser|brave"

routed_commands() {
  python3 - "$ROUTER" "$_REMOVED_CMDS" <<'PY'
import re, sys

path     = sys.argv[1]
removed  = set(sys.argv[2].split("|"))

pattern = re.compile(r'^\s+([a-z][a-z0-9_|/-]*)(\|[a-z][a-z0-9_|/-]*)?\)\s+cmd_')
cmds = set()
with open(path) as f:
    for line in f:
        m = pattern.match(line)
        if not m:
            continue
        # first token (before any |)
        first = m.group(1).split("|")[0]
        if first in removed:
            continue
        cmds.add(first)

for c in sorted(cmds):
    print(c)
PY
}

# ── Extract documented commands from cli-interface.spec.md ────────────────────
# A command is documented when a heading "#### docket <cmd>" appears (exact).

documented_commands() {
  python3 - "$CLI_SPEC" <<'PY'
import re, sys

pattern = re.compile(r'^#{1,6}\s+docket\s+([a-z][a-z0-9_-]*)(\s|$)')
cmds = set()
with open(sys.argv[1]) as f:
    for line in f:
        m = pattern.match(line)
        if m:
            cmds.add(m.group(1))

for c in sorted(cmds):
    print(c)
PY
}

# ── Compare ────────────────────────────────────────────────────────────────────
mapfile -t ROUTED     < <(routed_commands)
mapfile -t DOCUMENTED < <(documented_commands)

declare -A _routed_map _doc_map
for c in "${ROUTED[@]}";     do _routed_map["$c"]=1; done
for c in "${DOCUMENTED[@]}"; do _doc_map["$c"]=1;    done

missing_from_spec=()   # routed but not documented
stale_in_spec=()       # documented but not routed

for c in "${ROUTED[@]}"; do
  [[ -z "${_doc_map[$c]+x}" ]] && missing_from_spec+=("$c")
done
for c in "${DOCUMENTED[@]}"; do
  [[ -z "${_routed_map[$c]+x}" ]] && stale_in_spec+=("$c")
done

# ── Report ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Spec↔Code linter${RESET} — router.sh vs cli-interface.spec.md"
echo ""

if [[ "${#missing_from_spec[@]}" -eq 0 && "${#stale_in_spec[@]}" -eq 0 ]]; then
  echo -e "${GREEN}✓ All ${#ROUTED[@]} routed commands are documented; no stale entries.${RESET}"
  echo ""
  exit 0
fi

FAIL=0

if [[ "${#missing_from_spec[@]}" -gt 0 ]]; then
  echo -e "${RED}✗ Routed commands missing from spec (${#missing_from_spec[@]}):${RESET}"
  for c in "${missing_from_spec[@]}"; do
    echo "    $c"
  done
  echo ""
  echo -e "  Add a ${YELLOW}#### docket <cmd>${RESET} section to specs/api/cli-interface.spec.md"
  echo ""
  FAIL=1
fi

if [[ "${#stale_in_spec[@]}" -gt 0 ]]; then
  echo -e "${YELLOW}⚠ Spec entries with no matching router.sh arm (${#stale_in_spec[@]}):${RESET}"
  for c in "${stale_in_spec[@]}"; do
    echo "    $c"
  done
  echo ""
  echo -e "  Remove or update those sections, or add the command to router.sh"
  echo ""
  FAIL=1
fi

exit "$FAIL"
