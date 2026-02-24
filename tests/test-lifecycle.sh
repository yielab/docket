#!/usr/bin/env bash
# test-lifecycle.sh — Full lifecycle test for the rack command
#
# Tests: add → list → info → repair → reset → delete
# Uses a temporary "test-rack" agent backed by the demo-project codebase.
#
# Usage:  ./tests/test-lifecycle.sh
#         ./tests/test-lifecycle.sh --keep   (skip delete — leave agent for inspection)

set -uo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
TEST_ID="test-rack"
TEST_NAME="Test Rack"
CODEBASE="$HOME/Sites/demo-project"
RACK="$(dirname "$(realpath "$0")")/../bin/rack"
PROJECTS_DIR="$HOME/.openclaw/workspaces/projects"
CONFIG_FILE="$HOME/.openclaw/openclaw.json"
KEEP=false
[[ "${1:-}" == "--keep" ]] && KEEP=true

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

passed=0; failed=0; skipped=0

pass() { echo -e "  ${GREEN}✓ PASS${RESET}  $1"; ((passed++)); }
fail() { echo -e "  ${RED}✗ FAIL${RESET}  $1${2:+ — $2}"; ((failed++)); }
skip() { echo -e "  ${YELLOW}⊘ SKIP${RESET}  $1${2:+ — $2}"; ((skipped++)); }
section() { echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"; }

# ─── Pre-flight checks ──────────────────────────────────────────────────────
section "Pre-flight"

if [[ ! -x "$RACK" ]]; then
  fail "rack binary not found at $RACK"
  exit 1
fi
pass "rack binary exists: $RACK"

if ! command -v openclaw &>/dev/null; then
  fail "openclaw not in PATH"
  exit 1
fi
pass "openclaw in PATH: $(command -v openclaw)"

if [[ ! -d "$CODEBASE" ]]; then
  fail "codebase not found: $CODEBASE"
  exit 1
fi
pass "codebase exists: $CODEBASE"

if [[ ! -f "$CONFIG_FILE" ]]; then
  fail "openclaw config not found: $CONFIG_FILE"
  exit 1
fi
pass "openclaw.json exists"

# Clean up any leftover test agent from a previous failed run
if [[ -d "$PROJECTS_DIR/$TEST_ID" ]]; then
  echo -e "  ${YELLOW}⚠${RESET}  Leftover workspace from previous run — cleaning up..."
  # Remove from openclaw agents list
  python3 -c "
import json
with open('$CONFIG_FILE') as f:
    c = json.load(f)
c['agents']['list'] = [a for a in c.get('agents',{}).get('list',[]) if a.get('id') != '$TEST_ID']
c['bindings'] = [b for b in c.get('bindings',[]) if b.get('agentId') != '$TEST_ID']
with open('$CONFIG_FILE','w') as f:
    json.dump(c, f, indent=2)
" 2>/dev/null
  rm -rf "$PROJECTS_DIR/$TEST_ID"
  pass "cleaned up leftover test agent"
fi

# Snapshot config before tests (for rollback verification)
AGENTS_BEFORE=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print(len(c.get('agents',{}).get('list',[])))
" 2>/dev/null)
pass "baseline: $AGENTS_BEFORE agents registered"

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: rack add
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 1: rack add (create project agent)"

# Interactive inputs for cmd_add:
#   1. Type [1/2]          → 1 (repo)
#   2. Display name        → Test Rack
#   3. Agent ID [default]  → test-rack
#   4. Codebase path       → (accept detected default)
#   5. Description         → Test project for lifecycle test
#   6. Stack [detected]    → (accept detected)
#   7. Model [default]     → (accept default)
#   8. Telegram group ID   → (empty = skip)
ADD_OUTPUT=$(printf '%s\n' \
  "1" \
  "$TEST_NAME" \
  "$TEST_ID" \
  "$CODEBASE" \
  "Test project for lifecycle test" \
  "" \
  "" \
  "" \
  | "$RACK" add 2>&1) || true

ADD_EXIT=$?

# Check workspace created
if [[ -d "$PROJECTS_DIR/$TEST_ID" ]]; then
  pass "workspace directory created: $PROJECTS_DIR/$TEST_ID"
else
  fail "workspace directory NOT created" "$ADD_OUTPUT"
fi

# Check required files
for f in SOUL.md AGENTS.md TOOLS.md HEARTBEAT.md .rack-meta.json; do
  if [[ -f "$PROJECTS_DIR/$TEST_ID/$f" ]]; then
    pass "file created: $f"
  else
    fail "file missing: $f"
  fi
done

# Check memory directory
if [[ -d "$PROJECTS_DIR/$TEST_ID/memory" ]]; then
  pass "memory/ directory created"
else
  fail "memory/ directory missing"
fi

# Check permissions (dirs should be 700, files should be 600)
dir_perms=$(stat -c %a "$PROJECTS_DIR/$TEST_ID" 2>/dev/null)
if [[ "$dir_perms" == "700" ]]; then
  pass "workspace permissions: 700"
else
  fail "workspace permissions: expected 700, got $dir_perms"
fi

file_perms=$(stat -c %a "$PROJECTS_DIR/$TEST_ID/SOUL.md" 2>/dev/null)
if [[ "$file_perms" == "600" ]]; then
  pass "file permissions: 600"
else
  fail "file permissions: expected 600, got $file_perms"
fi

# Check .rack-meta.json content
META_TYPE=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('type',''))" 2>/dev/null)
if [[ "$META_TYPE" == "repo" ]]; then
  pass "meta: type = repo"
else
  fail "meta: type expected 'repo', got '$META_TYPE'"
fi

META_CODEBASE=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('codebase',''))" 2>/dev/null)
if [[ "$META_CODEBASE" == "$CODEBASE" ]]; then
  pass "meta: codebase = $CODEBASE"
else
  fail "meta: codebase expected '$CODEBASE', got '$META_CODEBASE'"
fi

# Check agent registered in openclaw.json
REGISTERED=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
ids = [a.get('id') for a in c.get('agents',{}).get('list',[])]
print('yes' if '$TEST_ID' in ids else 'no')
" 2>/dev/null)
if [[ "$REGISTERED" == "yes" ]]; then
  pass "agent registered in openclaw.json"
else
  fail "agent NOT registered in openclaw.json"
fi

# Check SOUL.md contains project details
if grep -q "$TEST_NAME" "$PROJECTS_DIR/$TEST_ID/SOUL.md" 2>/dev/null; then
  pass "SOUL.md contains project name"
else
  fail "SOUL.md missing project name"
fi

if grep -q "$CODEBASE" "$PROJECTS_DIR/$TEST_ID/SOUL.md" 2>/dev/null; then
  pass "SOUL.md contains codebase path"
else
  fail "SOUL.md missing codebase path"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: rack list
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 2: rack list"

LIST_OUTPUT=$("$RACK" list 2>&1) || true

if echo "$LIST_OUTPUT" | grep -q "$TEST_ID"; then
  pass "list output contains test agent '$TEST_ID'"
else
  fail "list output missing '$TEST_ID'" "$(echo "$LIST_OUTPUT" | head -5)"
fi

if echo "$LIST_OUTPUT" | grep -q "AGENT"; then
  pass "list output has table header"
else
  fail "list output missing table header"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: rack info
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 3: rack info $TEST_ID"

INFO_OUTPUT=$("$RACK" info "$TEST_ID" 2>&1) || true

if echo "$INFO_OUTPUT" | grep -q "$TEST_NAME"; then
  pass "info shows display name"
else
  fail "info missing display name"
fi

if echo "$INFO_OUTPUT" | grep -q "repo"; then
  pass "info shows type: repo"
else
  fail "info missing type"
fi

if echo "$INFO_OUTPUT" | grep -q "$CODEBASE"; then
  pass "info shows codebase path"
else
  fail "info missing codebase path"
fi

if echo "$INFO_OUTPUT" | grep -q "SOUL.md"; then
  pass "info lists workspace files"
else
  fail "info missing workspace file listing"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: rack repair (should find nothing broken)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 4: rack repair $TEST_ID (expect healthy)"

# Repair with no telegram input (skip the prompt by piping empty)
REPAIR_OUTPUT=$(echo "" | "$RACK" repair "$TEST_ID" 2>&1) || true

if echo "$REPAIR_OUTPUT" | grep -qi "healthy\|nothing to fix\|0 issue"; then
  pass "repair reports healthy"
elif echo "$REPAIR_OUTPUT" | grep -qi "fixed"; then
  pass "repair found and fixed issues (acceptable on fresh add)"
else
  fail "repair unexpected output" "$(echo "$REPAIR_OUTPUT" | tail -3)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: rack reset (memory only)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 5: rack reset $TEST_ID (memory only)"

# Create a fake memory file to test clearing
touch "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md"
chmod 600 "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md"

# Reset level 1 (memory only), confirm with "y"
RESET_OUTPUT=$(printf '1\ny\n' | "$RACK" reset "$TEST_ID" 2>&1) || true

if [[ ! -f "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md" ]]; then
  pass "reset cleared memory log files"
else
  fail "reset did NOT clear memory log files"
fi

# Verify SOUL.md still exists (reset shouldn't touch it)
if [[ -f "$PROJECTS_DIR/$TEST_ID/SOUL.md" ]]; then
  pass "reset preserved SOUL.md"
else
  fail "reset incorrectly deleted SOUL.md"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: rack doctor (system health)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 6: rack doctor"

DOCTOR_OUTPUT=$("$RACK" doctor 2>&1) || true

if echo "$DOCTOR_OUTPUT" | grep -q "openclaw"; then
  pass "doctor checks openclaw binary"
else
  fail "doctor missing openclaw check"
fi

if echo "$DOCTOR_OUTPUT" | grep -q "python3"; then
  pass "doctor checks python3"
else
  fail "doctor missing python3 check"
fi

if echo "$DOCTOR_OUTPUT" | grep -q "$TEST_ID"; then
  pass "doctor includes test agent in project checks"
else
  fail "doctor missing test agent check"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: rack delete
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$KEEP" == true ]]; then
  section "TEST 7: rack delete (SKIPPED — --keep flag)"
  skip "delete" "--keep flag passed"
else
  section "TEST 7: rack delete $TEST_ID"

  # Interactive inputs for cmd_delete:
  #   1. Also delete workspace directory? [y/N] → y
  #   2. Type the agent ID to confirm            → test-rack
  DELETE_OUTPUT=$(printf 'y\n%s\n' "$TEST_ID" | "$RACK" delete "$TEST_ID" 2>&1) || true

  # Verify workspace removed
  if [[ ! -d "$PROJECTS_DIR/$TEST_ID" ]]; then
    pass "workspace directory removed"
  else
    fail "workspace directory still exists"
  fi

  # Verify agent deregistered from openclaw.json
  STILL_REG=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
ids = [a.get('id') for a in c.get('agents',{}).get('list',[])]
print('yes' if '$TEST_ID' in ids else 'no')
" 2>/dev/null)
  if [[ "$STILL_REG" == "no" ]]; then
    pass "agent removed from openclaw.json"
  else
    fail "agent still in openclaw.json after delete"
  fi

  # Verify agent count is back to baseline
  AGENTS_AFTER=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print(len(c.get('agents',{}).get('list',[])))
" 2>/dev/null)
  if [[ "$AGENTS_AFTER" == "$AGENTS_BEFORE" ]]; then
    pass "agent count restored to baseline ($AGENTS_BEFORE)"
  else
    fail "agent count mismatch: before=$AGENTS_BEFORE after=$AGENTS_AFTER"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}═══════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Results: ${GREEN}$passed passed${RESET}, ${RED}$failed failed${RESET}, ${YELLOW}$skipped skipped${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════${RESET}"
echo ""

if [[ "$failed" -gt 0 ]]; then
  echo -e "${RED}${BOLD}Some tests failed.${RESET}"
  exit 1
else
  echo -e "${GREEN}${BOLD}All tests passed.${RESET}"
  exit 0
fi
