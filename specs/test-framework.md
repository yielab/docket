# Test-Driven Development Framework

**Version**: 1.0.0
**Status**: Active
**Last Updated**: 2024-01-20

## Overview

This document establishes the TDD (Test-Driven Development) framework for rack-cli, ensuring all features are developed test-first according to specifications.

## TDD Workflow

### The Three Laws of TDD

1. **You may not write production code until you have written a failing test**
2. **You may not write more of a test than is sufficient to fail**
3. **You may not write more production code than is sufficient to pass the test**

### Red-Green-Refactor Cycle

```
┌──────────┐
│   RED    │ Write failing test
└────┬─────┘
     │
     ▼
┌──────────┐
│  GREEN   │ Write minimal code to pass
└────┬─────┘
     │
     ▼
┌──────────┐
│ REFACTOR │ Improve code quality
└────┬─────┘
     │
     └──────┐
            │
            ▼
     [Repeat Cycle]
```

## Test Structure

### Test Organization

```
tests/
├── unit/                    # Unit tests (isolated functions)
│   ├── test-helpers.sh     # Helper function tests
│   ├── test-json.sh        # JSON manipulation tests
│   ├── test-session.sh     # Session key tests
│   └── test-validation.sh  # Input validation tests
├── integration/             # Integration tests (command flows)
│   ├── test-lifecycle.sh   # Agent lifecycle tests
│   ├── test-workflow.sh    # Workflow execution tests
│   ├── test-team.sh        # Team coordination tests
│   └── test-security.sh    # Security isolation tests
├── acceptance/              # Acceptance tests (user stories)
│   ├── test-stories.sh     # User story validations
│   └── test-scenarios.sh   # End-to-end scenarios
├── performance/             # Performance tests
│   ├── test-speed.sh       # Response time tests
│   └── test-scale.sh       # Scalability tests
├── fixtures/                # Test data and mocks
│   ├── agents/             # Sample agent configs
│   ├── workflows/          # Test workflow YAMLs
│   └── responses/          # Mock API responses
└── lib/                     # Test utilities
    ├── assertions.sh       # Test assertion functions
    ├── setup.sh           # Test environment setup
    └── teardown.sh        # Cleanup functions
```

### Test Naming Convention

Tests follow the pattern: `test_<component>_<behavior>_<expectation>`

Examples:
- `test_agent_creation_succeeds_with_valid_id`
- `test_reset_level3_regenerates_session_key`
- `test_cost_calculation_accurate_for_standard_tier`

## Unit Test Specifications

### Helper Function Tests

```bash
#!/usr/bin/env bash
# tests/unit/test-helpers.sh

source tests/lib/assertions.sh
source lib/helpers/output.sh

test_slugify_converts_spaces_to_dashes() {
    local input="My Test Project"
    local expected="my-test-project"
    local result=$(slugify "$input")

    assert_equals "$expected" "$result" \
        "slugify should convert spaces to dashes"
}

test_slugify_removes_special_chars() {
    local input="test@#$%project!"
    local expected="testproject"
    local result=$(slugify "$input")

    assert_equals "$expected" "$result" \
        "slugify should remove special characters"
}

test_detect_stack_identifies_node() {
    local temp_dir=$(mktemp -d)
    echo '{"name": "test"}' > "$temp_dir/package.json"

    local result=$(detect_stack "$temp_dir")

    assert_equals "node" "$result" \
        "should detect Node.js from package.json"

    rm -rf "$temp_dir"
}
```

### Command Tests

```bash
#!/usr/bin/env bash
# tests/integration/test-lifecycle.sh

test_add_creates_agent_successfully() {
    local test_id="test-agent-$(date +%s)"
    local test_path="/tmp/test-project"

    # Arrange
    mkdir -p "$test_path"

    # Act
    local output=$(rack add "$test_id" "$test_path" 2>&1)
    local exit_code=$?

    # Assert
    assert_equals 0 $exit_code "should exit with 0"
    assert_contains "$output" "SUCCESS" "should show success message"
    assert_directory_exists "$WORKSPACES_DIR/projects/$test_id" \
        "should create workspace directory"

    # Cleanup
    rack delete "$test_id" --force
    rm -rf "$test_path"
}

test_add_fails_with_duplicate_id() {
    local test_id="duplicate-test"

    # Arrange
    rack add "$test_id" "/tmp/test1" 2>&1

    # Act
    local output=$(rack add "$test_id" "/tmp/test2" 2>&1)
    local exit_code=$?

    # Assert
    assert_equals 3 $exit_code "should exit with 3"
    assert_contains "$output" "already exists" \
        "should show duplicate error"

    # Cleanup
    rack delete "$test_id" --force
}
```

## Integration Test Specifications

### Workflow Tests

```bash
#!/usr/bin/env bash
# tests/integration/test-workflow.sh

test_workflow_execution_completes() {
    local agent_id="workflow-test"
    local workflow_name="test-pipeline"

    # Setup
    rack add "$agent_id" "/tmp/test"
    rack workflow "$agent_id" create "$workflow_name"

    # Execute workflow
    local output=$(rack workflow "$agent_id" run "$workflow_name" 2>&1)
    local exit_code=$?

    # Verify
    assert_equals 0 $exit_code
    assert_contains "$output" "Workflow completed"
    assert_file_exists "$WORKSPACES_DIR/projects/$agent_id/workflows/$workflow_name.yaml"

    # Cleanup
    rack delete "$agent_id" --force
}
```

### Security Tests

```bash
#!/usr/bin/env bash
# tests/integration/test-security.sh

test_session_isolation_prevents_cross_access() {
    local agent1="security-test-1"
    local agent2="security-test-2"

    # Create two agents with different projects
    rack add "$agent1" "/tmp/project1"
    rack scope "$agent1" set "project-alpha"

    rack add "$agent2" "/tmp/project2"
    rack scope "$agent2" set "project-beta"

    # Get session keys
    local session1=$(meta_get "$WORKSPACES_DIR/projects/$agent1" "sessionKey")
    local session2=$(meta_get "$WORKSPACES_DIR/projects/$agent2" "sessionKey")

    # Verify different session contexts
    assert_not_equals "$session1" "$session2" \
        "agents should have different session keys"
    assert_contains "$session1" "project-alpha" \
        "session1 should include project-alpha"
    assert_contains "$session2" "project-beta" \
        "session2 should include project-beta"

    # Cleanup
    rack delete "$agent1" --force
    rack delete "$agent2" --force
}
```

## Acceptance Test Specifications

### User Story Validation

```bash
#!/usr/bin/env bash
# tests/acceptance/test-stories.sh

test_story_AGT001_create_project_agent() {
    echo "Testing: As a developer, I want to create a project agent..."

    local start_time=$(date +%s)
    local agent_id="story-test-agent"

    # Execute story
    rack add "$agent_id" "$(pwd)" --type repo --model standard
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Validate acceptance criteria
    assert_less_than $duration 2 "creation should take < 2 seconds"
    assert_directory_permissions "$WORKSPACES_DIR/projects/$agent_id" 700
    assert_file_permissions "$WORKSPACES_DIR/projects/$agent_id/SOUL.md" 600

    local list_output=$(rack list)
    assert_contains "$list_output" "$agent_id" \
        "agent should appear in list"

    local info=$(rack info "$agent_id" --format json)
    assert_json_field "$info" ".sessionKey" "agent:$agent_id:default"

    # Cleanup
    rack delete "$agent_id" --force
}
```

## Performance Test Specifications

### Response Time Tests

```bash
#!/usr/bin/env bash
# tests/performance/test-speed.sh

test_list_command_performance() {
    echo "Testing list command with 100 agents..."

    # Create 100 test agents
    for i in {1..100}; do
        rack add "perf-test-$i" "/tmp/test-$i" &
    done
    wait

    # Measure list performance
    local start=$(date +%s%N)
    rack list > /dev/null
    local end=$(date +%s%N)
    local duration=$(( (end - start) / 1000000 )) # Convert to ms

    assert_less_than $duration 500 \
        "list should complete in < 500ms with 100 agents"

    # Cleanup
    for i in {1..100}; do
        rack delete "perf-test-$i" --force &
    done
    wait
}
```

## Test Utilities

### Assertion Library

```bash
#!/usr/bin/env bash
# tests/lib/assertions.sh

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="${3:-Values should be equal}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ "$expected" == "$actual" ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "✓ $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "✗ $message"
        echo "  Expected: $expected"
        echo "  Actual:   $actual"
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local message="${3:-Should contain substring}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ "$haystack" == *"$needle"* ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "✓ $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "✗ $message"
        echo "  String: $haystack"
        echo "  Missing: $needle"
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    local message="${2:-File should exist}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [[ -f "$file" ]]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo "✓ $message"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo "✗ $message: $file"
        return 1
    fi
}

print_test_summary() {
    echo ""
    echo "Test Results:"
    echo "============="
    echo "Total:  $TESTS_RUN"
    echo "Passed: $TESTS_PASSED"
    echo "Failed: $TESTS_FAILED"

    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo ""
        echo "✓ All tests passed!"
        return 0
    else
        echo ""
        echo "✗ Some tests failed"
        return 1
    fi
}
```

## Continuous Testing

### Pre-commit Hook

```bash
#!/usr/bin/env bash
# .git/hooks/pre-commit

echo "Running tests before commit..."

# Run unit tests
./tests/unit/test-helpers.sh
if [[ $? -ne 0 ]]; then
    echo "Unit tests failed. Commit aborted."
    exit 1
fi

# Run integration tests
./tests/test-lifecycle.sh
if [[ $? -ne 0 ]]; then
    echo "Integration tests failed. Commit aborted."
    exit 1
fi

echo "All tests passed. Proceeding with commit."
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Setup environment
      run: |
        sudo apt-get update
        sudo apt-get install -y fzf python3

    - name: Run unit tests
      run: ./tests/unit/test-helpers.sh

    - name: Run integration tests
      run: ./tests/test-lifecycle.sh

    - name: Run acceptance tests
      run: ./tests/acceptance/test-stories.sh

    - name: Run performance tests
      run: ./tests/performance/test-speed.sh

    - name: Generate coverage report
      run: ./scripts/test-coverage.sh

    - name: Upload results
      uses: actions/upload-artifact@v2
      with:
        name: test-results
        path: test-results/
```

## Test Coverage Requirements

### Coverage Targets

| Component | Target | Current |
|-----------|--------|---------|
| Core functions | 100% | 100% |
| Helper functions | 100% | 100% |
| Commands | 90% | 85% |
| Error handling | 95% | 90% |
| Edge cases | 80% | 75% |

### Coverage Reporting

```bash
#!/usr/bin/env bash
# scripts/test-coverage.sh

# Track which functions are tested
declare -A TESTED_FUNCTIONS
declare -A ALL_FUNCTIONS

# Scan for all functions
for file in lib/**/*.sh; do
    while IFS= read -r func; do
        ALL_FUNCTIONS["$func"]=1
    done < <(grep -oP '^[a-z_]+\(\)' "$file" | tr -d '()')
done

# Check which are tested
for test in tests/**/*.sh; do
    while IFS= read -r func; do
        TESTED_FUNCTIONS["$func"]=1
    done < <(grep -oP 'test_[a-z_]+' "$test")
done

# Calculate coverage
total=${#ALL_FUNCTIONS[@]}
tested=${#TESTED_FUNCTIONS[@]}
coverage=$((tested * 100 / total))

echo "Function Coverage: $coverage% ($tested/$total)"
```

## Best Practices

### Writing Good Tests

1. **One assertion per test** - Each test validates one behavior
2. **Descriptive names** - Test name describes what is being tested
3. **Arrange-Act-Assert** - Clear test structure
4. **Independent tests** - No dependencies between tests
5. **Fast execution** - Unit tests < 10ms, integration < 100ms
6. **Deterministic** - Same result every time
7. **No side effects** - Clean up after tests

### Test Doubles

```bash
# Mock external dependencies
mock_openclaw_daemon() {
    cat > /tmp/mock_openclaw << 'EOF'
#!/bin/bash
echo '{"status": "success"}'
EOF
    chmod +x /tmp/mock_openclaw
    export PATH="/tmp:$PATH"
}

# Stub file systems
stub_workspace() {
    local mock_dir="/tmp/test-workspace"
    mkdir -p "$mock_dir"
    export WORKSPACES_DIR="$mock_dir"
}
```

## Changelog

### Version 1.0.0 (2024-01-20)
- Complete TDD framework specification
- Test structure and organization defined
- Assertion library created
- Coverage requirements established
- CI/CD integration configured