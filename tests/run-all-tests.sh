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
echo "  Rack CLI - Full Test Suite"
echo "========================================"
echo ""

# Track results
UNIT_PASSED=true
INTEGRATION_PASSED=true

# Run unit tests
echo -e "${BOLD}Running Unit Tests...${RESET}"
echo "----------------------------------------"
if "$SCRIPT_DIR/unit/test-helpers.sh"; then
  echo -e "${GREEN}✓ Unit tests passed${RESET}"
else
  echo -e "${RED}✗ Unit tests failed${RESET}"
  UNIT_PASSED=false
fi

echo ""
echo "========================================"
echo ""

# Run integration tests
echo -e "${BOLD}Running Integration Tests...${RESET}"
echo "----------------------------------------"
if "$SCRIPT_DIR/test-lifecycle.sh"; then
  echo -e "${GREEN}✓ Integration tests passed${RESET}"
else
  echo -e "${RED}✗ Integration tests failed${RESET}"
  INTEGRATION_PASSED=false
fi

echo ""
echo "========================================"
echo "  Final Summary"
echo "========================================"

if $UNIT_PASSED && $INTEGRATION_PASSED; then
  echo -e "${GREEN}${BOLD}✓ ALL TESTS PASSED${RESET}"
  echo ""
  exit 0
else
  echo -e "${RED}${BOLD}✗ SOME TESTS FAILED${RESET}"
  echo ""
  $UNIT_PASSED || echo -e "  ${RED}• Unit tests failed${RESET}"
  $INTEGRATION_PASSED || echo -e "  ${RED}• Integration tests failed${RESET}"
  echo ""
  exit 1
fi
