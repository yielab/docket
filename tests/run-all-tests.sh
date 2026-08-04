#!/usr/bin/env bash
# Master test runner - runs all tests (unit + integration)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo "========================================"
echo "  Docket CLI - Full Test Suite"
echo "========================================"
echo ""

# Track results
UNIT_PASSED=true

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
# the Python cutover. The specialist-role eval harness (tests/evals/) was removed
# (CL-J): it was dead code, wired to the deleted OpenClaw daemon.

echo "========================================"
echo "  Final Summary"
echo "========================================"

if $UNIT_PASSED; then
  echo -e "${GREEN}${BOLD}✓ ALL TESTS PASSED${RESET}"
  echo ""
  exit 0
else
  echo -e "${RED}${BOLD}✗ SOME TESTS FAILED${RESET}"
  echo ""
  echo -e "  ${RED}• Unit/golden tests failed${RESET}"
  echo ""
  exit 1
fi
