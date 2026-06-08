#!/usr/bin/env bash
# test-lifecycle.sh — Full lifecycle test for the rack command
#
# Tests: add → list → info → scope → team → workflow → repair → reset → cost → profile → delete
# Uses a temporary "test-rack" agent backed by the demo-project codebase.
#
# Usage:  ./tests/test-lifecycle.sh
#         ./tests/test-lifecycle.sh --keep    (skip delete — leave agent for inspection)
#         ./tests/test-lifecycle.sh --clean   (clean current setup and reinstall)

set -uo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
TEST_ID="test-rack"
TEST_NAME="Test Rack"
CODEBASE="$HOME/Sites/demo-project"
RACK="$(dirname "$(realpath "$0")")/../bin/rack"
PROJECTS_DIR="$HOME/.openclaw/workspaces/projects"
OPENCLAW_DIR="$HOME/.openclaw"
CONFIG_FILE="$HOME/.openclaw/openclaw.json"
CONFIG_BACKUP="$HOME/.openclaw/openclaw.json.backup-$(date +%s)"
KEEP=false
CLEAN=false
[[ "${1:-}" == "--keep" ]] && KEEP=true
[[ "${1:-}" == "--clean" ]] && CLEAN=true

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

passed=0; failed=0; skipped=0

pass() { echo -e "  ${GREEN}✓ PASS${RESET}  $1"; ((passed++)); }
fail() { echo -e "  ${RED}✗ FAIL${RESET}  $1${2:+ — $2}"; ((failed++)); }
skip() { echo -e "  ${YELLOW}⊘ SKIP${RESET}  $1${2:+ — $2}"; ((skipped++)); }
section() { echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"; }

# ─── Clean install mode ──────────────────────────────────────────────────────
if [[ "$CLEAN" == true ]]; then
  section "Clean Install Mode"

  if [[ -f "$CONFIG_FILE" ]]; then
    echo -e "  ${YELLOW}⚠${RESET}  Backing up current config..."
    cp "$CONFIG_FILE" "$CONFIG_BACKUP"
    pass "config backed up: $CONFIG_BACKUP"
  fi

  echo -e "  ${YELLOW}⚠${RESET}  Removing OpenClaw directory..."
  if [[ -d "$OPENCLAW_DIR" ]]; then
    rm -rf "$OPENCLAW_DIR"
    pass "removed $OPENCLAW_DIR"
  fi

  echo -e "  ${CYAN}→${RESET}  Running: rack install"
  echo ""

  # Run rack install (will be interactive, so pass "y" to confirm)
  printf 'y\n' | "$RACK" install || {
    fail "rack install failed"
    exit 1
  }

  pass "rack install completed"
  echo ""
fi

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
  echo -e "  ${CYAN}→${RESET}  Run: ./tests/test-lifecycle.sh --clean"
  exit 1
fi
pass "openclaw.json exists"

# Verify specialist agents exist (from rack install)
SPECIALISTS=("programmer" "reviewer" "tester" "knowledge" "security")
MISSING_SPECS=()
for spec in "${SPECIALISTS[@]}"; do
  SPEC_EXISTS=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
ids = [a.get('id') for a in c.get('agents',{}).get('list',[])]
print('yes' if '$spec' in ids else 'no')
" 2>/dev/null)

  if [[ "$SPEC_EXISTS" == "yes" ]]; then
    pass "specialist agent: $spec"
  else
    MISSING_SPECS+=("$spec")
  fi
done

if [[ "${#MISSING_SPECS[@]}" -gt 0 ]]; then
  fail "missing specialist agents: ${MISSING_SPECS[*]}"
  echo -e "  ${CYAN}→${RESET}  Run: ./tests/test-lifecycle.sh --clean"
  exit 1
fi

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

# Check session key in SOUL.md
if grep -q "Session Key:" "$PROJECTS_DIR/$TEST_ID/SOUL.md" 2>/dev/null; then
  pass "SOUL.md contains session key"
else
  fail "SOUL.md missing session key"
fi

if grep -q "agent:$TEST_ID:default" "$PROJECTS_DIR/$TEST_ID/SOUL.md" 2>/dev/null; then
  pass "SOUL.md has correct session key format"
else
  fail "SOUL.md has incorrect session key format"
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

if echo "$LIST_OUTPUT" | grep -qi "project agents"; then
  pass "list output has header"
else
  fail "list output missing header"
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
# TEST 4: rack maintain check (health check — expect healthy)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 4: rack maintain $TEST_ID check (expect healthy)"

MAINTAIN_OUTPUT=$("$RACK" maintain "$TEST_ID" check 2>&1) || true

if echo "$MAINTAIN_OUTPUT" | grep -qi "healthy\|nothing to fix\|0 issue"; then
  pass "maintain check reports healthy"
elif echo "$MAINTAIN_OUTPUT" | grep -qi "fixed\|issues found\|synced\|mismatch"; then
  pass "maintain check found and fixed issues (acceptable on fresh add)"
else
  fail "maintain check unexpected output" "$(echo "$MAINTAIN_OUTPUT" | tail -3)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: rack maintain clean (memory logs only)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 5: rack maintain $TEST_ID clean (memory only)"

# Create a fake memory file to test clearing
touch "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md"
chmod 600 "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md"

# Clean memory logs, confirm with "y"
CLEAN_OUTPUT=$(printf 'y\n' | "$RACK" maintain "$TEST_ID" clean 2>&1) || true

if [[ ! -f "$PROJECTS_DIR/$TEST_ID/memory/2026-01-01.md" ]]; then
  pass "maintain clean cleared memory log files"
else
  fail "maintain clean did NOT clear memory log files"
fi

# Verify SOUL.md still exists (clean should not touch it)
if [[ -f "$PROJECTS_DIR/$TEST_ID/SOUL.md" ]]; then
  pass "maintain clean preserved SOUL.md"
else
  fail "maintain clean incorrectly deleted SOUL.md"
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
# TEST 7: rack cost
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 7: rack cost"

# Test cost for all agents
COST_ALL_OUTPUT=$("$RACK" cost 2>&1) || true

if echo "$COST_ALL_OUTPUT" | grep -q "AGENT"; then
  pass "cost (all) shows table header"
else
  fail "cost (all) missing table header"
fi

if echo "$COST_ALL_OUTPUT" | grep -q "$TEST_ID"; then
  pass "cost (all) includes test agent"
else
  fail "cost (all) missing test agent"
fi

if echo "$COST_ALL_OUTPUT" | grep -q "Total"; then
  pass "cost (all) shows total line"
else
  fail "cost (all) missing total line"
fi

# Test cost for single agent
COST_SINGLE=$("$RACK" cost "$TEST_ID" 2>&1) || true

if echo "$COST_SINGLE" | grep -q "Model:"; then
  pass "cost (single) shows model info"
else
  fail "cost (single) missing model info"
fi

if echo "$COST_SINGLE" | grep -q "Profile:"; then
  pass "cost (single) shows profile info"
else
  fail "cost (single) missing profile info"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8: rack profile
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 8: rack profile $TEST_ID"

# Show current profile (no change)
PROFILE_SHOW=$("$RACK" profile "$TEST_ID" 2>&1) || true

if echo "$PROFILE_SHOW" | grep -q "standard"; then
  pass "profile shows current tier (standard)"
else
  fail "profile not showing current tier"
fi

if echo "$PROFILE_SHOW" | grep -q "economy"; then
  pass "profile lists available tiers"
else
  fail "profile missing available tiers"
fi

# Change to economy
"$RACK" profile "$TEST_ID" economy 2>&1 || true

ECONOMY_MODEL=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('model',''))" 2>/dev/null)
if echo "$ECONOMY_MODEL" | grep -qi "haiku"; then
  pass "profile change to economy: model is haiku"
else
  fail "profile change to economy: expected haiku, got $ECONOMY_MODEL"
fi

# Verify openclaw.json was updated too
OC_MODEL=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
for a in c.get('agents',{}).get('list',[]):
    if a.get('id') == '$TEST_ID':
        print(a.get('model','')); break
" 2>/dev/null)
if echo "$OC_MODEL" | grep -qi "haiku"; then
  pass "profile change updated openclaw.json"
else
  fail "profile change did not update openclaw.json (got: $OC_MODEL)"
fi

# Change back to standard for clean state
"$RACK" profile "$TEST_ID" standard 2>&1 || true

RESTORED_MODEL=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('model',''))" 2>/dev/null)
if echo "$RESTORED_MODEL" | grep -qi "sonnet"; then
  pass "profile restored to standard"
else
  fail "profile restore failed: got $RESTORED_MODEL"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9: rack scope (session key management)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 9: rack scope $TEST_ID"

# Show current scope
SCOPE_SHOW=$("$RACK" scope "$TEST_ID" show 2>&1) || true

if echo "$SCOPE_SHOW" | grep -q "agent:$TEST_ID:default"; then
  pass "scope shows default session key"
else
  fail "scope missing session key" "$(echo "$SCOPE_SHOW" | head -3)"
fi

# Change scope to "alpha"
"$RACK" scope "$TEST_ID" set alpha 2>&1 || true

# Verify session key updated in metadata
ALPHA_KEY=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('sessionKey',''))" 2>/dev/null)
if echo "$ALPHA_KEY" | grep -q "agent:$TEST_ID:alpha"; then
  pass "scope changed to alpha: $ALPHA_KEY"
else
  fail "scope change failed: got $ALPHA_KEY"
fi

# Reset to default
"$RACK" scope "$TEST_ID" reset 2>&1 || true

RESET_KEY=$(python3 -c "import json; print(json.load(open('$PROJECTS_DIR/$TEST_ID/.rack-meta.json')).get('sessionKey',''))" 2>/dev/null)
if echo "$RESET_KEY" | grep -q "agent:$TEST_ID:default"; then
  pass "scope reset to default"
else
  fail "scope reset failed: got $RESET_KEY"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 10: rack team (manager agent)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 10: rack team"

# Check team status (should show specialist agents)
TEAM_STATUS=$("$RACK" team status 2>&1) || true

if echo "$TEAM_STATUS" | grep -q "programmer"; then
  pass "team status shows programmer"
else
  fail "team status missing programmer"
fi

if echo "$TEAM_STATUS" | grep -q "Manager agent"; then
  pass "team status shows manager"
else
  skip "team init" "manager not initialized (run: rack team init)"
fi

# Verify TASK_LIST.json exists if manager is initialized
MANAGER_EXISTS=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
ids = [a.get('id') for a in c.get('agents',{}).get('list',[])]
print('yes' if 'manager' in ids else 'no')
" 2>/dev/null)

if [[ "$MANAGER_EXISTS" == "yes" ]] && [[ -f "$HOME/.openclaw/workspaces/manager/TASK_LIST.json" ]]; then
  pass "manager TASK_LIST.json exists"
else
  skip "TASK_LIST.json check" "manager not initialized or delegation not yet used"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 11: rack workflow (Lobster pipelines)
# ═══════════════════════════════════════════════════════════════════════════════
section "TEST 11: rack workflow $TEST_ID"

# List workflows (should be empty initially)
WORKFLOW_LIST=$("$RACK" workflow "$TEST_ID" list 2>&1) || true

if echo "$WORKFLOW_LIST" | grep -qi "no workflows\|0 workflows"; then
  pass "workflow list shows no workflows"
else
  skip "workflow list" "workflows may already exist"
fi

# Create a test workflow
"$RACK" workflow "$TEST_ID" create test-pipeline 2>&1 || true

if [[ -f "$PROJECTS_DIR/$TEST_ID/workflows/test-pipeline.lobster.yml" ]]; then
  pass "workflow created: test-pipeline.lobster.yml"
else
  fail "workflow file not created"
fi

# Verify workflow contains expected structure
if grep -q "name: test-pipeline" "$PROJECTS_DIR/$TEST_ID/workflows/test-pipeline.lobster.yml" 2>/dev/null; then
  pass "workflow file has correct structure"
else
  fail "workflow file missing name field"
fi

# List workflows again (should show test-pipeline)
WORKFLOW_LIST2=$("$RACK" workflow "$TEST_ID" list 2>&1) || true

if echo "$WORKFLOW_LIST2" | grep -q "test-pipeline"; then
  pass "workflow list shows created workflow"
else
  fail "workflow list missing test-pipeline"
fi

# Clean up workflow
"$RACK" workflow "$TEST_ID" delete test-pipeline <<< "y" 2>&1 || true

if [[ ! -f "$PROJECTS_DIR/$TEST_ID/workflows/test-pipeline.lobster.yml" ]]; then
  pass "workflow deleted successfully"
else
  fail "workflow file still exists after delete"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 12: rack delete
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$KEEP" == true ]]; then
  section "TEST 12: rack delete (SKIPPED — --keep flag)"
  skip "delete" "--keep flag passed"
else
  section "TEST 12: rack delete $TEST_ID"

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
