#!/usr/bin/env bash
# Command: audit — view the mutating-operations audit log (Phase 4).

cmd_audit() {
  local arg="${1:-20}"
  local logf="${OPENCLAW_DIR:-$HOME/.openclaw}/audit.log"

  if [[ ! -f "$logf" ]]; then
    info "No audit log yet."
    echo "  ${DIM}Mutations (keys, gates, profile, scope, add/delete) are recorded to${RESET}"
    echo "  ${DIM}$logf once you make a change.${RESET}"
    return 0
  fi

  # Raw JSONL passthrough for scripting.
  if [[ "$arg" == "--json" ]]; then
    cat "$logf"
    return 0
  fi

  local n="$arg"
  [[ "$n" =~ ^[0-9]+$ ]] || n=20

  header "Audit log — last $n change(s)"
  echo ""
  python3 - "$logf" "$n" <<'PY'
import json, sys
path, n = sys.argv[1], int(sys.argv[2])
lines = [l for l in open(path) if l.strip()]
if not lines:
    print("  (empty)")
for line in lines[-n:]:
    try:
        e = json.loads(line)
    except Exception:
        continue
    print(f"  {e.get('ts',''):<20}  {e.get('user','?'):<10}  {e.get('action',''):<16}  {e.get('detail','')}")
PY
  echo ""
  echo "${DIM}Full JSONL: rack audit --json  ·  file: $logf${RESET}"
}
