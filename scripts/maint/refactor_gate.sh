#!/usr/bin/env bash
# The Phase 46 gate: the nine checks a refactor step must pass, stopping at the first failure.
#
#   1 lint               ruff check, ruff format --check
#   2 types              mypy src (with the mcp extra, as CI does)
#   3 import-contracts   tests/architecture/test_import_contracts.py (violations, ignore list)
#   4 test-ids           tests/architecture/test_ids.py (the node-id manifest)
#   5 lanes              default lanes, pytest-without-sandbox.sh, the escape matrix
#   6 golden             tests/golden/run.sh verify-all
#   7 docs               validate-specs.sh and the generated-docs checks of the CI docs job
#   8 specs-diff         specs/ changed against --base by paths only
#   9 metrics            analyze.py --metrics against refactor/metrics-baseline.txt
#
# A check whose test or tool does not exist yet is reported as MISSING and fails. It never passes.
# Exit code: 0 all passed, 1 a check failed or is missing, 2 bad usage.
#
# Usage: scripts/maint/refactor_gate.sh [--base REV] [--only CHECK] [--list] [--record-metrics]
#                                       [--root DIR]
#   --base REV         what check 8 compares specs/ with (default: REFACTOR_BASE or HEAD)
#   --only CHECK       run one check, by number or name
#   --list             print the checks in order and exit
#   --record-metrics   write the current analyze.py --metrics values as the new baseline for check 9
#   --root DIR         run against another checkout (default: this repository)
set -uo pipefail

CHECKS=(lint types import-contracts test-ids lanes golden docs specs-diff metrics)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${REFACTOR_BASE:-HEAD}"
ONLY=""
LIST=0
RECORD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --base) BASE="${2:?--base needs a revision}"; shift 2 ;;
        --only) ONLY="${2:?--only needs a check}"; shift 2 ;;
        --root) ROOT="$(cd "${2:?--root needs a directory}" && pwd)"; shift 2 ;;
        --list) LIST=1; shift ;;
        --record-metrics) RECORD=1; shift ;;
        -h | --help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "refactor_gate: unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ "$LIST" = 1 ]; then
    n=0
    for name in "${CHECKS[@]}"; do n=$((n + 1)); echo "$n $name"; done
    exit 0
fi

cd "$ROOT" || exit 2

step() {
    echo "+ $*" >&2
    "$@"
}

uvrun() {
    step env -u VIRTUAL_ENV uv run "$@"
}

missing() {
    echo "GATE MISSING: check $1: $2" >&2
    return 1
}

require() {
    local check="$1" path="$2" owner="$3"
    [ -e "$path" ] || missing "$check" "$path does not exist ($owner)"
}

metrics_baseline="refactor/metrics-baseline.txt"
analyze="scripts/maint/refactor/analyze.py"

check_lint() {
    uvrun ruff check . && uvrun ruff format --check .
}

check_types() {
    uvrun --extra mcp mypy src
}

check_import_contracts() {
    require "3 import-contracts" tests/architecture/test_import_contracts.py "added by P46-4" || return 1
    uvrun pytest -q tests/architecture/test_import_contracts.py
}

check_test_ids() {
    require "4 test-ids" tests/architecture/test_ids.py "added by P46-4" || return 1
    uvrun pytest -q tests/architecture/test_ids.py
}

check_lanes() {
    uvrun --extra mcp pytest -q &&
        step env -u VIRTUAL_ENV bash scripts/maint/pytest-without-sandbox.sh -q &&
        uvrun --extra mcp pytest -q tests/integration/test_escape_matrix.py
}

check_golden() {
    step env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
}

check_docs() {
    step bash scripts/validate-specs.sh &&
        uvrun python scripts/gen_cli_docs.py --check &&
        uvrun python scripts/gen_evidence_schema.py --check &&
        uvrun python scripts/gen_recipe_docs.py --check &&
        uvrun python scripts/gen_operator_schemas.py --check
}

check_specs_diff() {
    echo "+ specs/ against $BASE, paths ignored" >&2
    git rev-parse --verify --quiet "$BASE^{commit}" > /dev/null || {
        echo "GATE FAILED: check 8 specs-diff: $BASE is not a revision" >&2
        return 1
    }
    SPECS_BASE="$BASE" python3 - << 'PY'
import os
import re
import subprocess
import sys

base = os.environ["SPECS_BASE"]
PATHS = re.compile(
    r"(?<![\w./-])(?:[\w-]+/)+[\w-]+\.py(?:::\w+)?(?!\w)|(?<![\w.])docket(?:\.\w+)+"
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def normalise(text: str) -> list[str]:
    return [PATHS.sub("<path>", line) for line in text.splitlines()]


changed = git("diff", "--name-status", base, "--", "specs/").splitlines()
bad = []
for entry in changed:
    status, _, path = entry.partition("\t")
    if status != "M":
        bad.append(f"{status} {path}: a spec file was added, deleted or renamed")
        continue
    old = normalise(git("show", f"{base}:{path}"))
    with open(path, encoding="utf-8") as handle:
        new = normalise(handle.read())
    if old != new:
        lines = [f"{i + 1}: {o!r} -> {n!r}" for i, (o, n) in enumerate(zip(old, new)) if o != n]
        extra = f"{len(old)} lines became {len(new)}" if len(old) != len(new) else ""
        bad.append(f"{path}: {extra or lines[0]}")
for item in bad:
    print(f"spec change that is not a path: {item}", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
}

current_metrics() {
    echo "+ $analyze --metrics" >&2
    env -u VIRTUAL_ENV uv run python "$analyze" --metrics | python3 -c '
import json
import re
import sys

text = sys.stdin.read()
try:
    data = json.loads(text)
    pairs = [(str(k), v) for k, v in data.items() if isinstance(v, (int, float))]
except ValueError:
    pairs = [
        (m.group(1).strip().replace(" ", "_"), float(m.group(2)))
        for m in re.finditer(r"^\s*([A-Za-z][\w -]*?)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*$", text, re.M)
    ]
for key, value in pairs:
    print(key, int(value) if value == int(value) else value)
'
}

check_metrics() {
    require "9 metrics" "$analyze" "added by P46-2" || return 1
    if [ "$RECORD" = 1 ]; then
        mkdir -p refactor
        current_metrics > "$metrics_baseline" || return 1
        echo "recorded $metrics_baseline" >&2
        return 0
    fi
    require "9 metrics" "$metrics_baseline" "run refactor_gate.sh --record-metrics once on a green tree" || return 1
    local now
    now="$(current_metrics)" || return 1
    [ -n "$now" ] || { echo "GATE FAILED: check 9 metrics: $analyze --metrics printed no numbers" >&2; return 1; }
    NOW="$now" BASELINE_FILE="$metrics_baseline" python3 - << 'PY'
import os
import sys

now = dict(line.rsplit(" ", 1) for line in os.environ["NOW"].splitlines() if line)
with open(os.environ["BASELINE_FILE"], encoding="utf-8") as handle:
    base = dict(line.rsplit(" ", 1) for line in handle.read().splitlines() if line)
bad = []
for key, was in base.items():
    if key not in now:
        bad.append(f"{key}: no longer reported (was {was})")
    elif float(now[key]) > float(was):
        bad.append(f"{key}: {now[key]} > {was}")
for item in bad:
    print(f"metric got worse: {item}", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
}

run_check() {
    local number="$1" name="$2"
    echo "== check $number $name" >&2
    "check_${name//-/_}"
    local code=$?
    if [ "$code" -ne 0 ]; then
        echo "GATE FAILED: check $number $name" >&2
        return 1
    fi
    echo "ok: check $number $name" >&2
}

if [ -n "$ONLY" ]; then
    n=0
    for name in "${CHECKS[@]}"; do
        n=$((n + 1))
        if [ "$ONLY" = "$name" ] || [ "$ONLY" = "$n" ]; then
            run_check "$n" "$name" || exit 1
            exit 0
        fi
    done
    echo "refactor_gate: no check named $ONLY" >&2
    exit 2
fi

if [ "$RECORD" = 1 ]; then
    check_metrics || { echo "GATE FAILED: --record-metrics" >&2; exit 1; }
    exit 0
fi

n=0
for name in "${CHECKS[@]}"; do
    n=$((n + 1))
    run_check "$n" "$name" || exit 1
done
echo "GATE PASSED: all ${#CHECKS[@]} checks" >&2
