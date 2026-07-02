#!/usr/bin/env bash
# Golden test runner for docket.
#
# Usage:
#   run.sh capture <cmd> [args...]   — run cmd, scrub output, WRITE golden file
#   run.sh verify  <cmd> [args...]   — run cmd, scrub output, DIFF against golden
#   run.sh list                      — list all golden cases
#
# Environment:
#   DOCKET_BIN   — path to the docket binary (default: <repo>/bin/docket)
#   GOLDEN_DIR   — base golden directory (default: <repo>/tests/golden)
#   KEEP_TMP     — set to 1 to leave the fake home dir after the run
#
# Each case is identified by the command + args joined with underscores.
# e.g.  "list" → cases/readonly/list.golden
#       "info myshop" → cases/readonly/info_myshop.golden
#
# Exit codes: 0 = match, 1 = mismatch/error, 2 = golden missing (verify mode)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DOCKET_BIN="${DOCKET_BIN:-$REPO_DIR/bin/docket}"
GOLDEN_DIR="${GOLDEN_DIR:-$SCRIPT_DIR}"
FAKES_DIR="$SCRIPT_DIR/fakes"
SEED_SCRIPT="$SCRIPT_DIR/fixtures/seed.sh"
SCRUB_PY="$SCRIPT_DIR/scrub.py"

# ── helpers ────────────────────────────────────────────────────────────────────

die()  { echo "golden/run.sh: $*" >&2; exit 1; }
info() { echo "  → $*" >&2; }

# Build a stable case-id from the command args
case_id() {
  echo "$*" | tr ' /' '__' | tr -s '_' | tr '[:upper:]' '[:lower:]'
}

# Locate the right cases/ subdir for a command
cases_dir() {
  local cmd="${1:-list}"
  case "$cmd" in
    list|info|cost|doctor|scope|context|auth|help|models|keys)
      echo "$GOLDEN_DIR/cases/readonly"
      ;;
    *)
      echo "$GOLDEN_DIR/cases/writers"
      ;;
  esac
}

# ── fake HOME setup ────────────────────────────────────────────────────────────

setup_fake_home() {
  local fake_home
  fake_home="$(mktemp -d)"
  bash "$SEED_SCRIPT" "$fake_home"
  echo "$fake_home"
}

teardown_fake_home() {
  local fake_home="$1"
  [[ "${KEEP_TMP:-0}" == "1" ]] && { info "kept fake home: $fake_home"; return; }
  rm -rf "$fake_home"
}

# ── run a docket command in the fake environment ───────────────────────────────

run_docket() {
  local fake_home="$1"; shift
  local stdout_file stderr_file exit_code_file
  stdout_file="$(mktemp)"
  stderr_file="$(mktemp)"
  exit_code_file="$(mktemp)"

  # Prepend fakes/ so our stubs intercept openclaw/systemctl/docker
  PATH="$FAKES_DIR:$PATH" \
  HOME="$fake_home" \
  OPENCLAW_DIR="$fake_home/.openclaw" \
  DOCKET_FAKE_HOME="$fake_home" \
  DOCKET_NO_COLOR=1 \
  NO_COLOR=1 \
    bash "$DOCKET_BIN" "$@" \
      >"$stdout_file" 2>"$stderr_file" \
      && echo "0" >"$exit_code_file" \
      || echo "$?" >"$exit_code_file"

  local exit_code
  exit_code="$(cat "$exit_code_file")"

  # Emit a structured snapshot: exit-code header, stdout, stderr section if any
  echo "EXIT:$exit_code"
  python3 "$SCRUB_PY" --home "$fake_home" <"$stdout_file"
  if [[ -s "$stderr_file" ]]; then
    echo "---STDERR---"
    python3 "$SCRUB_PY" --home "$fake_home" <"$stderr_file"
  fi

  rm -f "$stdout_file" "$stderr_file" "$exit_code_file"
}

# ── subcommands ────────────────────────────────────────────────────────────────

cmd_capture() {
  [[ $# -ge 1 ]] || die "capture requires at least one argument (the docket command)"
  local id; id="$(case_id "$@")"
  local dir; dir="$(cases_dir "$1")"
  local golden="$dir/$id.golden"

  local fake_home
  fake_home="$(setup_fake_home)"

  info "capturing: docket $* → $golden"
  run_docket "$fake_home" "$@" >"$golden"
  info "written $(wc -l <"$golden") lines"

  teardown_fake_home "$fake_home"
}

cmd_verify() {
  [[ $# -ge 1 ]] || die "verify requires at least one argument"
  local id; id="$(case_id "$@")"
  local dir; dir="$(cases_dir "$1")"
  local golden="$dir/$id.golden"

  [[ -f "$golden" ]] || { echo "MISSING golden: $golden" >&2; exit 2; }

  local fake_home actual_file
  fake_home="$(setup_fake_home)"
  actual_file="$(mktemp)"

  run_docket "$fake_home" "$@" >"$actual_file"

  teardown_fake_home "$fake_home"

  if diff -u "$golden" "$actual_file"; then
    rm -f "$actual_file"
    info "OK: docket $*"
    return 0
  else
    rm -f "$actual_file"
    echo "FAIL: docket $*" >&2
    return 1
  fi
}

cmd_list() {
  find "$GOLDEN_DIR/cases" -name '*.golden' | sort | while read -r f; do
    echo "  ${f#"$GOLDEN_DIR/cases/"}"
  done
}

# Verify every golden case in one pass. The command + args are recovered from
# each case-id by turning underscores back into spaces (the inverse of case_id,
# which is lossless for our flag-bearing names, e.g. list_--json → "list --json").
# Exits non-zero if any case fails — the single entry point CI calls.
cmd_verify_all() {
  local failed=0 total=0 case_file id args
  while IFS= read -r case_file; do
    id="$(basename "$case_file" .golden)"
    args="${id//_/ }"
    total=$((total + 1))
    # shellcheck disable=SC2086
    if ! cmd_verify $args; then
      failed=$((failed + 1))
    fi
  done < <(find "$GOLDEN_DIR/cases" -name '*.golden' | sort)
  echo "" >&2
  if [[ "$failed" -gt 0 ]]; then
    echo "GOLDEN SUITE: $failed/$total failed" >&2
    return 1
  fi
  echo "GOLDEN SUITE: all $total cases passed" >&2
  return 0
}

# ── entrypoint ─────────────────────────────────────────────────────────────────

MODE="${1:-}"
shift || true

case "$MODE" in
  capture)    cmd_capture "$@" ;;
  verify)     cmd_verify  "$@" ;;
  verify-all) cmd_verify_all ;;
  list)       cmd_list ;;
  *)          die "usage: run.sh <capture|verify|verify-all|list> [cmd args...]" ;;
esac
