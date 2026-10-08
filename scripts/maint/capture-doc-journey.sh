#!/usr/bin/env bash
# Drive the real docket CLI through the journey the public visuals show, against a live
# OpenAI-compatible endpoint, and write one transcript per scene. scripts/render-doc-assets.py
# transcribes these transcripts; refresh both together.
#
# Usage: scripts/maint/capture-doc-journey.sh [endpoint]   (default http://127.0.0.1:8081/v1)
# Needs `docket` on PATH and a model with function-tool support. Takes about five minutes: the
# gate scene deliberately waits out the 120-second approval timeout.
set -uo pipefail

ENDPOINT="${1:-http://127.0.0.1:8081/v1}"
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dk.XXXX")"
OUT="$ROOT/out"
mkdir -p "$ROOT/code/myapp" "$ROOT/code/svc" "$ROOT/hh" "$OUT"

# A throwaway HOME keeps every path short and renders it as "~"; the operator's own
# ~/.docket is never read or written.
export HOME="$ROOT" USER=demo LOGNAME=demo DOCKET_TOOL_MAX_OUTPUT_CHARS=2500
export GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.com
export GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.com
unset DOCKET_HOME DOCKET_LLM_BASE_URL

run() {
    local file="$OUT/$1"
    shift
    printf '$ %s\n' "$*" >>"$file"
    eval "$*" >>"$file" 2>&1
    printf '[exit %s]\n' "$?" >>"$file"
}

seed_repo() {
    git -C "$1" init -q -b main && git -C "$1" add . && git -C "$1" commit -qm init
}

printf 'def add(a, b):\n    return a - b\n' >"$ROOT/code/myapp/calc.py"
printf '# myapp\n' >"$ROOT/code/myapp/README.md"
seed_repo "$ROOT/code/myapp"
printf 'VERSION = "1.0"\n' >"$ROOT/code/svc/app.py"
seed_repo "$ROOT/code/svc"

cd "$ROOT/code/myapp" || exit 1
docket models provider add local "$ENDPOINT" --model local-model --ctx 16384 --max-tokens 4096 \
    >/dev/null 2>&1
docket models preset local >/dev/null 2>&1
# Isolation is opt-in; the visuals show the jailed path, so this host needs bwrap or docker.
docket gates isolate on >/dev/null 2>&1 || exit 1

# 1-team: the team comes from a shipped recipe, is written back to .docket/, validated, planned.
run 1-team.txt docket init --recipe secure-build
run 1-team.txt docket pod myapp export
run 1-team.txt "find .docket -type f | sort"
run 1-team.txt docket validate
run 1-team.txt docket pipeline plan myapp
run 1-team.txt "docket pod myapp set-verify myapp-implementer \"python3 -c 'import calc; assert calc.add(2, 3) == 5'\""

run 2-dispatch.txt 'docket pod myapp delegate "Fix calc.add so it returns the sum of a and b"'
run 2-dispatch.txt docket pod myapp dispatch
run 2-dispatch.txt docket runs list
session="$(basename "$(ls -t "$HOME"/.docket/traces/myapp/*.jsonl | head -1)" .jsonl)"
run 2-dispatch.txt "docket trace $session"

worktree="$(ls -d "$HOME"/.docket/workspaces/projects/myapp-implementer/tasks/*/ | head -1)"
worktree="${worktree%/}"
run 3-isolation.txt docket info myapp-implementer
run 3-isolation.txt docket gates status
run 3-isolation.txt git worktree list
run 3-isolation.txt git status --short
run 3-isolation.txt "git -C $worktree diff main"

run 4-gate.txt "docket policies test pre_tool_call implementer 'git push origin production'"
run 4-gate.txt 'docket pod myapp delegate "Publish the fix. Lead: never call the consult tool and do not ask questions, the operator already decided; hand this to the implementer as is. Implementer: run exactly this bash command once and report its output: git push origin production"'
run 4-gate.txt docket pod myapp dispatch
run 4-gate.txt docket log
run 4-gate.txt "docket trace export myapp | grep '\"deny\"'"
run 4-gate.txt docket log verify

# 5-record: what the pod knows about itself after the run.
run 5-record.txt docket config explain myapp-implementer
run 5-record.txt docket log verify

run 6-harness.txt "DOCKET_HOME=$HOME/hh DOCKET_LLM_BASE_URL=$ENDPOINT docket exec --workspace $HOME/code/svc --model local/local-model --task 'Run exactly this bash command: git push origin production' 2>/dev/null | tail -1 | python3 -m json.tool"

# Render the capture root as "~" so the transcripts can be copied into the renderer as-is.
sed -i.bak "s|$ROOT|~|g" "$OUT"/*.txt && rm -f "$OUT"/*.bak
echo "transcripts: $OUT"
