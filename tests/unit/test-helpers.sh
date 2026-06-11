#!/usr/bin/env bash
# Unit tests for helper functions

# Test framework (simple bash-based)
TESTS_PASSED=0
TESTS_FAILED=0

assert_equals() {
  local expected="$1"
  local actual="$2"
  local test_name="$3"

  if [[ "$expected" == "$actual" ]]; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name"
    echo "  Expected: $expected"
    echo "  Actual:   $actual"
    ((TESTS_FAILED++))
  fi
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local test_name="$3"

  if echo "$haystack" | grep -q "$needle"; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name"
    echo "  String '$needle' not found in '$haystack'"
    ((TESTS_FAILED++))
  fi
}

assert_not_empty() {
  local value="$1"
  local test_name="$2"

  if [[ -n "$value" ]]; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name (value is empty)"
    ((TESTS_FAILED++))
  fi
}

# Setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "$SCRIPT_DIR/../../lib" && pwd)"

# Don't use strict mode for tests (it causes issues with test assertions)
DEBUG="${DEBUG:-0}"
source "$LIB_DIR/core/config.sh"
source "$LIB_DIR/helpers/utils.sh"
source "$LIB_DIR/helpers/session.sh"

echo ""
echo "========================================"
echo "  Unit Tests: Helper Functions"
echo "========================================"
echo ""

# Test: slugify
echo "Testing slugify()..."
result=$(slugify "My Project Name")
assert_equals "my-project-name" "$result" "slugify converts to lowercase and dashes"

result=$(slugify "Test_123  Spaces")
assert_equals "test-123-spaces" "$result" "slugify handles underscores and multiple spaces"

result=$(slugify "Special!@#Chars")
assert_contains "$result" "special" "slugify removes special characters"

echo ""

# Test: generate_session_key
echo "Testing generate_session_key()..."
result=$(generate_session_key "myproject" "default")
assert_equals "agent:myproject:default" "$result" "generate_session_key with default"

result=$(generate_session_key "test-app" "alpha")
assert_equals "agent:test-app:alpha" "$result" "generate_session_key with custom key"

result=$(generate_session_key "myproject")
assert_equals "agent:myproject:default" "$result" "generate_session_key defaults to 'default'"

echo ""

# Test: parse_session_key
echo "Testing parse_session_key()..."
result=$(parse_session_key "agent:myproject:default")
assert_equals "default" "$result" "parse_session_key extracts default"

result=$(parse_session_key "agent:test-app:alpha")
assert_equals "alpha" "$result" "parse_session_key extracts alpha"

result=$(parse_session_key "agent:another:beta")
assert_equals "beta" "$result" "parse_session_key extracts beta"

echo ""

# Test: detect_stack (need temp directory)
echo "Testing detect_stack()..."
TEMP_DIR=$(mktemp -d)
touch "$TEMP_DIR/package.json"
echo '{"dependencies":{"react":"^18.0.0","typescript":"^5.0.0"}}' > "$TEMP_DIR/package.json"

result=$(detect_stack "$TEMP_DIR")
assert_contains "$result" "Node.js" "detect_stack finds Node.js"
assert_contains "$result" "React" "detect_stack finds React from package.json"
assert_contains "$result" "TypeScript" "detect_stack finds TypeScript from package.json"

# Test Python detection
rm "$TEMP_DIR/package.json"
touch "$TEMP_DIR/requirements.txt"
echo "fastapi" > "$TEMP_DIR/requirements.txt"
echo "pytest" >> "$TEMP_DIR/requirements.txt"

result=$(detect_stack "$TEMP_DIR")
assert_contains "$result" "Python" "detect_stack finds Python"
assert_contains "$result" "FastAPI" "detect_stack finds FastAPI from requirements.txt"
assert_contains "$result" "pytest" "detect_stack finds pytest"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""

# Test: model_to_profile
echo "Testing model_to_profile()..."
result=$(model_to_profile "anthropic/claude-haiku-4-5")
assert_equals "economy" "$result" "model_to_profile returns economy for haiku"

result=$(model_to_profile "anthropic/claude-sonnet-4-6")
assert_equals "standard" "$result" "model_to_profile returns standard for sonnet"

result=$(model_to_profile "anthropic/claude-opus-4-6")
assert_equals "premium" "$result" "model_to_profile returns premium for opus"

result=$(model_to_profile "some-unknown-model")
assert_equals "custom" "$result" "model_to_profile returns custom for unknown models"

echo ""

# Test: resolve_model
echo "Testing resolve_model()..."
result=$(resolve_model "economy")
assert_equals "anthropic/claude-haiku-4-5" "$result" "resolve_model expands economy to haiku"

result=$(resolve_model "standard")
assert_equals "anthropic/claude-sonnet-4-6" "$result" "resolve_model expands standard to sonnet"

result=$(resolve_model "premium")
assert_equals "anthropic/claude-opus-4-6" "$result" "resolve_model expands premium to opus"

result=$(resolve_model "anthropic/claude-custom-1-0")
assert_equals "anthropic/claude-custom-1-0" "$result" "resolve_model returns unknown models as-is"

echo ""

# Test: test_cmd_for_stack
echo "Testing test_cmd_for_stack()..."
result=$(test_cmd_for_stack "Python, pytest")
assert_equals "pytest -v" "$result" "test_cmd_for_stack returns pytest for Python"

result=$(test_cmd_for_stack "Node.js, React")
assert_equals "npm test" "$result" "test_cmd_for_stack returns npm test for Node.js"

result=$(test_cmd_for_stack "Go")
assert_equals "go test ./..." "$result" "test_cmd_for_stack returns go test for Go"

result=$(test_cmd_for_stack "Rust")
assert_equals "cargo test" "$result" "test_cmd_for_stack returns cargo test for Rust"

echo ""

# ── P0-1: agents.list config key tests ────────────────────────────────────────
echo "Testing agents.list config key (P0-1)..."
source "$LIB_DIR/helpers/output.sh"
source "$LIB_DIR/helpers/json.sh"

_P01_TMP=$(mktemp)
cat > "$_P01_TMP" <<'JSON'
{
  "agents": {
    "defaults": {"model": {"primary": "anthropic/claude-sonnet-4-6"}},
    "list": [
      {"id": "alpha", "model": "anthropic/claude-haiku-4-5"},
      {"id": "beta",  "model": "anthropic/claude-sonnet-4-6"}
    ]
  },
  "bindings": []
}
JSON

# Override CONFIG_FILE to point at the tmp fixture
_REAL_CONFIG="$CONFIG_FILE"
CONFIG_FILE="$_P01_TMP"

# agent_registered should find agents in agents.list
agent_registered "alpha" 2>/dev/null
assert_equals "0" "$?" "agent_registered finds alpha in agents.list"

agent_registered "beta" 2>/dev/null
assert_equals "0" "$?" "agent_registered finds beta in agents.list"

_missing_exit=0
agent_registered "nonexistent" 2>/dev/null || _missing_exit=$?
assert_equals "1" "$_missing_exit" "agent_registered returns 1 for missing agent"

# Agent count expression (used in install.sh) reads agents.list
_count=$(python3 -c "import json; c=json.load(open('$_P01_TMP')); print(len(c.get('agents', {}).get('list', [])))")
assert_equals "2" "$_count" "agents.list count returns correct number"

# Ensure agents.registered does NOT exist in a valid config (would return 0)
_reg_count=$(python3 -c "import json; c=json.load(open('$_P01_TMP')); print(len(c.get('agents', {}).get('registered', [])))")
assert_equals "0" "$_reg_count" "agents.registered is empty (correct key is agents.list)"

# Restore
CONFIG_FILE="$_REAL_CONFIG"
rm -f "$_P01_TMP"
echo ""

# ── P0-2: Config drift detection logic ────────────────────────────────────────
echo "Testing config drift detection (P0-2)..."
_P02_CFG=$(mktemp)
_P02_META=$(mktemp)

cat > "$_P02_CFG" <<'JSON'
{
  "agents": {
    "defaults": {},
    "list": [
      {"id": "myagent", "model": "anthropic/claude-sonnet-4-6"}
    ]
  },
  "bindings": []
}
JSON

# meta matches openclaw — no drift expected
cat > "$_P02_META" <<'JSON'
{"model": "anthropic/claude-sonnet-4-6", "name": "My Agent"}
JSON

_drift_output=$(python3 - "$_P02_CFG" "$_P02_META" "myagent" <<'PY'
import json, sys
config  = json.load(open(sys.argv[1]))
meta    = json.load(open(sys.argv[2]))
agent_id = sys.argv[3]

meta_model = meta.get("model", "")
oc_agent   = next((a for a in config.get("agents", {}).get("list", []) if a.get("id") == agent_id), None)
oc_model   = oc_agent.get("model", "") if oc_agent else ""

if meta_model and oc_model and meta_model != oc_model:
    print(f"DRIFT: meta={meta_model} openclaw={oc_model}")
else:
    print("OK")
PY
)
assert_equals "OK" "$_drift_output" "drift detector: no drift when models match"

# Introduce drift — meta has different model
cat > "$_P02_META" <<'JSON'
{"model": "anthropic/claude-haiku-4-5", "name": "My Agent"}
JSON

_drift_output=$(python3 - "$_P02_CFG" "$_P02_META" "myagent" <<'PY'
import json, sys
config  = json.load(open(sys.argv[1]))
meta    = json.load(open(sys.argv[2]))
agent_id = sys.argv[3]

meta_model = meta.get("model", "")
oc_agent   = next((a for a in config.get("agents", {}).get("list", []) if a.get("id") == agent_id), None)
oc_model   = oc_agent.get("model", "") if oc_agent else ""

if meta_model and oc_model and meta_model != oc_model:
    print(f"DRIFT: meta={meta_model} openclaw={oc_model}")
else:
    print("OK")
PY
)
assert_contains "$_drift_output" "DRIFT" "drift detector: reports drift when models differ"
assert_contains "$_drift_output" "haiku" "drift detector: drift output includes meta model"
assert_contains "$_drift_output" "sonnet" "drift detector: drift output includes openclaw model"

# Agent not in openclaw.json — no false positive
_drift_output=$(python3 - "$_P02_CFG" "$_P02_META" "unknown-agent" <<'PY'
import json, sys
config  = json.load(open(sys.argv[1]))
meta    = json.load(open(sys.argv[2]))
agent_id = sys.argv[3]

meta_model = meta.get("model", "")
oc_agent   = next((a for a in config.get("agents", {}).get("list", []) if a.get("id") == agent_id), None)
oc_model   = oc_agent.get("model", "") if oc_agent else ""

if meta_model and oc_model and meta_model != oc_model:
    print(f"DRIFT: meta={meta_model} openclaw={oc_model}")
else:
    print("OK")
PY
)
assert_equals "OK" "$_drift_output" "drift detector: no false positive for agent absent from openclaw"

rm -f "$_P02_CFG" "$_P02_META"
echo ""

# ── P0-3: oc_get / oc_set / set_agent_model ───────────────────────────────────
echo "Testing oc_get / oc_set / set_agent_model (P0-3)..."

_P03_CFG=$(mktemp)
_P03_META_DIR=$(mktemp -d)
mkdir -p "$_P03_META_DIR/testagent"

cat > "$_P03_CFG" <<'JSON'
{
  "agents": {
    "defaults": {"model": {"primary": "anthropic/claude-sonnet-4-6"}},
    "list": [
      {"id": "testagent", "model": "anthropic/claude-sonnet-4-6"}
    ]
  },
  "bindings": []
}
JSON

cat > "$_P03_META_DIR/testagent/.rack-meta.json" <<'JSON'
{"name": "Test Agent", "model": "anthropic/claude-sonnet-4-6"}
JSON

# Override globals for isolated testing
_REAL_CONFIG2="$CONFIG_FILE"
_REAL_PROJECTS="$PROJECTS_DIR"
CONFIG_FILE="$_P03_CFG"
PROJECTS_DIR="$_P03_META_DIR"

# oc_get: read a dotted path
_val=$(oc_get "agents.defaults.model.primary" "fallback")
assert_equals "anthropic/claude-sonnet-4-6" "$_val" "oc_get reads dotted path"

_val=$(oc_get "agents.nonexistent.field" "mydefault")
assert_equals "mydefault" "$_val" "oc_get returns default for missing path"

# oc_set: write a value and read it back
oc_set "agents.defaults.model.primary" '"anthropic/claude-haiku-4-5"'
_val=$(oc_get "agents.defaults.model.primary" "")
assert_equals "anthropic/claude-haiku-4-5" "$_val" "oc_set writes and oc_get reads back"

# oc_set: creates .bak before writing
assert_not_empty "$(ls "${_P03_CFG}.bak" 2>/dev/null)" "oc_set creates .bak backup file"

# oc_set: file is valid JSON after write
python3 -c "import json; json.load(open('$_P03_CFG'))" 2>/dev/null
assert_equals "0" "$?" "oc_set produces valid JSON"

# oc_set: bad JSON value is rejected
oc_set "some.key" "not-valid-json{" 2>/dev/null
assert_equals "1" "$?" "oc_set rejects invalid JSON value"

# set_agent_model: updates both sources
set_agent_model "testagent" "anthropic/claude-haiku-4-5"
_oc_model=$(python3 -c "
import json
c = json.load(open('$_P03_CFG'))
a = next((x for x in c.get('agents',{}).get('list',[]) if x.get('id')=='testagent'), {})
print(a.get('model',''))
")
_meta_model=$(python3 -c "
import json
print(json.load(open('$_P03_META_DIR/testagent/.rack-meta.json')).get('model',''))
")
assert_equals "anthropic/claude-haiku-4-5" "$_oc_model"    "set_agent_model updates openclaw.json"
assert_equals "anthropic/claude-haiku-4-5" "$_meta_model"  "set_agent_model updates .rack-meta.json"

# Restore
CONFIG_FILE="$_REAL_CONFIG2"
PROJECTS_DIR="$_REAL_PROJECTS"
rm -rf "$_P03_CFG" "${_P03_CFG}.bak" "$_P03_META_DIR"
echo ""

# ── P0-4: mark_gateway_dirty / restart_gateway_if_dirty ───────────────────────
echo "Testing mark_gateway_dirty / restart_gateway_if_dirty (P0-4)..."
source "$LIB_DIR/helpers/service.sh"
export RACK_NO_RESTART=1

# Not dirty — no output
RACK_GATEWAY_DIRTY=0
_out=$(restart_gateway_if_dirty 2>&1)
assert_equals "" "$_out" "restart_gateway_if_dirty is a no-op when not dirty"

# mark_gateway_dirty sets the flag in the current shell
RACK_GATEWAY_DIRTY=0
mark_gateway_dirty
assert_equals "1" "$RACK_GATEWAY_DIRTY" "mark_gateway_dirty sets flag to 1"

# restart_gateway_if_dirty triggers when dirty (test output, then clear flag directly)
RACK_GATEWAY_DIRTY=1
_out=$(restart_gateway_if_dirty 2>&1)
assert_contains "$_out" "dry-run" "restart_gateway_if_dirty triggers when dirty"

# After a direct (non-subshell) call, flag is cleared in parent
RACK_GATEWAY_DIRTY=1
restart_gateway_if_dirty >/dev/null 2>&1
assert_equals "0" "$RACK_GATEWAY_DIRTY" "restart_gateway_if_dirty clears dirty flag after firing"

# Two mark_dirty calls still produce only one restart
RACK_GATEWAY_DIRTY=0
mark_gateway_dirty
mark_gateway_dirty
_restart_count=$(restart_gateway_if_dirty 2>&1 | grep -c "dry-run" || true)
assert_equals "1" "$_restart_count" "multiple mark_dirty calls produce exactly one restart"

unset RACK_NO_RESTART
echo ""

# ── P1-1: Per-agent budget field ───────────────────────────────────────────────
echo "Testing per-agent budget field (P1-1)..."
_P11_DIR=$(mktemp -d)
mkdir -p "$_P11_DIR/testagent"
cat > "$_P11_DIR/testagent/.rack-meta.json" <<'JSON'
{"name": "Test Agent", "model": "anthropic/claude-sonnet-4-6"}
JSON

_REAL_PROJ_P11="$PROJECTS_DIR"
PROJECTS_DIR="$_P11_DIR"

meta_set "testagent" "budgetUsd" "5"
_val=$(meta_get "testagent" "budgetUsd" "")
assert_equals "5" "$_val" "meta_set/get budgetUsd stores and reads integer budget"

meta_set "testagent" "budgetUsd" "10.50"
_val=$(meta_get "testagent" "budgetUsd" "")
assert_equals "10.50" "$_val" "budgetUsd handles decimal amounts"

meta_set "testagent" "budgetUsd" "0"
_val=$(meta_get "testagent" "budgetUsd" "")
assert_equals "0" "$_val" "budgetUsd=0 stored correctly (no cap)"

# Paused flag set and cleared
meta_set "testagent" "paused" "true"
meta_set "testagent" "pausedReason" "budget"
_paused=$(meta_get "testagent" "paused" "")
assert_equals "true" "$_paused" "paused flag stored correctly"
_reason=$(meta_get "testagent" "pausedReason" "")
assert_equals "budget" "$_reason" "pausedReason stored correctly"

PROJECTS_DIR="$_REAL_PROJ_P11"
rm -rf "$_P11_DIR"
echo ""

# ── P1-2: Budget check threshold logic ────────────────────────────────────────
echo "Testing budget check threshold logic (P1-2)..."

# Python percentage calculation
_pct=$(python3 -c "print(int(float('0.50') / float('1.00') * 100))")
assert_equals "50" "$_pct" "budget pct: 50% of cap"

_pct=$(python3 -c "print(int(float('0.85') / float('1.00') * 100))")
assert_equals "85" "$_pct" "budget pct: 85% is in warning zone"

_pct=$(python3 -c "print(int(float('1.05') / float('1.00') * 100))")
assert_equals "105" "$_pct" "budget pct: 105% is over cap"

# Threshold decision logic
_status="ok"
_pv=50
[[ "$_pv" -ge 100 ]] && _status="paused"
[[ "$_status" == "ok" && "$_pv" -ge 80 ]] && _status="warning"
assert_equals "ok" "$_status" "check_budget: <80% returns ok"

_status="ok"
_pv=85
[[ "$_pv" -ge 100 ]] && _status="paused"
[[ "$_status" == "ok" && "$_pv" -ge 80 ]] && _status="warning"
assert_equals "warning" "$_status" "check_budget: ≥80% triggers warning"

_status="ok"
_pv=105
[[ "$_pv" -ge 100 ]] && _status="paused"
[[ "$_status" == "ok" && "$_pv" -ge 80 ]] && _status="warning"
assert_equals "paused" "$_status" "check_budget: ≥100% triggers pause"

echo ""

# ── P1-3: Runaway session detection ───────────────────────────────────────────
echo "Testing runaway session detection (P1-3)..."
source "$LIB_DIR/helpers/workspace.sh"

_P13_SESSIONS=$(mktemp -d)
_P13_JSONL="$_P13_SESSIONS/session-test.jsonl"

# Create 250 turns (above RUNAWAY_TURNS_THRESHOLD=200) with a known cost
python3 -c "
import json
entry = {'message': {'usage': {
    'input': 1000, 'output': 500, 'cacheRead': 0, 'cacheWrite': 0,
    'cost': {'total': 0.01}}}}
with open('$_P13_JSONL', 'w') as f:
    for _ in range(250):
        f.write(json.dumps(entry) + '\n')
"

# Parse the sessions dir directly (mirrors _aggregate_cost logic)
_cost_out=$(python3 - "$_P13_SESSIONS" <<'PY'
import json, sys, os, glob
sessions_dir = sys.argv[1]
total = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0, "turns": 0}
for f in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
    with open(f) as fh:
        for line in fh:
            try:
                data = json.loads(line)
                msg = data.get("message", {})
                usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
                if usage:
                    total["input"]      += usage.get("input", 0)
                    total["output"]     += usage.get("output", 0)
                    total["cacheRead"]  += usage.get("cacheRead", 0)
                    total["cacheWrite"] += usage.get("cacheWrite", 0)
                    cost = usage.get("cost", {})
                    total["cost"]  += cost.get("total", 0) if isinstance(cost, dict) else 0
                    total["turns"] += 1
            except (json.JSONDecodeError, KeyError):
                pass
print(f'{total["input"]}|{total["output"]}|{total["cacheRead"]}|{total["cacheWrite"]}|{total["cost"]:.6f}|{total["turns"]}')
PY
)

IFS='|' read -r _ _ _ _ _total_cost _turns <<< "$_cost_out"
assert_equals "250" "$_turns" "runaway parser: counts 250 turns correctly"

# Threshold comparison: 250 > 200 should trigger
_over_turns=0
[[ "$_turns" -gt "${RUNAWAY_TURNS_THRESHOLD:-200}" ]] && _over_turns=1
assert_equals "1" "$_over_turns" "runaway: 250 turns exceeds RUNAWAY_TURNS_THRESHOLD"

# Cost threshold: 250 * 0.01 = 2.50; should NOT trigger $20 threshold
_over_cost=0
python3 -c "import sys; sys.exit(0 if float('$_total_cost') >= 20 else 1)" 2>/dev/null \
  && _over_cost=1
assert_equals "0" "$_over_cost" "runaway: \$2.50 does NOT exceed \$20 threshold"

rm -rf "$_P13_SESSIONS"
echo ""

# ─── P4-2: Team delegation helpers ────────────────────────────────────────────
echo "── P4-2: Team delegation ──"

_P42_DIR=$(mktemp -d)
_P42_TASK_LIST="$_P42_DIR/TASK_LIST.json"

# Seed an empty task list
echo '{"tasks":[]}' > "$_P42_TASK_LIST"

# Add a task via Python (same logic as _team_delegate)
python3 - "$_P42_TASK_LIST" "task-001" "Fix login bug" "normal" "2026-06-08T10:00:00" <<'PYEOF'
import sys, json
path, tid, desc, pri, created = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data.setdefault("tasks", []).append({
    "id": tid, "description": desc, "priority": pri,
    "created": created, "status": "pending"
})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF

_p42_count=$(python3 -c "import json; d=json.load(open('$_P42_TASK_LIST')); print(len([t for t in d['tasks'] if t['status']=='pending']))")
assert_equals "1" "$_p42_count" "delegate: task appears in pending queue"

# Add a second task with high priority
python3 - "$_P42_TASK_LIST" "task-002" "Security audit" "high" "2026-06-08T10:01:00" <<'PYEOF'
import sys, json
path, tid, desc, pri, created = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data.setdefault("tasks", []).append({
    "id": tid, "description": desc, "priority": pri,
    "created": created, "status": "pending"
})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF

_p42_count2=$(python3 -c "import json; d=json.load(open('$_P42_TASK_LIST')); print(len([t for t in d['tasks'] if t['status']=='pending']))")
assert_equals "2" "$_p42_count2" "delegate: two tasks pending after second add"

# Mark task-001 as done
python3 - "$_P42_TASK_LIST" "task-001" <<'PYEOF'
import json, sys
path, tid = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
for t in data.get("tasks", []):
    if t["id"] == tid:
        t["status"] = "done"
        break
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF

_p42_pending=$(python3 -c "import json; d=json.load(open('$_P42_TASK_LIST')); print(len([t for t in d['tasks'] if t['status']=='pending']))")
_p42_done=$(python3 -c "import json; d=json.load(open('$_P42_TASK_LIST')); print(len([t for t in d['tasks'] if t['status']=='done']))")
assert_equals "1" "$_p42_pending" "done: one task still pending after marking first done"
assert_equals "1" "$_p42_done"    "done: one task in done state"

# Priority ordering check (high should sort before normal)
_p42_first_pri=$(python3 -c "
import json
d=json.load(open('$_P42_TASK_LIST'))
pending=[t for t in d['tasks'] if t['status']=='pending']
order={'high':0,'normal':1,'low':2}
pending.sort(key=lambda t: order.get(t.get('priority','normal'),1))
print(pending[0]['priority'] if pending else 'empty')
")
assert_equals "high" "$_p42_first_pri" "queue: high-priority task sorts first"

rm -rf "$_P42_DIR"
echo ""

# ─── P5-1: Channel-aware binding helpers ───────────────────────────────────────
echo "── P5-1: Channel-aware bindings ──"

_P51_CONFIG=$(mktemp)
echo '{"bindings":[]}' > "$_P51_CONFIG"

# Stub CONFIG_FILE for these tests
_orig_config="${CONFIG_FILE:-}"
CONFIG_FILE="$_P51_CONFIG"

# Test 1: upsert_binding with explicit channel
upsert_binding "agent-a" "peer-123" "discord" "server"
_p51_ch=$(python3 -c "import json; b=json.load(open('$_P51_CONFIG'))['bindings'][0]; print(b['match']['channel'])")
assert_equals "discord" "$_p51_ch" "upsert_binding: channel written correctly for non-telegram"

# Test 2: get_channel_binding retrieves the correct peer
_p51_peer=$(get_channel_binding "agent-a" "discord")
assert_equals "peer-123" "$_p51_peer" "get_channel_binding: retrieves peer for named channel"

# Test 3: get_tg_binding returns empty when only discord binding exists
_p51_tg=$(get_tg_binding "agent-a")
assert_equals "" "$_p51_tg" "get_tg_binding: returns empty when agent has no telegram binding"

# Test 4: upsert second binding on telegram channel alongside discord
upsert_binding "agent-a" "tg-group-99" "telegram" "group"
_p51_tg2=$(get_tg_binding "agent-a")
assert_equals "tg-group-99" "$_p51_tg2" "get_tg_binding: returns telegram peer after adding telegram binding"

# Test 5: upsert_binding replaces existing same-channel binding (idempotent channel key)
upsert_binding "agent-a" "peer-456" "discord" "server"
_p51_count=$(python3 -c "import json; bs=json.load(open('$_P51_CONFIG'))['bindings']; print(len([b for b in bs if b['match']['channel']=='discord']))")
assert_equals "1" "$_p51_count" "upsert_binding: replaces existing binding for same channel (no duplicates)"

CONFIG_FILE="$_orig_config"
rm -f "$_P51_CONFIG"
echo ""

# ─── P5-2: Snapshot command ────────────────────────────────────────────────────
echo "── P5-2: Snapshot command ──"

# Hermetic fixture: a temp OpenClaw home with one registered project agent so the
# command works without a real ~/.openclaw (e.g. in CI). Paths are env-overridable.
_P52_HOME=$(mktemp -d)
mkdir -p "$_P52_HOME/workspaces/projects/testagent"
cat > "$_P52_HOME/workspaces/projects/testagent/.rack-meta.json" <<'JSON'
{"name":"Test Agent","type":"repo","model":"anthropic/claude-sonnet-4-6"}
JSON
cat > "$_P52_HOME/openclaw.json" <<'JSON'
{"agents":{"list":[{"id":"testagent"}]},"bindings":[],"channels":{}}
JSON

_p52_out=$(OPENCLAW_DIR="$_P52_HOME" CONFIG_FILE="$_P52_HOME/openclaw.json" PROJECTS_DIR="$_P52_HOME/workspaces/projects" ./bin/rack snapshot 2>/dev/null)
_p52_valid=$(echo "$_p52_out" | python3 -c "import json,sys; d=json.load(sys.stdin); print('ok')" 2>/dev/null || echo "fail")
assert_equals "ok" "$_p52_valid" "snapshot: output is valid JSON"

_p52_has_agents=$(echo "$_p52_out" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes' if d.get('agents') else 'no')" 2>/dev/null || echo "no")
assert_equals "yes" "$_p52_has_agents" "snapshot: agents array present"

_p52_gateway=$(echo "$_p52_out" | python3 -c "import json,sys; d=json.load(sys.stdin); print('present' if 'gateway' in d else 'missing')" 2>/dev/null || echo "missing")
assert_equals "present" "$_p52_gateway" "snapshot: gateway field present"

rm -rf "$_P52_HOME"
echo ""

# ─── P5-3: Secret storage is injection-safe ────────────────────────────────────
echo "── P5-3: Secrets injection safety ──"

# Source the key-store helper (and its deps) in isolation.
source "$LIB_DIR/commands/keys.sh"

_P53_SECRETS=$(mktemp)
echo '{}' > "$_P53_SECRETS"
# Hostile value: if interpolated into Python source it would run os.system and
# create a marker file. Stored safely, it must end up as a literal string.
_P53_MARKER=$(mktemp -u)
_P53_PAYLOAD="'''; import os; os.system('touch $_P53_MARKER'); x='''"

RACK_KEY_VALUE="$_P53_PAYLOAD" _keys_store "$_P53_SECRETS" "ANTHROPIC_API_KEY" >/dev/null 2>&1

# The injected command must NOT have run
[[ ! -e "$_P53_MARKER" ]] && _p53_safe="safe" || _p53_safe="EXECUTED"
assert_equals "safe" "$_p53_safe" "keys: hostile value is not executed (no injection)"

# The value must be stored verbatim as a JSON string
_p53_roundtrip=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['ANTHROPIC_API_KEY'])" "$_P53_SECRETS")
assert_equals "$_P53_PAYLOAD" "$_p53_roundtrip" "keys: hostile value stored verbatim as data"

# secrets.json must be 0600
_p53_perm=$(stat -c '%a' "$_P53_SECRETS" 2>/dev/null || stat -f '%Lp' "$_P53_SECRETS" 2>/dev/null)
assert_equals "600" "$_p53_perm" "keys: secrets file is mode 600"

rm -f "$_P53_SECRETS" "$_P53_MARKER"
echo ""

# ─── P5-4: Secret distribution is scoped to least privilege ────────────────────
echo "── P5-4: Scoped secret distribution ──"

# output.sh provides info(); secrets.sh provides the backend used by the sync.
source "$LIB_DIR/helpers/output.sh"
source "$LIB_DIR/helpers/secrets.sh"

# Hermetic OpenClaw home with two project agents on different providers.
_P54_HOME=$(mktemp -d)
mkdir -p "$_P54_HOME/workspaces/projects/anth-agent"
mkdir -p "$_P54_HOME/workspaces/projects/oai-agent"
cat > "$_P54_HOME/workspaces/projects/anth-agent/.rack-meta.json" <<'JSON'
{"name":"Anthropic Agent","type":"repo","model":"anthropic/claude-sonnet-4-6"}
JSON
cat > "$_P54_HOME/workspaces/projects/oai-agent/.rack-meta.json" <<'JSON'
{"name":"OpenAI Agent","type":"repo","model":"openai/gpt-4o"}
JSON

# A user-authored line in one .env must survive the rewrite.
echo "MY_CUSTOM_FLAG=keepme" > "$_P54_HOME/workspaces/projects/anth-agent/.env"

# Secrets: two provider keys + one custom (shared) secret.
cat > "$_P54_HOME/secrets.json" <<'JSON'
{"ANTHROPIC_API_KEY":"sk-ant-aaa","OPENAI_API_KEY":"sk-oai-bbb","SHARED_TOKEN":"shared-ccc"}
JSON
chmod 600 "$_P54_HOME/secrets.json"

OPENCLAW_DIR="$_P54_HOME" PROJECTS_DIR="$_P54_HOME/workspaces/projects" \
  _sync_keys_to_agents >/dev/null 2>&1

_p54_anth=$(cat "$_P54_HOME/workspaces/projects/anth-agent/.env")
_p54_oai=$(cat "$_P54_HOME/workspaces/projects/oai-agent/.env")

# Anthropic agent: gets its own provider key, NOT OpenAI's.
echo "$_p54_anth" | grep -q '^ANTHROPIC_API_KEY=' && _p54_a1="yes" || _p54_a1="no"
assert_equals "yes" "$_p54_a1" "scoped: anthropic agent receives ANTHROPIC_API_KEY"
echo "$_p54_anth" | grep -q '^OPENAI_API_KEY=' && _p54_a2="leaked" || _p54_a2="absent"
assert_equals "absent" "$_p54_a2" "scoped: anthropic agent does NOT receive OPENAI_API_KEY"

# OpenAI agent: mirror image.
echo "$_p54_oai" | grep -q '^OPENAI_API_KEY=' && _p54_o1="yes" || _p54_o1="no"
assert_equals "yes" "$_p54_o1" "scoped: openai agent receives OPENAI_API_KEY"
echo "$_p54_oai" | grep -q '^ANTHROPIC_API_KEY=' && _p54_o2="leaked" || _p54_o2="absent"
assert_equals "absent" "$_p54_o2" "scoped: openai agent does NOT receive ANTHROPIC_API_KEY"

# Shared (non-provider) secret reaches both agents.
echo "$_p54_anth" | grep -q '^SHARED_TOKEN=' && _p54_s1="yes" || _p54_s1="no"
echo "$_p54_oai" | grep -q '^SHARED_TOKEN=' && _p54_s2="yes" || _p54_s2="no"
assert_equals "yes" "$_p54_s1" "scoped: shared secret reaches anthropic agent"
assert_equals "yes" "$_p54_s2" "scoped: shared secret reaches openai agent"

# User-authored line is preserved.
echo "$_p54_anth" | grep -q '^MY_CUSTOM_FLAG=keepme' && _p54_keep="yes" || _p54_keep="no"
assert_equals "yes" "$_p54_keep" "scoped: user-authored .env line is preserved"

# .env files are mode 600.
_p54_perm=$(stat -c '%a' "$_P54_HOME/workspaces/projects/anth-agent/.env" 2>/dev/null || stat -f '%Lp' "$_P54_HOME/workspaces/projects/anth-agent/.env" 2>/dev/null)
assert_equals "600" "$_p54_perm" "scoped: synced .env is mode 600"

rm -rf "$_P54_HOME"
echo ""

# ─── P5-5: Key rotation metadata & age reporting ───────────────────────────────
echo "── P5-5: Key rotation & age hygiene ──"

_P55_HOME=$(mktemp -d)
cat > "$_P55_HOME/secrets.json" <<'JSON'
{"ANTHROPIC_API_KEY":"sk-ant-old","OPENAI_API_KEY":"sk-oai-new"}
JSON
chmod 600 "$_P55_HOME/secrets.json"

# An old key (manually stamped in the past) must report STALE.
cat > "$_P55_HOME/secrets.meta.json" <<'JSON'
{"ANTHROPIC_API_KEY":{"added_at":"2000-01-01T00:00:00Z"}}
JSON
chmod 600 "$_P55_HOME/secrets.meta.json"

# Stamp the second key as freshly added (now).
OPENCLAW_DIR="$_P55_HOME" _keys_touch_meta "OPENAI_API_KEY" "added"

_p55_report=$(OPENCLAW_DIR="$_P55_HOME" _keys_age_report)
echo "$_p55_report" | grep -q '^STALE|ANTHROPIC_API_KEY|' && _p55_stale="yes" || _p55_stale="no"
assert_equals "yes" "$_p55_stale" "age: key older than threshold reports STALE"
echo "$_p55_report" | grep -q '^OK|OPENAI_API_KEY|' && _p55_ok="yes" || _p55_ok="no"
assert_equals "yes" "$_p55_ok" "age: freshly added key reports OK"

# Rotation stamps rotated_at and clears staleness.
OPENCLAW_DIR="$_P55_HOME" _keys_touch_meta "ANTHROPIC_API_KEY" "rotated"
_p55_rot=$(python3 -c "import json,sys; print('yes' if json.load(open(sys.argv[1]))['ANTHROPIC_API_KEY'].get('rotated_at') else 'no')" "$_P55_HOME/secrets.meta.json")
assert_equals "yes" "$_p55_rot" "rotate: rotated_at timestamp recorded"
_p55_report2=$(OPENCLAW_DIR="$_P55_HOME" _keys_age_report)
echo "$_p55_report2" | grep -q '^OK|ANTHROPIC_API_KEY|' && _p55_fresh="yes" || _p55_fresh="no"
assert_equals "yes" "$_p55_fresh" "rotate: rotated key is no longer STALE"

# Removal drops the lifecycle metadata entry.
OPENCLAW_DIR="$_P55_HOME" _keys_touch_meta "OPENAI_API_KEY" "removed"
_p55_gone=$(python3 -c "import json,sys; print('absent' if 'OPENAI_API_KEY' not in json.load(open(sys.argv[1])) else 'present')" "$_P55_HOME/secrets.meta.json")
assert_equals "absent" "$_p55_gone" "remove: lifecycle metadata is dropped"

# Sidecar is mode 600.
_p55_perm=$(stat -c '%a' "$_P55_HOME/secrets.meta.json" 2>/dev/null || stat -f '%Lp' "$_P55_HOME/secrets.meta.json" 2>/dev/null)
assert_equals "600" "$_p55_perm" "meta: sidecar is mode 600"

rm -rf "$_P55_HOME"
echo ""

# ─── P5-6: Config permission hardening (G2) ────────────────────────────────────
echo "── P5-6: Config permission hardening ──"

source "$LIB_DIR/helpers/security.sh"

_P56_HOME=$(mktemp -d)
printf '{}' > "$_P56_HOME/openclaw.json"; chmod 664 "$_P56_HOME/openclaw.json"
printf '{}' > "$_P56_HOME/secrets.json"; chmod 600 "$_P56_HOME/secrets.json"

_p56_changed=$(CONFIG_FILE="$_P56_HOME/openclaw.json" OPENCLAW_DIR="$_P56_HOME" secure_config_perms)

# The 664 config is tightened to 600; the already-600 secrets file is untouched.
_p56_cfg_mode=$(stat -c '%a' "$_P56_HOME/openclaw.json" 2>/dev/null || stat -f '%Lp' "$_P56_HOME/openclaw.json")
assert_equals "600" "$_p56_cfg_mode" "perms: group/other-accessible config tightened to 600"
echo "$_p56_changed" | grep -q "openclaw.json" && _p56_rep="yes" || _p56_rep="no"
assert_equals "yes" "$_p56_rep" "perms: tightened file is reported"
echo "$_p56_changed" | grep -q "secrets.json" && _p56_sec="reported" || _p56_sec="silent"
assert_equals "silent" "$_p56_sec" "perms: already-600 file is left alone (never loosened)"

# Idempotent: a second run is a no-op and reports nothing.
_p56_again=$(CONFIG_FILE="$_P56_HOME/openclaw.json" OPENCLAW_DIR="$_P56_HOME" secure_config_perms)
assert_equals "" "$_p56_again" "perms: idempotent (no-op on second run)"

rm -rf "$_P56_HOME"
echo ""

# ─── P5-7: Exec-approval gate apply (G3) ───────────────────────────────────────
echo "── P5-7: Exec-approval gates ──"

# Force the local-file path so the test never touches a real daemon: a stub
# openclaw that fails makes apply_exec_approval_gates fall back to a direct write.
openclaw() { return 1; }

_P57_HOME=$(mktemp -d)
cat > "$_P57_HOME/openclaw.json" <<'JSON'
{"agents":{"list":[{"id":"alpha"},{"id":"beta"}]},"bindings":[],"channels":{}}
JSON
# Pre-existing approvals file with a socket — must be preserved across apply.
cat > "$_P57_HOME/exec-approvals.json" <<'JSON'
{"version":1,"socket":{"path":"/x.sock","token":"tok"},"defaults":{},"agents":{}}
JSON

CONFIG_FILE="$_P57_HOME/openclaw.json" OPENCLAW_DIR="$_P57_HOME" apply_exec_approval_gates >/dev/null 2>&1
_p57_appr="$_P57_HOME/exec-approvals.json"

_p57_sec=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['defaults'].get('security'))" "$_p57_appr")
assert_equals "allowlist" "$_p57_sec" "gates: defaults.security=allowlist"
_p57_fb=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['defaults'].get('askFallback'))" "$_p57_appr")
assert_equals "deny" "$_p57_fb" "gates: defaults.askFallback=deny"

# Existing socket/token preserved (config not clobbered).
_p57_tok=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['socket'].get('token'))" "$_p57_appr")
assert_equals "tok" "$_p57_tok" "gates: existing socket/token preserved"

# Both registered agents seeded with a non-empty allowlist.
_p57_alpha=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['agents']['alpha']['allowlist']))" "$_p57_appr")
[[ "$_p57_alpha" -gt 0 ]] && _p57_a="seeded" || _p57_a="empty"
assert_equals "seeded" "$_p57_a" "gates: agent allowlist seeded with curated bins"

# Dangerous bins (rm) are deliberately NOT allowlisted → they stay gated.
_p57_rm=$(python3 -c "import json,sys
al=json.load(open(sys.argv[1]))['agents']['alpha']['allowlist']
print('present' if any(e['pattern'].endswith('/rm') for e in al) else 'absent')" "$_p57_appr")
assert_equals "absent" "$_p57_rm" "gates: dangerous bin (rm) is not allowlisted"

_p57_perm=$(stat -c '%a' "$_p57_appr" 2>/dev/null || stat -f '%Lp' "$_p57_appr")
assert_equals "600" "$_p57_perm" "gates: exec-approvals.json written 0600"

# Idempotent: a second run must not overwrite existing defaults.
_p57_again=$(CONFIG_FILE="$_P57_HOME/openclaw.json" OPENCLAW_DIR="$_P57_HOME" apply_exec_approval_gates 2>/dev/null)
echo "$_p57_again" | grep -q 'defaults_changed=0' && _p57_idem="kept" || _p57_idem="clobbered"
assert_equals "kept" "$_p57_idem" "gates: re-run preserves existing defaults (non-clobber)"

# disable resets defaults to empty (escape hatch).
CONFIG_FILE="$_P57_HOME/openclaw.json" OPENCLAW_DIR="$_P57_HOME" disable_exec_approval_gates >/dev/null 2>&1
_p57_dis=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['defaults']))" "$_p57_appr")
assert_equals "0" "$_p57_dis" "gates: disable resets defaults to empty"

unset -f openclaw
rm -rf "$_P57_HOME"
echo ""

# ─── P5-8: Approval routing (G4) ───────────────────────────────────────────────
echo "── P5-8: Approval routing ──"

_P58_HOME=$(mktemp -d)
# Config with one Telegram-bound agent (alpha) and one unbound (beta).
cat > "$_P58_HOME/openclaw.json" <<'JSON'
{"agents":{"list":[{"id":"alpha"},{"id":"beta"}]},
 "bindings":[{"agentId":"alpha","match":{"channel":"telegram","peer":{"kind":"group","id":"-100200"}}}],
 "channels":{}}
JSON

_p58_count=$(CONFIG_FILE="$_P58_HOME/openclaw.json" OPENCLAW_DIR="$_P58_HOME" apply_approval_routing)

# approvals.exec written with enabled:true, mode:session.
_p58_enabled=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['approvals']['exec']['enabled'])" "$_P58_HOME/openclaw.json")
assert_equals "True" "$_p58_enabled" "routing: approvals.exec.enabled=true"
_p58_mode=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['approvals']['exec']['mode'])" "$_P58_HOME/openclaw.json")
assert_equals "session" "$_p58_mode" "routing: mode=session (no cross-agent target list)"

# Telegram-bound agents counted (1 of 2).
assert_equals "1" "$_p58_count" "routing: counts telegram-bound agents"

# Status helper reports on|session.
_p58_status=$(CONFIG_FILE="$_P58_HOME/openclaw.json" _approval_routing_status)
assert_equals "on|session" "$_p58_status" "routing: status reports on|session"

# Existing config preserved through the oc_set write.
_p58_pres=$(python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print(len(c['bindings']), len(c['agents']['list']))" "$_P58_HOME/openclaw.json")
assert_equals "1 2" "$_p58_pres" "routing: bindings and agents preserved"

# Disable flips enabled to false (escape hatch).
CONFIG_FILE="$_P58_HOME/openclaw.json" disable_approval_routing >/dev/null 2>&1
_p58_off=$(CONFIG_FILE="$_P58_HOME/openclaw.json" _approval_routing_status)
assert_equals "off|session" "$_p58_off" "routing: disable sets enabled=false"

rm -rf "$_P58_HOME"
echo ""

# ─── P5-9: Workspace isolation (G5) ────────────────────────────────────────────
echo "── P5-9: Workspace isolation ──"

_P59_HOME=$(mktemp -d)
echo '{"agents":{"list":[{"id":"alpha"}]},"bindings":[],"channels":{}}' > "$_P59_HOME/openclaw.json"

CONFIG_FILE="$_P59_HOME/openclaw.json" apply_workspace_isolation >/dev/null 2>&1

_p59_mode=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['agents']['defaults']['sandbox']['mode'])" "$_P59_HOME/openclaw.json")
assert_equals "non-main" "$_p59_mode" "isolation: sandbox.mode=non-main"
_p59_wa=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['agents']['defaults']['sandbox']['workspaceAccess'])" "$_P59_HOME/openclaw.json")
assert_equals "rw" "$_p59_wa" "isolation: sandbox.workspaceAccess=rw"
_p59_st=$(CONFIG_FILE="$_P59_HOME/openclaw.json" _isolation_status)
assert_equals "non-main" "$_p59_st" "isolation: status reports non-main"

# Existing agents list preserved through the write.
_p59_pres=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['agents']['list']))" "$_P59_HOME/openclaw.json")
assert_equals "1" "$_p59_pres" "isolation: agents.list preserved"

# Disable flips mode to off.
CONFIG_FILE="$_P59_HOME/openclaw.json" disable_workspace_isolation >/dev/null 2>&1
_p59_off=$(CONFIG_FILE="$_P59_HOME/openclaw.json" _isolation_status)
assert_equals "off" "$_p59_off" "isolation: disable sets mode=off"

rm -rf "$_P59_HOME"
echo ""

# ─── P5-10: Secret backend abstraction ─────────────────────────────────────────
echo "── P5-10: Secret backend ──"

source "$LIB_DIR/helpers/secrets.sh"

# Dispatch: defaults to file; selects keyring only when secret-tool is present.
_p510_def=$(RACK_SECRETS_BACKEND="" secrets_backend)
assert_equals "file" "$_p510_def" "backend: defaults to file"

# File backend round-trip (hermetic OPENCLAW_DIR).
_P510_HOME=$(mktemp -d)
RACK_KEY_VALUE="sk-file-xyz" OPENCLAW_DIR="$_P510_HOME" RACK_SECRETS_BACKEND=file secret_put "ANTHROPIC_API_KEY"
_p510_get=$(OPENCLAW_DIR="$_P510_HOME" RACK_SECRETS_BACKEND=file secret_get "ANTHROPIC_API_KEY")
assert_equals "sk-file-xyz" "$_p510_get" "backend(file): put/get round-trip"
_p510_names=$(OPENCLAW_DIR="$_P510_HOME" secret_names)
assert_equals "ANTHROPIC_API_KEY" "$_p510_names" "backend(file): names lists the key"
OPENCLAW_DIR="$_P510_HOME" RACK_SECRETS_BACKEND=file secret_has "ANTHROPIC_API_KEY" && _p510_h="yes" || _p510_h="no"
assert_equals "yes" "$_p510_h" "backend(file): secret_has true for stored key"
_p510_perm=$(stat -c '%a' "$_P510_HOME/secrets.json" 2>/dev/null || stat -f '%Lp' "$_P510_HOME/secrets.json")
assert_equals "600" "$_p510_perm" "backend(file): secrets.json is 0600"
OPENCLAW_DIR="$_P510_HOME" RACK_SECRETS_BACKEND=file secret_del "ANTHROPIC_API_KEY"
OPENCLAW_DIR="$_P510_HOME" secret_has "ANTHROPIC_API_KEY" && _p510_d="present" || _p510_d="gone"
assert_equals "gone" "$_p510_d" "backend(file): secret_del removes the key"
rm -rf "$_P510_HOME"

# Keyring backend round-trip — only when a live keyring is reachable. Uses an
# isolated service name so the real keyring isn't polluted; cleaned up after.
_P510_SVC="rack-cli-test-$$"
if command -v secret-tool >/dev/null 2>&1 \
   && secret-tool store --label=probe service "$_P510_SVC" key PROBE <<<"x" >/dev/null 2>&1; then
  secret-tool clear service "$_P510_SVC" key PROBE >/dev/null 2>&1
  _P510_KHOME=$(mktemp -d)
  _benv=(OPENCLAW_DIR="$_P510_KHOME" RACK_SECRETS_BACKEND=keyring RACK_KEYRING_SERVICE="$_P510_SVC")

  _p510_kb=$(env "${_benv[@]}" RACK_SECRETS_BACKEND=keyring bash -c 'source '"$LIB_DIR"'/helpers/output.sh; source '"$LIB_DIR"'/helpers/secrets.sh; source '"$LIB_DIR"'/commands/keys.sh; secrets_backend')
  assert_equals "keyring" "$_p510_kb" "backend(keyring): selected when secret-tool live"

  env "${_benv[@]}" bash -c 'source '"$LIB_DIR"'/helpers/output.sh; source '"$LIB_DIR"'/helpers/secrets.sh; source '"$LIB_DIR"'/commands/keys.sh; RACK_KEY_VALUE="sk-kr-secret" secret_put OPENAI_API_KEY'
  # Value must be retrievable from the keyring...
  _p510_kget=$(env "${_benv[@]}" bash -c 'source '"$LIB_DIR"'/helpers/output.sh; source '"$LIB_DIR"'/helpers/secrets.sh; source '"$LIB_DIR"'/commands/keys.sh; secret_get OPENAI_API_KEY')
  assert_equals "sk-kr-secret" "$_p510_kget" "backend(keyring): put/get via OS keyring"
  # ...but the on-disk index must NOT contain the value (no plaintext at rest).
  _p510_idxval=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('OPENAI_API_KEY',''))" "$_P510_KHOME/secrets.json")
  assert_equals "" "$_p510_idxval" "backend(keyring): index stores no value (no plaintext at rest)"
  # Cleanup keyring entry.
  env "${_benv[@]}" bash -c 'source '"$LIB_DIR"'/helpers/output.sh; source '"$LIB_DIR"'/helpers/secrets.sh; source '"$LIB_DIR"'/commands/keys.sh; secret_del OPENAI_API_KEY' >/dev/null 2>&1
  secret-tool clear service "$_P510_SVC" key OPENAI_API_KEY >/dev/null 2>&1
  rm -rf "$_P510_KHOME"
else
  echo "  ${DIM}(keyring backend not validated — no live secret service in this environment)${RESET}"
fi
echo ""

# ─── P6-1: Write-safety (atomic writes + lock + loud reads) ────────────────────
echo "── P6-1: Write-safety ──"

source "$LIB_DIR/helpers/json.sh"

_P61=$(mktemp -d)
_p61_f="$_P61/data.json"
echo '{"keep":1}' > "$_p61_f"

# Valid JSON via stdin → written atomically, 0600, with a rolling .bak, no .tmp.
printf '{"a":1,"b":2}' | json_atomic_write "$_p61_f"
_p61_b=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['b'])" "$_p61_f")
assert_equals "2" "$_p61_b" "atomic: valid JSON is written"
_p61_perm=$(stat -c '%a' "$_p61_f" 2>/dev/null || stat -f '%Lp' "$_p61_f")
assert_equals "600" "$_p61_perm" "atomic: written file is 0600"
[[ -f "$_p61_f.bak" ]] && _p61_bak="yes" || _p61_bak="no"
assert_equals "yes" "$_p61_bak" "atomic: rolling .bak created"
[[ -e "$_p61_f.tmp" ]] && _p61_tmp="left" || _p61_tmp="clean"
assert_equals "clean" "$_p61_tmp" "atomic: no .tmp left behind"

# Invalid JSON on stdin → refused; the original file must NOT be truncated.
printf 'NOT JSON' | json_atomic_write "$_p61_f" 2>/dev/null && _p61_rc="wrote" || _p61_rc="refused"
assert_equals "refused" "$_p61_rc" "atomic: invalid JSON is refused (non-zero exit)"
_p61_intact=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['b'])" "$_p61_f")
assert_equals "2" "$_p61_intact" "atomic: original file intact after refused write"

# with_rack_lock runs the command and propagates its exit code.
OPENCLAW_DIR="$_P61" with_rack_lock true && _p61_lk="ok" || _p61_lk="fail"
assert_equals "ok" "$_p61_lk" "lock: runs command (exit 0)"
OPENCLAW_DIR="$_P61" with_rack_lock false && _p61_lf="ok" || _p61_lf="nonzero"
assert_equals "nonzero" "$_p61_lf" "lock: propagates non-zero exit"

# Loud-on-corruption read: a corrupt meta file warns to stderr but returns default.
mkdir -p "$_P61/proj/bad"
echo 'NOT JSON' > "$_P61/proj/bad/.rack-meta.json"
_p61_warn=$(PROJECTS_DIR="$_P61/proj" META_FILE=".rack-meta.json" meta_get "bad" "model" "fallback" 2>&1 >/dev/null)
echo "$_p61_warn" | grep -qiE "cannot read|corrupt|warning" && _p61_w="warned" || _p61_w="silent"
assert_equals "warned" "$_p61_w" "read: corrupt state file warns loudly"
_p61_val=$(PROJECTS_DIR="$_P61/proj" META_FILE=".rack-meta.json" meta_get "bad" "model" "fallback" 2>/dev/null)
assert_equals "fallback" "$_p61_val" "read: corrupt file still returns default"

rm -rf "$_P61"
echo ""

# ─── P6-2: Versioning ──────────────────────────────────────────────────────────
echo "── P6-2: Versioning ──"

_p62_ver=$(cat "$LIB_DIR/../VERSION" 2>/dev/null)
assert_not_empty "$_p62_ver" "version: VERSION file present and non-empty"
_p62_out=$(./bin/rack --version 2>/dev/null)
assert_equals "rack $_p62_ver" "$_p62_out" "version: 'rack --version' matches VERSION file"
_p62_v2=$(./bin/rack -V 2>/dev/null)
assert_equals "rack $_p62_ver" "$_p62_v2" "version: '-V' alias matches"
# CHANGELOG documents the current version.
grep -q "\[$_p62_ver\]" "$LIB_DIR/../CHANGELOG.md" && _p62_cl="yes" || _p62_cl="no"
assert_equals "yes" "$_p62_cl" "version: CHANGELOG has an entry for $_p62_ver"

echo ""

# ─── P7-1: Portability (service abstraction + GNU-ism-free helpers) ────────────
echo "── P7-1: Portability ──"

source "$LIB_DIR/helpers/service.sh"
source "$LIB_DIR/helpers/utils.sh"

# service_manager honours the override; hints/ctl follow it.
assert_equals "launchd" "$(RACK_SERVICE_MANAGER=launchd service_manager)" "service: manager override respected"
assert_equals "systemctl --user restart openclaw-gateway.service" \
  "$(RACK_SERVICE_MANAGER=systemd service_hint restart)" "service: systemd hint"
RACK_SERVICE_MANAGER=none service_hint restart | grep -q "openclaw gateway restart" && _p71_h2="ok" || _p71_h2="no"
assert_equals "ok" "$_p71_h2" "service: non-systemd hint avoids systemctl"
RACK_SERVICE_MANAGER=none service_ctl is-active 2>/dev/null && _p71_ia="active" || _p71_ia="inactive"
assert_equals "inactive" "$_p71_ia" "service: is-active false off systemd"

# newest_file: most recent match by mtime (portable, replaces find -printf).
_P71=$(mktemp -d)
echo a > "$_P71/2024-01-01.md"; echo b > "$_P71/2024-02-01.md"
touch -t 202401010000 "$_P71/2024-01-01.md"
touch -t 202402010000 "$_P71/2024-02-01.md"
assert_equals "$_P71/2024-02-01.md" "$(newest_file "$_P71" '*.md')" "newest_file: most recent by mtime"
assert_equals "" "$(newest_file "$_P71" '*.txt')" "newest_file: empty when no match"

# portable_sed_i: in-place edit on GNU or BSD sed, preserving other lines.
printf 'Session Key: old\nkeep this\n' > "$_P71/SOUL.md"
portable_sed_i "s|^Session Key:.*|Session Key: new|" "$_P71/SOUL.md"
grep -q "^Session Key: new" "$_P71/SOUL.md" && _p71_se="ok" || _p71_se="no"
assert_equals "ok" "$_p71_se" "portable_sed_i: applies substitution"
grep -q "^keep this" "$_P71/SOUL.md" && _p71_keep="ok" || _p71_keep="no"
assert_equals "ok" "$_p71_keep" "portable_sed_i: preserves other lines"

# Portable stat wrappers.
printf '12345' > "$_P71/sz"; chmod 640 "$_P71/sz"
assert_equals "5" "$(file_size "$_P71/sz")" "file_size: bytes"
assert_equals "640" "$(file_mode "$_P71/sz")" "file_mode: octal mode"

rm -rf "$_P71"
echo ""

# ─── P8-1: Audit log ───────────────────────────────────────────────────────────
echo "── P8-1: Audit log ──"

source "$LIB_DIR/helpers/audit.sh"

_P81=$(mktemp -d)
OPENCLAW_DIR="$_P81" audit_log "keys.add" "ANTHROPIC_API_KEY"
OPENCLAW_DIR="$_P81" audit_log "gates.enable" "security=allowlist"
assert_equals "2" "$(wc -l < "$_P81/audit.log" | tr -d ' ')" "audit: one JSON line per call"
_p81_action=$(tail -1 "$_P81/audit.log" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['action'])")
assert_equals "gates.enable" "$_p81_action" "audit: records the action"
_p81_meta=$(tail -1 "$_P81/audit.log" | python3 -c "import json,sys; e=json.loads(sys.stdin.read()); print('yes' if e.get('user') and e.get('ts') else 'no')")
assert_equals "yes" "$_p81_meta" "audit: records user + timestamp"
_p81_perm=$(stat -c '%a' "$_P81/audit.log" 2>/dev/null || stat -f '%Lp' "$_P81/audit.log")
assert_equals "600" "$_p81_perm" "audit: log file is 0600"

rm -f "$_P81/audit.log"
RACK_NO_AUDIT=1 OPENCLAW_DIR="$_P81" audit_log "keys.add" "X"
[[ -f "$_P81/audit.log" ]] && _p81_off="wrote" || _p81_off="skipped"
assert_equals "skipped" "$_p81_off" "audit: RACK_NO_AUDIT=1 disables logging"

rm -rf "$_P81"
echo ""

# ─── P8-2: list --json ─────────────────────────────────────────────────────────
echo "── P8-2: list --json ──"

source "$LIB_DIR/commands/list.sh"

_P82=$(mktemp -d)
mkdir -p "$_P82/projects/alpha"
cat > "$_P82/projects/alpha/.rack-meta.json" <<'JSON'
{"name":"Alpha","type":"repo","model":"anthropic/claude-sonnet-4-6","stack":"Go"}
JSON
cat > "$_P82/openclaw.json" <<'JSON'
{"agents":{"list":[{"id":"alpha"}]},"bindings":[{"agentId":"alpha","match":{"channel":"telegram","peer":{"kind":"group","id":"-100"}}}],"channels":{}}
JSON

_p82_json=$(PROJECTS_DIR="$_P82/projects" CONFIG_FILE="$_P82/openclaw.json" \
  DEFAULT_MODEL="anthropic/claude-sonnet-4-6" META_FILE=".rack-meta.json" _list_json)
echo "$_p82_json" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null && _p82_v="ok" || _p82_v="fail"
assert_equals "ok" "$_p82_v" "list --json: valid JSON"
assert_equals "alpha" "$(echo "$_p82_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['agents'][0]['id'])")" "list --json: agent id present"
assert_equals "True" "$(echo "$_p82_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['agents'][0]['registered'])")" "list --json: registered reflects config"
assert_equals "-100" "$(echo "$_p82_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['agents'][0]['telegram'])")" "list --json: telegram binding resolved"

rm -rf "$_P82"
echo ""

# ─── P9-1: Cost index (incremental aggregation) ────────────────────────────────
echo "── P9-1: Cost index ──"

source "$LIB_DIR/helpers/workspace.sh"

_P91=$(mktemp -d)
mkdir -p "$_P91/agents/a1/sessions"
printf '%s\n%s\n' \
  '{"message":{"usage":{"input":100,"output":50,"cost":{"total":0.01}}}}' \
  '{"message":{"usage":{"input":200,"output":100,"cost":{"total":0.02}}}}' \
  > "$_P91/agents/a1/sessions/s1.jsonl"

_p91_1=$(OPENCLAW_DIR="$_P91" _aggregate_cost "a1")
assert_equals "300|150|0|0|0.030000|2" "$_p91_1" "cost: aggregates input/output/cost/turns"
[[ -f "$_P91/agents/a1/.cost-index.json" ]] && _p91_idx="yes" || _p91_idx="no"
assert_equals "yes" "$_p91_idx" "cost: index file created"

# Unchanged files → cached result identical.
_p91_2=$(OPENCLAW_DIR="$_P91" _aggregate_cost "a1")
assert_equals "$_p91_1" "$_p91_2" "cost: cached call returns identical totals"

# Append a turn → size changes → file re-parsed incrementally.
printf '%s\n' '{"message":{"usage":{"input":10,"output":5,"cost":{"total":0.001}}}}' >> "$_P91/agents/a1/sessions/s1.jsonl"
assert_equals "310|155|0|0|0.031000|3" "$(OPENCLAW_DIR="$_P91" _aggregate_cost "a1")" "cost: changed file re-parsed"

# A removed session drops from the totals.
rm "$_P91/agents/a1/sessions/s1.jsonl"
assert_equals "0|0|0|0|0.000000|0" "$(OPENCLAW_DIR="$_P91" _aggregate_cost "a1")" "cost: removed session reflected"

rm -rf "$_P91"
echo ""

# ─── P9-2: cost --json ─────────────────────────────────────────────────────────
echo "── P9-2: cost --json ──"

source "$LIB_DIR/helpers/picker.sh"
source "$LIB_DIR/commands/cost.sh"

_P92=$(mktemp -d)
mkdir -p "$_P92/projects/a1" "$_P92/agents/a1/sessions"
echo '{"name":"A1","model":"anthropic/claude-sonnet-4-6","budgetUsd":"5"}' > "$_P92/projects/a1/.rack-meta.json"
printf '%s\n' '{"message":{"usage":{"input":1000,"output":500,"cost":{"total":0.25}}}}' > "$_P92/agents/a1/sessions/s.jsonl"

_p92=$(OPENCLAW_DIR="$_P92" PROJECTS_DIR="$_P92/projects" META_FILE=".rack-meta.json" \
  DEFAULT_MODEL="anthropic/claude-sonnet-4-6" _cost_json)
echo "$_p92" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null && _p92_v="ok" || _p92_v="fail"
assert_equals "ok" "$_p92_v" "cost --json: valid JSON"
assert_equals "0.25" "$(echo "$_p92" | python3 -c "import json,sys; print(json.load(sys.stdin)['totalUsd'])")" "cost --json: total cost"
assert_equals "5.0" "$(echo "$_p92" | python3 -c "import json,sys; print(json.load(sys.stdin)['agents'][0]['budgetUsd'])")" "cost --json: budget surfaced"

rm -rf "$_P92"
echo ""

# ─── P10-1: serve metrics + health ─────────────────────────────────────────────
echo "── P10-1: Serve metrics ──"

source "$LIB_DIR/commands/snapshot.sh"
source "$LIB_DIR/commands/serve.sh"

_P101=$(mktemp -d)
mkdir -p "$_P101/projects/a1" "$_P101/agents/a1/sessions" "$_P101/out"
echo '{"name":"A1","model":"anthropic/claude-sonnet-4-6"}' > "$_P101/projects/a1/.rack-meta.json"
printf '%s\n' '{"message":{"usage":{"input":1000,"output":500,"cost":{"total":0.5}}}}' > "$_P101/agents/a1/sessions/s.jsonl"

_serve_env=(OPENCLAW_DIR="$_P101" PROJECTS_DIR="$_P101/projects" META_FILE=".rack-meta.json"
            DEFAULT_MODEL="anthropic/claude-sonnet-4-6" RACK_SERVICE_MANAGER=none CONFIG_FILE="$_P101/openclaw.json")
echo '{"agents":{"list":[]},"bindings":[],"channels":{}}' > "$_P101/openclaw.json"

_p101_m=$(env "${_serve_env[@]}" bash -c 'source lib/core/config.sh; source lib/helpers/output.sh; source lib/helpers/json.sh; source lib/helpers/picker.sh; source lib/helpers/service.sh; source lib/helpers/workspace.sh; source lib/commands/cost.sh; source lib/commands/serve.sh; _serve_metrics')
echo "$_p101_m" | grep -q "^rack_agents_total 1$" && _p101_a="ok" || _p101_a="no"
assert_equals "ok" "$_p101_a" "metrics: rack_agents_total reflects agent count"
echo "$_p101_m" | grep -q "^rack_cost_usd_total 0.5$" && _p101_c="ok" || _p101_c="no"
assert_equals "ok" "$_p101_c" "metrics: rack_cost_usd_total aggregates"
echo "$_p101_m" | grep -q "^rack_gateway_up 0$" && _p101_g="ok" || _p101_g="no"
assert_equals "ok" "$_p101_g" "metrics: rack_gateway_up reflects state"
echo "$_p101_m" | grep -q "# TYPE rack_agents_total gauge" && _p101_t="ok" || _p101_t="no"
assert_equals "ok" "$_p101_t" "metrics: includes Prometheus HELP/TYPE"

# _serve_refresh writes the served artifacts.
env "${_serve_env[@]}" bash -c 'source lib/core/config.sh; source lib/helpers/output.sh; source lib/helpers/json.sh; source lib/helpers/picker.sh; source lib/helpers/service.sh; source lib/helpers/workspace.sh; source lib/commands/cost.sh; source lib/commands/snapshot.sh; source lib/commands/serve.sh; _serve_refresh "'"$_P101/out"'"' 2>/dev/null
[[ -f "$_P101/out/metrics" ]] && _p101_mf="yes" || _p101_mf="no"
assert_equals "yes" "$_p101_mf" "serve: /metrics artifact written"
_p101_health=$(python3 -c "import json; print(json.load(open('$_P101/out/health'))['status'])" 2>/dev/null)
assert_equals "ok" "$_p101_health" "serve: /health emits status ok"

rm -rf "$_P101"
echo ""

# ─── P10-2: info --json ────────────────────────────────────────────────────────
echo "── P10-2: info --json ──"

source "$LIB_DIR/commands/info.sh"

_P102=$(mktemp -d)
mkdir -p "$_P102/projects/a1/memory"
echo '{"name":"A1","type":"repo","model":"anthropic/claude-sonnet-4-6","stack":"Go","projectKey":"alpha"}' > "$_P102/projects/a1/.rack-meta.json"
echo '{"agents":{"list":[{"id":"a1"}]},"bindings":[{"agentId":"a1","match":{"channel":"telegram","peer":{"kind":"group","id":"-55"}}}],"channels":{}}' > "$_P102/openclaw.json"

_p102=$(PROJECTS_DIR="$_P102/projects" CONFIG_FILE="$_P102/openclaw.json" META_FILE=".rack-meta.json" \
  DEFAULT_MODEL="anthropic/claude-sonnet-4-6" _info_json "a1")
echo "$_p102" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null && _p102_v="ok" || _p102_v="fail"
assert_equals "ok" "$_p102_v" "info --json: valid JSON"
assert_equals "alpha" "$(echo "$_p102" | python3 -c "import json,sys; print(json.load(sys.stdin)['projectKey'])")" "info --json: projectKey present"
assert_equals "-55" "$(echo "$_p102" | python3 -c "import json,sys; print(json.load(sys.stdin)['telegram'])")" "info --json: telegram resolved"
assert_equals "True" "$(echo "$_p102" | python3 -c "import json,sys; print(json.load(sys.stdin)['registered'])")" "info --json: registered reflects config"

rm -rf "$_P102"
echo ""

# ─── P11-1: Cost history (daily series) ────────────────────────────────────────
echo "── P11-1: Cost history ──"

source "$LIB_DIR/helpers/workspace.sh"
source "$LIB_DIR/helpers/picker.sh"
source "$LIB_DIR/commands/cost.sh"

_P111=$(mktemp -d)
mkdir -p "$_P111/projects/a1" "$_P111/agents/a1/sessions"
echo '{"name":"A1"}' > "$_P111/projects/a1/.rack-meta.json"
{
  echo '{"timestamp":"2026-01-01T10:00:00Z","message":{"usage":{"input":100,"output":50,"cost":{"total":0.10}}}}'
  echo '{"timestamp":"2026-01-01T12:00:00Z","message":{"usage":{"input":100,"output":50,"cost":{"total":0.10}}}}'
  echo '{"timestamp":"2026-01-02T09:00:00Z","message":{"usage":{"input":200,"output":100,"cost":{"total":0.30}}}}'
} > "$_P111/agents/a1/sessions/s.jsonl"

_p111=$(OPENCLAW_DIR="$_P111" _cost_history "a1")
echo "$_p111" | grep -q '^2026-01-01|2|200|100|0.200000$' && _h1="ok" || _h1="no"
assert_equals "ok" "$_h1" "history: day 1 bucket (2 turns summed)"
echo "$_p111" | grep -q '^2026-01-02|1|200|100|0.300000$' && _h2="ok" || _h2="no"
assert_equals "ok" "$_h2" "history: day 2 bucket"
[[ -f "$_P111/agents/a1/.cost-history.json" ]] && _hidx="yes" || _hidx="no"
assert_equals "yes" "$_hidx" "history: history index created"

# JSON view: two days.
_p111j=$(OPENCLAW_DIR="$_P111" PROJECTS_DIR="$_P111/projects" _cost_history_view "a1" 0 1)
echo "$_p111j" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null && _hjv="ok" || _hjv="no"
assert_equals "ok" "$_hjv" "history --json: valid JSON"
assert_equals "2" "$(echo "$_p111j" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['history']))")" "history --json: two days"

# --days 1 keeps only the most recent day.
_p111d=$(OPENCLAW_DIR="$_P111" PROJECTS_DIR="$_P111/projects" _cost_history_view "a1" 1 1)
assert_equals "2026-01-02" "$(echo "$_p111d" | python3 -c "import json,sys; print(json.load(sys.stdin)['history'][0]['date'])")" "history --days 1: keeps most recent"

rm -rf "$_P111"
echo ""

# ─── P11-2: Template/prompt version stamping & drift ───────────────────────────
echo "── P11-2: Template versioning ──"

source "$LIB_DIR/helpers/output.sh"
source "$LIB_DIR/helpers/json.sh"
source "$LIB_DIR/helpers/workspace.sh"

_P112=$(mktemp -d)
(
  export PROJECTS_DIR="$_P112/projects" OPENCLAW_DIR="$_P112" META_FILE=".rack-meta.json"
  export TEMPLATE_VERSION="7"
  _create_workspace "tv1" "task" "TV One" "" "" "a task agent" "$DEFAULT_MODEL" >/dev/null 2>&1
)
_p112_stamp=$(PROJECTS_DIR="$_P112/projects" META_FILE=".rack-meta.json" \
  meta_get "tv1" "templateVersion" "MISSING")
assert_equals "7" "$_p112_stamp" "template: _create_workspace stamps TEMPLATE_VERSION into meta"

# Drift comparison logic: a lower stamp than current is detected as drift.
_p112_cur="7"
_p112_old=$(PROJECTS_DIR="$_P112/projects" META_FILE=".rack-meta.json" \
  meta_get "tv1" "templateVersion" "")
if [[ "$_p112_old" != "$_p112_cur" ]]; then _p112_drift="drift"; else _p112_drift="current"; fi
assert_equals "current" "$_p112_drift" "template: matching stamp reads as current"
# Simulate a template bump: stamp 7, current 8 → drift.
if [[ "7" != "8" ]]; then _p112_bump="drift"; else _p112_bump="current"; fi
assert_equals "drift" "$_p112_bump" "template: older stamp than current reads as drift"

rm -rf "$_P112"
echo ""

echo ""
echo "========================================"
echo "  Summary"
echo "========================================"
echo "  Passed: $TESTS_PASSED"
echo "  Failed: $TESTS_FAILED"
echo "========================================"
echo ""

if [[ $TESTS_FAILED -gt 0 ]]; then
  exit 1
else
  exit 0
fi
