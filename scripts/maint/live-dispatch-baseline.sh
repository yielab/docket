#!/usr/bin/env bash
# One real dispatch through the HTTP API, recorded: create a task on a pod the running
# `docket start --dispatch` serves, wait for it to settle, and keep the task, its trace and the
# raw trace files in one directory. The same command before and after a refactor gives two
# recordings to compare event by event (ADR 0030, P46-15); it also records a phase's real run.
#
# Usage: scripts/maint/live-dispatch-baseline.sh <pod> <out-dir> <description-file> [options-json]
#        scripts/maint/live-dispatch-baseline.sh <pod> <out-dir> --wait <task-id>
#
# The description file is the task text; options-json is an object of POST /tasks fields
# (`maxTokens`, `prepare`, `gate`, `pipeline`, `baseRef`, `externalRef`, `idempotencyKey`).
# Polling stops on a terminal status (done, failed, cancelled, blocked) or when the task waits
# on a person (waiting_approval, waiting_input); decide with `docket task approve|deny|answer`
# and resume with `--wait`. Nothing here approves anything.
#
# Env: DOCKET_SERVE_URL (default http://127.0.0.1:7399), DOCKET_TOKEN_FILE (default
# $DOCKET_HOME/token or ~/.docket/token), DOCKET_BIN (default docket), POLL_S (default 15).
set -euo pipefail

pod="${1:?pod}"
out="${2:?out-dir}"
mode="${3:?description-file or --wait}"
url="${DOCKET_SERVE_URL:-http://127.0.0.1:7399}"
home_dir="${DOCKET_HOME:-$HOME/.docket}"
token_file="${DOCKET_TOKEN_FILE:-$home_dir/token}"
bin="${DOCKET_BIN:-docket}"
poll="${POLL_S:-15}"
token="$(cat "$token_file")"
mkdir -p "$out"

api() { curl -sS -m 30 -H "Authorization: Bearer $token" "$@"; }

if [ "$mode" = "--wait" ]; then
    task_id="${4:?task-id}"
else
    description="$(cat "$mode")"
    options="${4:-}"
    body="$(python3 - "$description" "$options" <<'EOF'
import json, sys
body = {"description": sys.argv[1]}
if sys.argv[2]:
    body.update(json.load(open(sys.argv[2])))
print(json.dumps(body))
EOF
)"
    date -u +%Y-%m-%dT%H:%M:%SZ >"$out/started-at"
    api -X POST -H 'Content-Type: application/json' -d "$body" "$url/tasks/$pod" >"$out/create.json"
    task_id="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("id") or d.get("task",{}).get("id") or "")' "$out/create.json")"
    if [ -z "$task_id" ]; then
        echo "task not created: $(cat "$out/create.json")" >&2
        exit 1
    fi
    echo "$task_id" >"$out/task-id"
    echo "created $task_id on $pod"
fi

last=""
while :; do
    api "$url/tasks/$pod/$task_id" >"$out/task.json"
    status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status",""))' "$out/task.json")"
    if [ "$status" != "$last" ]; then
        printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" | tee -a "$out/status.log"
        last="$status"
    fi
    case "$status" in
        done|failed|cancelled|blocked|waiting_approval|waiting_input) break ;;
    esac
    sleep "$poll"
done

"$bin" task show "$task_id" --pod "$pod" --json >"$out/task-show.json" 2>"$out/task-show.err" || true
"$bin" task trace "$task_id" --pod "$pod" --json >"$out/task-trace.json" 2>"$out/task-trace.err" || true
"$bin" task diff "$task_id" --pod "$pod" >"$out/task.diff" 2>"$out/task-diff.err" || true
api "$url/traces/$pod" >"$out/traces-page.json"
mkdir -p "$out/trace-files"
if [ -f "$out/started-at" ]; then
    find "$home_dir/traces/$pod" -name '*.jsonl' -newermt "$(cat "$out/started-at")" -exec cp {} "$out/trace-files/" \;
else
    cp "$home_dir/traces/$pod"/*.jsonl "$out/trace-files/" 2>/dev/null || true
fi
echo "task $task_id ended polling at status $status; recorded in $out"
if [ "$status" = "waiting_approval" ] || [ "$status" = "waiting_input" ]; then
    echo "decide with: $bin task approve|deny|answer $task_id --pod $pod; then rerun with --wait $task_id"
fi
