#!/usr/bin/env bash
# Unit tests for helper functions

# Test framework (simple bash-based)
TESTS_PASSED=0
TESTS_FAILED=0

assert_equals() {
  local expected="$1"
  local actual="$2"
  local test_name="$3"

  if [[ "$expected" == "$actual" ]]; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name"
    echo "  Expected: $expected"
    echo "  Actual:   $actual"
    ((TESTS_FAILED++))
  fi
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local test_name="$3"

  if echo "$haystack" | grep -q "$needle"; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name"
    echo "  String '$needle' not found in '$haystack'"
    ((TESTS_FAILED++))
  fi
}

assert_not_empty() {
  local value="$1"
  local test_name="$2"

  if [[ -n "$value" ]]; then
    echo "✓ PASS: $test_name"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: $test_name (value is empty)"
    ((TESTS_FAILED++))
  fi
}

# Setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "$SCRIPT_DIR/../../lib" && pwd)"

# Don't use strict mode for tests (it causes issues with test assertions)
DEBUG="${DEBUG:-0}"
source "$LIB_DIR/core/config.sh"
source "$LIB_DIR/helpers/utils.sh"
source "$LIB_DIR/helpers/session.sh"

echo ""
echo "========================================"
echo "  Unit Tests: Helper Functions"
echo "========================================"
echo ""

# Test: slugify
echo "Testing slugify()..."
result=$(slugify "My Project Name")
assert_equals "my-project-name" "$result" "slugify converts to lowercase and dashes"

result=$(slugify "Test_123  Spaces")
assert_equals "test-123-spaces" "$result" "slugify handles underscores and multiple spaces"

result=$(slugify "Special!@#Chars")
assert_contains "$result" "special" "slugify removes special characters"

echo ""

# Test: generate_session_key
echo "Testing generate_session_key()..."
result=$(generate_session_key "myproject" "default")
assert_equals "agent:myproject:default" "$result" "generate_session_key with default"

result=$(generate_session_key "test-app" "alpha")
assert_equals "agent:test-app:alpha" "$result" "generate_session_key with custom key"

result=$(generate_session_key "myproject")
assert_equals "agent:myproject:default" "$result" "generate_session_key defaults to 'default'"

echo ""

# Test: parse_session_key
echo "Testing parse_session_key()..."
result=$(parse_session_key "agent:myproject:default")
assert_equals "default" "$result" "parse_session_key extracts default"

result=$(parse_session_key "agent:test-app:alpha")
assert_equals "alpha" "$result" "parse_session_key extracts alpha"

result=$(parse_session_key "agent:another:beta")
assert_equals "beta" "$result" "parse_session_key extracts beta"

echo ""

# Test: detect_stack (need temp directory)
echo "Testing detect_stack()..."
TEMP_DIR=$(mktemp -d)
touch "$TEMP_DIR/package.json"
echo '{"dependencies":{"react":"^18.0.0","typescript":"^5.0.0"}}' > "$TEMP_DIR/package.json"

result=$(detect_stack "$TEMP_DIR")
assert_contains "$result" "Node.js" "detect_stack finds Node.js"
assert_contains "$result" "React" "detect_stack finds React from package.json"
assert_contains "$result" "TypeScript" "detect_stack finds TypeScript from package.json"

# Test Python detection
rm "$TEMP_DIR/package.json"
touch "$TEMP_DIR/requirements.txt"
echo "fastapi" > "$TEMP_DIR/requirements.txt"
echo "pytest" >> "$TEMP_DIR/requirements.txt"

result=$(detect_stack "$TEMP_DIR")
assert_contains "$result" "Python" "detect_stack finds Python"
assert_contains "$result" "FastAPI" "detect_stack finds FastAPI from requirements.txt"
assert_contains "$result" "pytest" "detect_stack finds pytest"

# Cleanup
rm -rf "$TEMP_DIR"

echo ""

# Test: model_to_profile
echo "Testing model_to_profile()..."
result=$(model_to_profile "anthropic/claude-haiku-4-5")
assert_equals "economy" "$result" "model_to_profile returns economy for haiku"

result=$(model_to_profile "anthropic/claude-sonnet-4-6")
assert_equals "standard" "$result" "model_to_profile returns standard for sonnet"

result=$(model_to_profile "anthropic/claude-opus-4-6")
assert_equals "premium" "$result" "model_to_profile returns premium for opus"

result=$(model_to_profile "some-unknown-model")
assert_equals "custom" "$result" "model_to_profile returns custom for unknown models"

echo ""

# Test: resolve_model
echo "Testing resolve_model()..."
result=$(resolve_model "economy")
assert_equals "anthropic/claude-haiku-4-5" "$result" "resolve_model expands economy to haiku"

result=$(resolve_model "standard")
assert_equals "anthropic/claude-sonnet-4-6" "$result" "resolve_model expands standard to sonnet"

result=$(resolve_model "premium")
assert_equals "anthropic/claude-opus-4-6" "$result" "resolve_model expands premium to opus"

result=$(resolve_model "anthropic/claude-custom-1-0")
assert_equals "anthropic/claude-custom-1-0" "$result" "resolve_model returns unknown models as-is"

echo ""

# Test: test_cmd_for_stack
echo "Testing test_cmd_for_stack()..."
result=$(test_cmd_for_stack "Python, pytest")
assert_equals "pytest -v" "$result" "test_cmd_for_stack returns pytest for Python"

result=$(test_cmd_for_stack "Node.js, React")
assert_equals "npm test" "$result" "test_cmd_for_stack returns npm test for Node.js"

result=$(test_cmd_for_stack "Go")
assert_equals "go test ./..." "$result" "test_cmd_for_stack returns go test for Go"

result=$(test_cmd_for_stack "Rust")
assert_equals "cargo test" "$result" "test_cmd_for_stack returns cargo test for Rust"

echo ""
echo "========================================"
echo "  Summary"
echo "========================================"
echo "  Passed: $TESTS_PASSED"
echo "  Failed: $TESTS_FAILED"
echo "========================================"
echo ""

if [[ $TESTS_FAILED -gt 0 ]]; then
  exit 1
else
  exit 0
fi
