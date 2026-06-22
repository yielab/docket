#!/usr/bin/env bash
# Command: trace — view, follow, and export agent action traces.
#
# docket trace <session_id>              render one trace human-readable
# docket trace tail <project>            follow the most-recent session
# docket trace export <project> [--since DATE]   raw JSONL passthrough

cmd_trace() {
  local subcommand="${1:-}"
  case "$subcommand" in
    tail)   shift; _trace_tail "$@" ;;
    export) shift; _trace_export "$@" ;;
    ingest) shift; _trace_ingest_cmd "$@" ;;
    "")     _trace_help; return 0 ;;
    -h|--help) _trace_help; return 0 ;;
    *)
      # Treat as session_id
      _trace_show "$@"
      ;;
  esac
}

_trace_help() {
  header "docket trace"
  echo ""
  echo "  docket trace <session_id>              Render one trace human-readable"
  echo "  docket trace tail <project>            Follow the most-recent session"
  echo "  docket trace export <project>          Raw JSONL passthrough"
  echo "    [--since YYYY-MM-DD]                 Filter by date"
  echo "  docket trace ingest <project>          Manually ingest daemon session logs"
  echo ""
  echo "  Traces live at: $TRACES_DIR/<project>/<session_id>.jsonl"
  echo ""
}

_trace_show() {
  local session_id="${1:-}"
  [[ -z "$session_id" ]] && { _trace_help; return 0; }

  local found=""
  # Search across all projects
  local f
  for f in "$TRACES_DIR"/*/"${session_id}.jsonl"; do
    [[ -f "$f" ]] && { found="$f"; break; }
  done

  if [[ -z "$found" ]]; then
    fail "No trace found for session: $session_id"
    info "Available sessions: docket trace export <project>"
    return 1
  fi

  header "Trace: $session_id"
  echo ""

  DOCKET_TRACEFILE="$found" python3 - <<'PY'
import json, os

tf = os.environ["DOCKET_TRACEFILE"]
try:
    lines = open(tf).readlines()
except Exception as e:
    print(f"Error reading trace: {e}")
    exit(1)

COLOR = {
    "session_start":       "\033[32m",   # green
    "session_end":         "\033[32m",
    "tool_call":           "\033[36m",   # cyan
    "tool_result":         "\033[36m",
    "cost_charged":        "\033[33m",   # yellow
    "budget_warning":      "\033[33m",
    "budget_exceeded":     "\033[31m",   # red
    "guardrail_check":     "\033[34m",   # blue
    "guardrail_block":     "\033[31m",
    "approval_requested":  "\033[35m",   # magenta
    "approval_granted":    "\033[32m",
    "approval_denied":     "\033[31m",
    "drift_alert":         "\033[31m",
    "error":               "\033[31m",
}
RESET = "\033[0m"

for line in lines:
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    ts      = r.get("ts", "?")[:19]
    etype   = r.get("event_type", "?")
    role    = r.get("agent_role", "")
    payload = r.get("payload", {})
    cost    = r.get("cost_usd")
    dur     = r.get("duration_ms")

    col = COLOR.get(etype, "")
    # Build summary
    summary_parts = []
    if isinstance(payload, dict):
        for k in ("status", "action", "text", "task_id", "pct"):
            v = payload.get(k)
            if v is not None:
                summary_parts.append(f"{k}={v}")
    summary = "  " + "  ".join(summary_parts) if summary_parts else ""

    extras = []
    if cost is not None:
        extras.append(f"${cost:.4f}")
    if dur is not None:
        extras.append(f"{dur}ms")
    extras_str = "  [" + "  ".join(extras) + "]" if extras else ""

    role_str = f"  ({role})" if role and role != "unknown" else ""
    print(f"  {col}{ts}  {etype:<25}{RESET}{role_str}{summary}{extras_str}")
PY
  echo ""
}

_trace_tail() {
  local project="${1:-}"
  [[ -z "$project" ]] && error "Usage: docket trace tail <project>"

  local project_trace_dir="$TRACES_DIR/$project"
  if [[ ! -d "$project_trace_dir" ]]; then
    # Try ingesting first
    trace_ingest "$project" 2>/dev/null || true
  fi

  if [[ ! -d "$project_trace_dir" ]]; then
    fail "No traces for project: $project"
    info "Start tracing with: docket trace ingest $project"
    return 1
  fi

  # Find most recent trace file
  local latest
  latest=$(ls -t "$project_trace_dir"/*.jsonl 2>/dev/null | head -1)
  if [[ -z "$latest" ]]; then
    fail "No trace files found for project: $project"
    return 1
  fi

  info "Following: $(basename "$latest")  (Ctrl-C to stop)"
  echo ""
  tail -f "$latest"
}

_trace_export() {
  local project="${1:-}" since=""
  shift || true
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  [[ -z "$project" ]] && error "Usage: docket trace export <project> [--since YYYY-MM-DD]"

  local project_trace_dir="$TRACES_DIR/$project"
  if [[ ! -d "$project_trace_dir" ]]; then
    trace_ingest "$project" 2>/dev/null || true
  fi

  DOCKET_EXPORT_DIR="${project_trace_dir:-}" \
  DOCKET_EXPORT_SINCE="$since" \
    python3 - <<'PY'
import json, os, glob

export_dir = os.environ.get("DOCKET_EXPORT_DIR", "")
since_str  = os.environ.get("DOCKET_EXPORT_SINCE", "")

if not export_dir or not os.path.isdir(export_dir):
    import sys
    print(f"No trace directory found", file=sys.stderr)
    sys.exit(1)

for tf in sorted(glob.glob(os.path.join(export_dir, "*.jsonl"))):
    try:
        with open(tf) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if since_str:
                    try:
                        r = json.loads(line)
                        ts = r.get("ts", "")
                        if ts < since_str:
                            continue
                    except Exception:
                        pass
                print(line)
    except Exception:
        pass
PY
}

_trace_ingest_cmd() {
  local project="${1:-}"
  [[ -z "$project" ]] && error "Usage: docket trace ingest <project>"
  info "Ingesting session logs for: $project"
  trace_ingest "$project"
  success "Ingest complete → $TRACES_DIR/$project/"
}
