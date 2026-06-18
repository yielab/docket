#!/usr/bin/env bash
# Check specification coverage for all commands and features

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Coverage tracking
declare -A COMMANDS_COVERED
declare -A FEATURES_COVERED
declare -A TESTS_COVERED

# Scan for all commands in the codebase
scan_commands() {
    echo "Scanning for commands..."

    # Find all cmd_* functions
    local commands; commands=$(grep -h "^cmd_[a-z_]*(" lib/commands/*.sh 2>/dev/null | \
                    sed 's/cmd_//g' | sed 's/().*//g' | sort -u)

    echo "Found commands: $(echo "$commands" | wc -l)"
    echo "$commands"
    echo ""

    # Check if each command has a spec.
    # A command counts as specified only if it has a structured spec entry — a markdown
    # heading naming the command (e.g. "#### docket add" in the API contract) or a dedicated
    # functional spec file. A bare prose mention does NOT count, so the number reflects
    # commands that are actually specified, not merely referenced.
    for cmd in $commands; do
        if grep -rqE "^#+[[:space:]].*\bdocket ${cmd}\b" specs/ 2>/dev/null \
            || [[ -f "specs/functional/${cmd}.spec.md" ]]; then
            COMMANDS_COVERED["$cmd"]=1
            echo -e "${GREEN}✓${NC} $cmd - specified"
        else
            COMMANDS_COVERED["$cmd"]=0
            echo -e "${RED}✗${NC} $cmd - missing specification"
        fi
    done
}

# Scan for features mentioned in specs
scan_features() {
    echo ""
    echo "Scanning feature coverage..."

    # Core features that should be documented
    local features=(
        "agent-lifecycle"
        "session-scoping"
        "workflow-integration"
        "team-coordination"
        "telegram-integration"
        "cost-tracking"
        "model-profiles"
        "api-keys"
        "security-gates"
        "workspace-structure"
    )

    for feature in "${features[@]}"; do
        if [[ -f "specs/functional/${feature}.spec.md" ]]; then
            FEATURES_COVERED["$feature"]=1
            echo -e "${GREEN}✓${NC} $feature - specified"
        else
            FEATURES_COVERED["$feature"]=0
            echo -e "${RED}✗${NC} $feature - missing specification"
        fi
    done
}

# Check test coverage for specs
scan_test_coverage() {
    echo ""
    echo "Scanning test coverage..."

    # Find all test files
    local test_files; test_files=$(find tests -name "*.sh" -type f 2>/dev/null)

    # Map of spec to test patterns. Patterns match how the integration suite actually
    # exercises each feature (it drives real `docket <cmd>` invocations rather than defining
    # test_<cmd>() functions), so a match means the spec's behavior is covered by a test.
    declare -A SPEC_TEST_MAP
    SPEC_TEST_MAP["agent-lifecycle"]="docket add|docket delete|docket info"
    SPEC_TEST_MAP["session-scoping"]="docket scope"
    SPEC_TEST_MAP["workflow"]="docket workflow"
    SPEC_TEST_MAP["team-coordination"]="docket team"
    SPEC_TEST_MAP["cost-tracking"]="docket cost"

    for spec in "${!SPEC_TEST_MAP[@]}"; do
        local pattern="${SPEC_TEST_MAP[$spec]}"
        if grep -rE "$pattern" tests/ >/dev/null 2>&1; then
            TESTS_COVERED["$spec"]=1
            echo -e "${GREEN}✓${NC} $spec - has tests"
        else
            TESTS_COVERED["$spec"]=0
            echo -e "${RED}✗${NC} $spec - missing tests"
        fi
    done
}

# Check acceptance criteria coverage
scan_acceptance() {
    echo ""
    echo "Scanning acceptance criteria..."

    # Count user stories
    local total_stories; total_stories=$(grep -c "^### Story:" specs/acceptance/user-stories.md 2>/dev/null || echo 0)
    local completed_stories; completed_stories=$(grep -B2 "^\- \[x\]" specs/acceptance/user-stories.md 2>/dev/null | \
                            grep -c "^### Story:" || echo 0)

    echo "User Stories: $completed_stories/$total_stories completed"

    # Check for acceptance tests
    if [[ -f "tests/acceptance/test-stories.sh" ]]; then
        local test_count; test_count=$(grep -c "^test_story_" tests/acceptance/test-stories.sh 2>/dev/null || echo 0)
        echo "Acceptance Tests: $test_count implemented"
    else
        echo -e "${RED}Acceptance Tests: Not found${NC}"
    fi
}

# Generate coverage matrix
generate_matrix() {
    echo ""
    echo "================================"
    echo "Specification Coverage Matrix"
    echo "================================"
    echo ""

    # Print header
    printf "%-25s %-10s %-10s %-10s\n" "Component" "Spec" "Tests" "Docs"
    printf "%-25s %-10s %-10s %-10s\n" "-------------------------" "----------" "----------" "----------"

    # Commands coverage
    for cmd in "${!COMMANDS_COVERED[@]}"; do
        local spec_status="${COMMANDS_COVERED[$cmd]}"
        local test_status=0
        local doc_status=0

        # Check if command has tests
        if grep -r "test.*$cmd" tests/ >/dev/null 2>&1; then
            test_status=1
        fi

        # Check if command is in documentation
        if grep -r "docket $cmd" docs/ README.md >/dev/null 2>&1; then
            doc_status=1
        fi

        # Format status symbols
        local spec_symbol; spec_symbol=$([[ $spec_status -eq 1 ]] && echo "✓" || echo "✗")
        local test_symbol; test_symbol=$([[ $test_status -eq 1 ]] && echo "✓" || echo "✗")
        local doc_symbol; doc_symbol=$([[ $doc_status -eq 1 ]] && echo "✓" || echo "✗")

        printf "%-25s %-10s %-10s %-10s\n" "docket $cmd" "$spec_symbol" "$test_symbol" "$doc_symbol"
    done
}

# Calculate overall coverage
calculate_coverage() {
    echo ""
    echo "================================"
    echo "Coverage Summary"
    echo "================================"
    echo ""

    # Command coverage
    local total_commands=${#COMMANDS_COVERED[@]}
    local covered_commands=0
    for cmd in "${!COMMANDS_COVERED[@]}"; do
        [[ ${COMMANDS_COVERED[$cmd]} -eq 1 ]] && covered_commands=$((covered_commands + 1))
    done
    local cmd_coverage; cmd_coverage=$((covered_commands * 100 / total_commands))

    # Feature coverage
    local total_features=${#FEATURES_COVERED[@]}
    local covered_features=0
    for feature in "${!FEATURES_COVERED[@]}"; do
        [[ ${FEATURES_COVERED[$feature]} -eq 1 ]] && covered_features=$((covered_features + 1))
    done
    local feature_coverage; feature_coverage=$((covered_features * 100 / total_features))

    # Test coverage
    local total_specs=${#TESTS_COVERED[@]}
    local covered_specs=0
    for spec in "${!TESTS_COVERED[@]}"; do
        [[ ${TESTS_COVERED[$spec]} -eq 1 ]] && covered_specs=$((covered_specs + 1))
    done
    local test_coverage; test_coverage=$((covered_specs * 100 / total_specs))

    # Display results
    echo "Command Specification Coverage: ${cmd_coverage}% ($covered_commands/$total_commands)"
    echo "Feature Specification Coverage: ${feature_coverage}% ($covered_features/$total_features)"
    echo "Test Coverage for Specs: ${test_coverage}% ($covered_specs/$total_specs)"
    echo ""

    # Overall status
    local overall; overall=$((cmd_coverage + feature_coverage + test_coverage))
    overall=$((overall / 3))

    if [[ $overall -ge 90 ]]; then
        echo -e "${GREEN}Overall Coverage: ${overall}% - Excellent!${NC}"
    elif [[ $overall -ge 70 ]]; then
        echo -e "${YELLOW}Overall Coverage: ${overall}% - Good, but improvements needed${NC}"
    else
        echo -e "${RED}Overall Coverage: ${overall}% - Needs significant work${NC}"
    fi
}

# Generate recommendations
generate_recommendations() {
    echo ""
    echo "================================"
    echo "Recommendations"
    echo "================================"
    echo ""

    local has_recommendations=false

    # Check for missing command specs
    for cmd in "${!COMMANDS_COVERED[@]}"; do
        if [[ ${COMMANDS_COVERED[$cmd]} -eq 0 ]]; then
            echo "• Create specification for 'docket $cmd' command"
            has_recommendations=true
        fi
    done

    # Check for missing feature specs
    for feature in "${!FEATURES_COVERED[@]}"; do
        if [[ ${FEATURES_COVERED[$feature]} -eq 0 ]]; then
            echo "• Document $feature feature in specs/functional/"
            has_recommendations=true
        fi
    done

    # Check for missing tests
    for spec in "${!TESTS_COVERED[@]}"; do
        if [[ ${TESTS_COVERED[$spec]} -eq 0 ]]; then
            echo "• Write tests for $spec specification"
            has_recommendations=true
        fi
    done

    if [[ $has_recommendations == false ]]; then
        echo -e "${GREEN}No critical recommendations - excellent coverage!${NC}"
    fi
}

# Export coverage report
export_report() {
    local report_file="specs/coverage-report.md"

    {
        echo "# Specification Coverage Report"
        echo ""
        echo "Generated: $(date)"
        echo ""
        echo "## Summary"
        echo ""

        # Command coverage
        local total_commands=${#COMMANDS_COVERED[@]}
        local covered_commands=0
        for cmd in "${!COMMANDS_COVERED[@]}"; do
            [[ ${COMMANDS_COVERED[$cmd]} -eq 1 ]] && covered_commands=$((covered_commands + 1))
        done

        echo "- Commands: $covered_commands/$total_commands covered"
        echo "- Features: ${#FEATURES_COVERED[@]} tracked"
        echo "- Tests: ${#TESTS_COVERED[@]} specifications tested"
        echo ""

        echo "## Command Coverage"
        echo ""
        echo "| Command | Specified | Tested | Documented |"
        echo "|---------|-----------|--------|------------|"

        for cmd in "${!COMMANDS_COVERED[@]}"; do
            local spec_status="${COMMANDS_COVERED[$cmd]}"
            local test_status; test_status=$([[ $(grep -r "test.*$cmd" tests/ 2>/dev/null | wc -l) -gt 0 ]] && echo "✓" || echo "✗")
            local doc_status; doc_status=$([[ $(grep -r "docket $cmd" docs/ README.md 2>/dev/null | wc -l) -gt 0 ]] && echo "✓" || echo "✗")
            local spec_symbol; spec_symbol=$([[ $spec_status -eq 1 ]] && echo "✓" || echo "✗")

            echo "| docket $cmd | $spec_symbol | $test_status | $doc_status |"
        done

    } > "$report_file"

    echo ""
    echo "Report exported to: $report_file"
}

# Main execution
main() {
    # Check if in project root
    if [[ ! -f "bin/docket" ]]; then
        echo "Error: Must be run from project root directory"
        exit 1
    fi

    echo -e "${BLUE}Docket CLI Specification Coverage Analysis${NC}"
    echo "========================================="
    echo ""

    scan_commands
    scan_features
    scan_test_coverage
    scan_acceptance
    generate_matrix
    calculate_coverage
    generate_recommendations

    # Export if requested
    if [[ "${1:-}" == "--export" ]]; then
        export_report
    fi
}

# Run analysis
main "$@"