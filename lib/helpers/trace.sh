#!/usr/bin/env bash
# trace.sh — durable per-session JSONL trace writer and ingestion bridge.
#
# All agent actions that docket can observe are appended to:
#   $TRACES_DIR/<project>/<session_id>.jsonl
# One file per session → atomic vs concurrent sessions (O1).
# Disable all trace writes with DOCKET_NO_TRACE=1.

# Closed set of valid event types (O4).
_TRACE_EVENT_TYPES=(
  session_start tool_call tool_result
  guardrail_check guardrail_block
  approval_requested approval_granted approval_denied
  cost_charged budget_warning budget_exceeded
  drift_alert error session_end
)

# trace_event <project> <session_id> <agent_role> <event_type> <payload-json>
#             [cost_usd] [duration_ms]
# Validates event_type, redacts payload, appends one JSON line (0600).
trace_event() {
  [[ "${DOCKET_NO_TRACE:-0}" == "1" ]] && return 0
  command -v python3 >/dev/null 2>&1 || return 0

  local project="$1" session_id="$2" agent_role="$3" event_type="$4" payload="$5"
  local cost_usd="${6:-}" duration_ms="${7:-}"

  # Validate event_type
  local valid=0
  local t
  for t in "${_TRACE_EVENT_TYPES[@]}"; do
    [[ "$t" == "$event_type" ]] && { valid=1; break; }
  done
  if [[ "$valid" -eq 0 ]]; then
    warn "trace_event: unknown event_type '$event_type' — not written" >&2
    return 1
  fi

  local tracefile="$TRACES_DIR/$project/$session_id.jsonl"
  local redacted_payload
  redacted_payload=$(redact "$payload" 2>/dev/null || echo "$payload")

  DOCKET_TRACE_PROJECT="$project" \
  DOCKET_TRACE_SESSION="$session_id" \
  DOCKET_TRACE_ROLE="$agent_role" \
  DOCKET_TRACE_TYPE="$event_type" \
  DOCKET_TRACE_PAYLOAD="$redacted_payload" \
  DOCKET_TRACE_COST="$cost_usd" \
  DOCKET_TRACE_DURATION="$duration_ms" \
  DOCKET_TRACE_FILE="$tracefile" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, time

project   = os.environ["DOCKET_TRACE_PROJECT"]
session   = os.environ["DOCKET_TRACE_SESSION"]
role      = os.environ["DOCKET_TRACE_ROLE"]
etype     = os.environ["DOCKET_TRACE_TYPE"]
payload   = os.environ["DOCKET_TRACE_PAYLOAD"]
cost      = os.environ.get("DOCKET_TRACE_COST") or None
duration  = os.environ.get("DOCKET_TRACE_DURATION") or None
tracefile = os.environ["DOCKET_TRACE_FILE"]

# Parse payload as JSON if possible, else wrap in {text:...}
try:
    payload_obj = json.loads(payload)
except Exception:
    payload_obj = {"text": payload}

record = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "project": project,
    "session_id": session,
    "agent_role": role,
    "event_type": etype,
    "payload": payload_obj,
}
if cost not in (None, ""):
    try:
        record["cost_usd"] = float(cost)
    except ValueError:
        pass
if duration not in (None, ""):
    try:
        record["duration_ms"] = int(duration)
    except ValueError:
        pass

os.makedirs(os.path.dirname(tracefile), exist_ok=True)
is_new = not os.path.exists(tracefile)
with open(tracefile, "a") as f:
    f.write(json.dumps(record) + "\n")
if is_new:
    os.chmod(tracefile, 0o600)
PY
}

# trace_ingest <project> — idempotently project daemon session logs into traces.
# Reads ~/.openclaw/agents/<project>/sessions/*.jsonl; projects each into trace
# events (tool_call/tool_result per turn), offset-tracked to avoid double-emit.
# The fidelity ceiling: these are reconstructed from daemon logs; richer events
# require a daemon enhancement. Records the offset so re-runs add nothing new.
trace_ingest() {
  local project="$1"
  [[ "${DOCKET_NO_TRACE:-0}" == "1" ]] && return 0
  command -v python3 >/dev/null 2>&1 || return 0

  local agent_sessions_dir="$OPENCLAW_DIR/agents/$project/sessions"
  [[ -d "$agent_sessions_dir" ]] || return 0

  local index_file="$TRACES_DIR/$project/.ingest-index.json"
  mkdir -p "$TRACES_DIR/$project" || return 0
  chmod 700 "$TRACES_DIR/$project" 2>/dev/null || true

  DOCKET_INGEST_PROJECT="$project" \
  DOCKET_AGENT_SESSIONS="$agent_sessions_dir" \
  DOCKET_TRACES_DIR="$TRACES_DIR/$project" \
  DOCKET_INDEX_FILE="$index_file" \
  DOCKET_SESSION_TIMEOUT="$SESSION_TIMEOUT" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, time, glob

project      = os.environ["DOCKET_INGEST_PROJECT"]
sessions_dir = os.environ["DOCKET_AGENT_SESSIONS"]
traces_dir   = os.environ["DOCKET_TRACES_DIR"]
index_file   = os.environ["DOCKET_INDEX_FILE"]
timeout_s    = int(os.environ.get("DOCKET_SESSION_TIMEOUT", "3600"))

try:
    index = json.load(open(index_file))
except Exception:
    index = {}

now = time.time()
changed = False

for src in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
    session_id = os.path.basename(src).replace(".jsonl", "")
    offset     = index.get(session_id, 0)
    tracefile  = os.path.join(traces_dir, session_id + ".jsonl")

    try:
        with open(src, "r") as f:
            all_lines = f.readlines()
    except Exception:
        continue

    new_lines = all_lines[offset:]
    if not new_lines:
        continue

    # Derive session start ts from first record
    session_start_ts = None
    try:
        first = json.loads(all_lines[0])
        session_start_ts = first.get("timestamp", "")
    except Exception:
        pass

    records_to_write = []

    # Emit session_start if this is the very first batch for this session
    if offset == 0:
        records_to_write.append({
            "ts": session_start_ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "project": project,
            "session_id": session_id,
            "agent_role": "unknown",
            "event_type": "session_start",
            "payload": {"source": "ingested"},
        })

    last_ts = None
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue

        etype = rec.get("type", "")
        ts    = rec.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        last_ts = ts

        if etype in ("tool_use", "tool_result", "message"):
            event_type = "tool_call" if etype == "tool_use" else (
                "tool_result" if etype == "tool_result" else None
            )
            if event_type is None:
                continue
            records_to_write.append({
                "ts": ts,
                "project": project,
                "session_id": session_id,
                "agent_role": "unknown",
                "event_type": event_type,
                "payload": {"source": "ingested", "daemon_type": etype, "id": rec.get("id")},
            })

    is_new = not os.path.exists(tracefile)
    if records_to_write:
        with open(tracefile, "a") as f:
            for r in records_to_write:
                f.write(json.dumps(r) + "\n")
        if is_new:
            os.chmod(tracefile, 0o600)

    new_offset = offset + len(new_lines)
    index[session_id] = new_offset
    changed = True

    # Synthetic session_end for timed-out open traces
    if last_ts:
        try:
            # Parse ISO ts to epoch
            import datetime
            dt = datetime.datetime.strptime(last_ts[:19], "%Y-%m-%dT%H:%M:%S")
            last_epoch = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            if (now - last_epoch) > timeout_s:
                # Check if we already wrote a session_end
                has_end = False
                if os.path.exists(tracefile):
                    with open(tracefile, "r") as f:
                        for line in f:
                            try:
                                r = json.loads(line)
                                if r.get("event_type") == "session_end":
                                    has_end = True
                                    break
                            except Exception:
                                pass
                if not has_end:
                    end_record = {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "project": project,
                        "session_id": session_id,
                        "agent_role": "unknown",
                        "event_type": "session_end",
                        "payload": {"status": "aborted", "source": "timeout-sweep"},
                    }
                    with open(tracefile, "a") as f:
                        f.write(json.dumps(end_record) + "\n")
        except Exception:
            pass

if changed:
    tmp = index_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(index, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, index_file)
PY
}

# _trace_sweep_all — called by docket serve to coerce stale open traces to aborted.
# Only runs on traces docket itself wrote (not the ingestion path, which already
# handles timeout per-session-file during ingestion).
_trace_sweep_all() {
  [[ -d "$TRACES_DIR" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0

  DOCKET_TRACES_DIR="$TRACES_DIR" \
  DOCKET_SESSION_TIMEOUT="$SESSION_TIMEOUT" \
    python3 - <<'PY' 2>/dev/null || true
import json, os, time, glob, datetime

traces_dir = os.environ["DOCKET_TRACES_DIR"]
timeout_s  = int(os.environ.get("DOCKET_SESSION_TIMEOUT", "3600"))
now = time.time()

for tf in glob.glob(os.path.join(traces_dir, "*", "*.jsonl")):
    lines = []
    has_end = False
    last_ts_str = None
    try:
        with open(tf, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    lines.append(r)
                    if r.get("event_type") == "session_end":
                        has_end = True
                    last_ts_str = r.get("ts") or last_ts_str
                except Exception:
                    pass
    except Exception:
        continue

    if has_end or last_ts_str is None:
        continue

    try:
        dt = datetime.datetime.strptime(last_ts_str[:19], "%Y-%m-%dT%H:%M:%S")
        last_epoch = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        continue

    if (now - last_epoch) > timeout_s:
        # Derive project from path
        parts = tf.replace(traces_dir + "/", "").split("/")
        project = parts[0] if len(parts) > 1 else "unknown"
        session_id = os.path.basename(tf).replace(".jsonl", "")
        end_record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "project": project,
            "session_id": session_id,
            "agent_role": "unknown",
            "event_type": "session_end",
            "payload": {"status": "aborted", "source": "timeout-sweep"},
        }
        with open(tf, "a") as f:
            f.write(json.dumps(end_record) + "\n")
PY
}
