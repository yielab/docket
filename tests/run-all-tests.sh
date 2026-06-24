#!/usr/bin/env bash
# Master test runner - runs all tests (unit + integration)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo "========================================"
echo "  Docket CLI - Full Test Suite"
echo "========================================"
echo ""

# Track results
UNIT_PASSED=true
EVALS_PASSED=true

# Run unit tests
echo -e "${BOLD}Running Unit Tests (pytest)...${RESET}"
echo "----------------------------------------"
if (cd "$PROJECT_ROOT" && uv run pytest -q); then
  echo -e "${GREEN}✓ Unit tests passed${RESET}"
else
  echo -e "${RED}✗ Unit tests failed${RESET}"
  UNIT_PASSED=false
fi

echo ""
echo -e "${BOLD}Running Golden Parity Suite...${RESET}"
echo "----------------------------------------"
if bash "$SCRIPT_DIR/golden/run.sh" verify-all; then
  echo -e "${GREEN}✓ Golden suite passed${RESET}"
else
  echo -e "${RED}✗ Golden suite failed${RESET}"
  UNIT_PASSED=false
fi

echo ""
echo "========================================"
echo ""

# Note: command/lifecycle behaviour is covered by the pytest suite (tests/python/)
# and the golden parity suite above — the old Bash integration test was retired in
# the Python cutover.

# Run evals (non-blocking — SKIP is acceptable; only FAIL counts)
echo -e "${BOLD}Running Eval Harness...${RESET}"
echo "----------------------------------------"
if "$SCRIPT_DIR/evals/run-evals.sh"; then
  echo -e "${GREEN}✓ Evals passed (or all skipped)${RESET}"
else
  echo -e "${YELLOW}⚠ Some evals failed (non-blocking)${RESET}"
  EVALS_PASSED=false
fi

echo ""
echo "========================================"
echo "  Final Summary"
echo "========================================"

if $UNIT_PASSED; then
  echo -e "${GREEN}${BOLD}✓ ALL TESTS PASSED${RESET}"
  $EVALS_PASSED || echo -e "  ${YELLOW}⚠ Evals: some failures (non-blocking — run: ./tests/evals/run-evals.sh)${RESET}"
  echo ""
  exit 0
else
  echo -e "${RED}${BOLD}✗ SOME TESTS FAILED${RESET}"
  echo ""
  $UNIT_PASSED || echo -e "  ${RED}• Unit/golden tests failed${RESET}"
  $EVALS_PASSED || echo -e "  ${YELLOW}⚠ Evals: some failures (non-blocking)${RESET}"
  echo ""
  exit 1
fi
