#!/usr/bin/env bash
# Command: metrics — compute role/project success rates, latency, cost, guardrails.
# Pure python-over-JSONL; no external store.
#
# docket metrics [--role R] [--project P] [--window N]

cmd_metrics() {
  local role="" project="" window="$METRICS_WINDOW"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --role|-r)    role="$2";    shift 2 ;;
      --project|-p) project="$2"; shift 2 ;;
      --window|-w)  window="$2";  shift 2 ;;
      -h|--help)    _metrics_help; return 0 ;;
      *) shift ;;
    esac
  done

  [[ -d "$TRACES_DIR" ]] || {
    fail "No traces directory found at $TRACES_DIR"
    info "Start tracing: docket trace ingest <project>"
    return 1
  }

  DOCKET_TRACES_DIR="$TRACES_DIR" \
  DOCKET_METRICS_ROLE="$role" \
  DOCKET_METRICS_PROJECT="$project" \
  DOCKET_METRICS_WINDOW="$window" \
    python3 - <<'PY'
import json, os, glob, statistics

traces_dir = os.environ["DOCKET_TRACES_DIR"]
role_filter    = os.environ.get("DOCKET_METRICS_ROLE", "")
project_filter = os.environ.get("DOCKET_METRICS_PROJECT", "")
window         = int(os.environ.get("DOCKET_METRICS_WINDOW", "50"))

# Collect all session_end records (terminal sessions), keyed by (project, session_id).
terminal_sessions = []
guardrail_trips   = {}   # action -> count

pattern = os.path.join(traces_dir, "**", "*.jsonl")
for tf in sorted(glob.glob(pattern, recursive=True)):
    parts = tf.replace(traces_dir + "/", "").split("/")
    project = parts[0] if len(parts) > 1 else "unknown"
    if project_filter and project != project_filter:
        continue

    session_data = {
        "project": project,
        "session_id": os.path.basename(tf).replace(".jsonl", ""),
        "role": None,
        "status": None,
        "cost_usd": 0.0,
        "duration_ms": None,
        "start_ts": None,
        "end_ts": None,
        "guardrail_trips": 0,
    }
    has_end = False
    try:
        with open(tf) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                etype = r.get("event_type", "")
                if etype == "session_start":
                    session_data["start_ts"] = r.get("ts")
                    session_data["role"] = r.get("agent_role") or session_data["role"]
                elif etype == "session_end":
                    has_end = True
                    session_data["status"] = r.get("payload", {}).get("status", "success")
                    session_data["end_ts"] = r.get("ts")
                    session_data["role"] = r.get("agent_role") or session_data["role"]
                elif etype == "cost_charged":
                    c = r.get("cost_usd") or 0
                    session_data["cost_usd"] += float(c)
                elif etype in ("guardrail_block", "approval_requested"):
                    action = r.get("payload", {}).get("action", etype)
                    guardrail_trips[action] = guardrail_trips.get(action, 0) + 1
                    session_data["guardrail_trips"] += 1
                if not session_data["role"]:
                    session_data["role"] = r.get("agent_role")
    except Exception:
        continue

    if not has_end:
        continue  # skip open sessions

    # Compute duration
    if session_data["start_ts"] and session_data["end_ts"]:
        import datetime
        try:
            s = datetime.datetime.strptime(session_data["start_ts"][:19], "%Y-%m-%dT%H:%M:%S")
            e = datetime.datetime.strptime(session_data["end_ts"][:19], "%Y-%m-%dT%H:%M:%S")
            session_data["duration_ms"] = int((e - s).total_seconds() * 1000)
        except Exception:
            pass

    terminal_sessions.append(session_data)

# Filter by role
if role_filter:
    terminal_sessions = [s for s in terminal_sessions if (s["role"] or "") == role_filter]

# Rolling window (most recent N)
terminal_sessions = terminal_sessions[-window:]

if not terminal_sessions:
    print("No terminal sessions found (run: docket trace ingest <project>)")
    import sys; sys.exit(0)

# Compute metrics
total    = len(terminal_sessions)
success  = sum(1 for s in terminal_sessions if s["status"] == "success")
failure  = sum(1 for s in terminal_sessions if s["status"] == "failure")
aborted  = sum(1 for s in terminal_sessions if s["status"] == "aborted")
s_rate   = round(success / total * 100, 1) if total else 0

durations = [s["duration_ms"] for s in terminal_sessions if s["duration_ms"] is not None]
costs     = [s["cost_usd"] for s in terminal_sessions]

mean_dur = round(statistics.mean(durations)) if durations else None
p95_dur  = round(sorted(durations)[int(len(durations) * 0.95)]) if durations else None
total_cost = round(sum(costs), 4)
mean_cost  = round(statistics.mean(costs), 4) if costs else 0

BOLD = "\033[1m"; RESET = "\033[0m"; GREEN = "\033[32m"; RED = "\033[31m"; YELLOW = "\033[33m"

print(f"\n{BOLD}docket metrics{RESET}  (window: {total} terminal sessions)")
if role_filter:   print(f"  Role:    {role_filter}")
if project_filter: print(f"  Project: {project_filter}")
print()
col = GREEN if s_rate >= 80 else (YELLOW if s_rate >= 60 else RED)
print(f"  Success rate   {col}{s_rate}%{RESET}  ({success} success / {failure} failure / {aborted} aborted)")
if mean_dur is not None:
    print(f"  Duration       mean={mean_dur}ms  p95={p95_dur}ms")
print(f"  Cost           total=${total_cost}  mean=${mean_cost}/session")
if guardrail_trips:
    print(f"  Guardrail trips:")
    for act, cnt in sorted(guardrail_trips.items(), key=lambda x: -x[1]):
        print(f"    {act:<30} {cnt}")
print()
PY
}

_metrics_help() {
  header "docket metrics"
  echo ""
  echo "  docket metrics                    All agents, default window"
  echo "  docket metrics --role programmer  Filter by agent role"
  echo "  docket metrics --project myapp    Filter by project"
  echo "  docket metrics --window 20        Use last 20 terminal sessions"
  echo ""
  echo "  Metrics computed from JSONL traces at $TRACES_DIR"
  echo "  Run 'docket trace ingest <project>' to populate traces first."
  echo ""
}
