#!/usr/bin/env bash
# drift.sh — role success-rate drift detection (D1–D3).
#
# Compares the rolling METRICS_WINDOW success rate for each agent_role
# against the trailing BASELINE_WINDOW baseline. If current < baseline -
# DRIFT_THRESHOLD, emits a drift_alert trace event and notifies via Telegram.
# Rate-limited to one alert per role per DRIFT_COOLDOWN seconds (D3).
# Aborted sessions count against success rate (D-6 decision).

_DRIFT_STATE_FILE="${DOCKET_HOME:-$HOME/.openclaw}/drift-state.json"

# drift_check_role <role> [project_filter]
# Computes current and baseline rates; emits alert when threshold crossed.
drift_check_role() {
  local role="$1" project_filter="${2:-}"
  [[ -d "$TRACES_DIR" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  DOCKET_DRIFT_ROLE="$role" \
  DOCKET_DRIFT_PROJECT="$project_filter" \
  DOCKET_TRACES_DIR="$TRACES_DIR" \
  DOCKET_METRICS_WINDOW="$METRICS_WINDOW" \
  DOCKET_BASELINE_WINDOW="$BASELINE_WINDOW" \
  DOCKET_DRIFT_THRESHOLD="$DRIFT_THRESHOLD" \
  DOCKET_DRIFT_STATE_FILE="$_DRIFT_STATE_FILE" \
  DOCKET_DRIFT_COOLDOWN="$DRIFT_COOLDOWN" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, glob, time, datetime

role         = os.environ["DOCKET_DRIFT_ROLE"]
proj_filter  = os.environ.get("DOCKET_DRIFT_PROJECT", "")
traces_dir   = os.environ["DOCKET_TRACES_DIR"]
window       = int(os.environ.get("DOCKET_METRICS_WINDOW", "50"))
baseline_win = int(os.environ.get("DOCKET_BASELINE_WINDOW", "100"))
threshold    = float(os.environ.get("DOCKET_DRIFT_THRESHOLD", "15"))
state_file   = os.environ["DOCKET_DRIFT_STATE_FILE"]
cooldown     = int(os.environ.get("DOCKET_DRIFT_COOLDOWN", "86400"))

def collect_terminal_sessions(max_n):
    sessions = []
    for tf in sorted(glob.glob(os.path.join(traces_dir, "**", "*.jsonl"), recursive=True)):
        parts = tf.replace(traces_dir + "/", "").split("/")
        project = parts[0] if len(parts) > 1 else "unknown"
        if proj_filter and project != proj_filter:
            continue
        cur_role = None; status = None
        try:
            with open(tf) as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if r.get("agent_role") == role:
                        cur_role = role
                    if r.get("event_type") == "session_end" and cur_role == role:
                        status = r.get("payload", {}).get("status", "success")
                        break
        except Exception:
            continue
        if cur_role == role and status:
            sessions.append(status)
        if len(sessions) >= max_n:
            break
    return sessions

all_sessions = collect_terminal_sessions(baseline_win + window)
if len(all_sessions) < window:
    # Not enough data yet — skip drift check
    sys.exit(0) if True else None

baseline_sessions = all_sessions[:-window]
current_sessions  = all_sessions[-window:]

def success_rate(sessions):
    if not sessions: return None
    # Aborted counts as failure (D-6)
    return sum(1 for s in sessions if s == "success") / len(sessions) * 100

base_rate = success_rate(baseline_sessions)
curr_rate = success_rate(current_sessions)

if base_rate is None or curr_rate is None:
    import sys; sys.exit(0)

if curr_rate >= base_rate - threshold:
    import sys; sys.exit(0)  # No drift

# Drift detected — check cooldown (D3)
try:
    state = json.load(open(state_file))
except Exception:
    state = {}

now = time.time()
last_alert = state.get("last_alert", {}).get(role, 0)
if (now - last_alert) < cooldown:
    import sys; sys.exit(0)  # Within cooldown, suppress

# Emit alert
import sys
sys.stdout.write(f"DRIFT|{role}|{round(base_rate,1)}|{round(curr_rate,1)}\n")

# Update cooldown state
state.setdefault("last_alert", {})[role] = now
tmp = state_file + ".tmp"
with open(tmp, "w") as f:
    json.dump(state, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, state_file)
PY
}

# drift_check_all — check every role represented in the trace store.
drift_check_all() {
  [[ -d "$TRACES_DIR" ]] || return 0

  # Collect all agent_roles from traces
  local roles
  roles=$(python3 -c "
import json, os, glob
traces = '$TRACES_DIR'
roles = set()
for tf in glob.glob(os.path.join(traces, '**', '*.jsonl'), recursive=True):
    try:
        with open(tf) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    r = json.loads(line)
                    role = r.get('agent_role', '')
                    if role and role != 'unknown':
                        roles.add(role)
                except Exception:
                    pass
    except Exception:
        pass
print('\n'.join(sorted(roles)))
" 2>/dev/null || true)

  [[ -z "$roles" ]] && return 0

  while IFS= read -r role; do
    [[ -z "$role" ]] && continue
    local result
    result=$(drift_check_role "$role" 2>/dev/null || true)
    if [[ "$result" == DRIFT* ]]; then
      IFS='|' read -r _ drift_role base_rate curr_rate <<< "$result"
      warn "Drift alert: role '$drift_role' success rate dropped from ${base_rate}% → ${curr_rate}% (threshold: ${DRIFT_THRESHOLD}pp)"
      trace_event "$drift_role" "drift-$$" "$drift_role" "drift_alert" \
        "{\"role\":\"$drift_role\",\"baseline_rate\":$base_rate,\"current_rate\":$curr_rate,\"threshold\":$DRIFT_THRESHOLD}" \
        2>/dev/null || true
      # Notify via Telegram (best-effort; resolve agent binding by role)
      local spec_ws="$OPENCLAW_DIR/workspaces/$drift_role"
      if [[ -d "$spec_ws" ]]; then
        tg_send "$drift_role" \
          "[docket] Drift alert: role '$drift_role' success rate dropped ${base_rate}% → ${curr_rate}% (threshold: ${DRIFT_THRESHOLD}pp)" \
          2>/dev/null || true
      fi
    fi
  done <<< "$roles"
}
