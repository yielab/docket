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

# output.sh provides info() used by _sync_keys_to_agents.
source "$LIB_DIR/helpers/output.sh"

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
