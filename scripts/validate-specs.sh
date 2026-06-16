#!/usr/bin/env bash
# Validate all specification documents for completeness and consistency

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
TOTAL_SPECS=0
VALID_SPECS=0
WARNINGS=0
ERRORS=0

# Required sections for each spec type
declare -A REQUIRED_SECTIONS
REQUIRED_SECTIONS["functional"]="Purpose Scope Requirements Interface Examples Validation Changelog"
REQUIRED_SECTIONS["api"]="Purpose Scope Syntax Arguments Options Output Return Validation Changelog"
REQUIRED_SECTIONS["data"]="Purpose Scope Structure Schema Validation Examples Changelog"
REQUIRED_SECTIONS["acceptance"]="Overview Stories Criteria Scenarios Metrics Changelog"
REQUIRED_SECTIONS["validation"]="Purpose Rules Functions Testing Performance Changelog"

# Validate a single spec file
validate_spec() {
    local spec_file="$1"
    local spec_type="$2"
    local errors=()
    local warnings=()

    TOTAL_SPECS=$((TOTAL_SPECS + 1))

    echo -n "Checking $(basename "$spec_file")... "

    # Check file exists
    if [[ ! -f "$spec_file" ]]; then
        echo -e "${RED}✗ File not found${NC}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi

    # Check required sections
    local required="${REQUIRED_SECTIONS[$spec_type]}"
    for section in $required; do
        if ! grep -q "^## $section" "$spec_file" 2>/dev/null; then
            errors+=("Missing section: ## $section")
        fi
    done

    # Check for version
    if ! grep -q "^\*\*Version\*\*:" "$spec_file"; then
        errors+=("Missing version declaration")
    fi

    # Check for status
    if ! grep -q "^\*\*Status\*\*:" "$spec_file"; then
        errors+=("Missing status declaration")
    fi

    # Check for RFC 2119 keywords
    if grep -q "^## Requirements" "$spec_file"; then
        if ! grep -q "\(MUST\|SHALL\|SHOULD\|MAY\)" "$spec_file"; then
            warnings+=("Requirements section should use RFC 2119 keywords")
        fi
    fi

    # Check for examples
    if ! grep -q '```' "$spec_file"; then
        warnings+=("No code examples found")
    fi

    # Check for proper markdown formatting
    if grep -q '^#[^# ]' "$spec_file"; then
        warnings+=("Improper heading format (missing space after #)")
    fi

    # Report results
    if [[ ${#errors[@]} -eq 0 ]] && [[ ${#warnings[@]} -eq 0 ]]; then
        echo -e "${GREEN}✓${NC}"
        VALID_SPECS=$((VALID_SPECS + 1))
    elif [[ ${#errors[@]} -eq 0 ]]; then
        echo -e "${YELLOW}⚠${NC}"
        VALID_SPECS=$((VALID_SPECS + 1))
        for warning in "${warnings[@]}"; do
            echo "    Warning: $warning"
            WARNINGS=$((WARNINGS + 1))
        done
    else
        echo -e "${RED}✗${NC}"
        for error in "${errors[@]}"; do
            echo "    Error: $error"
            ERRORS=$((ERRORS + 1))
        done
        for warning in "${warnings[@]}"; do
            echo "    Warning: $warning"
            WARNINGS=$((WARNINGS + 1))
        done
    fi
}

# Check specification directory structure
check_structure() {
    echo "Validating specification structure..."
    echo ""

    local required_dirs=("functional" "api" "data" "acceptance" "validation")

    for dir in "${required_dirs[@]}"; do
        if [[ ! -d "specs/$dir" ]]; then
            echo -e "${RED}✗ Missing directory: specs/$dir${NC}"
            ERRORS=$((ERRORS + 1))
        else
            echo -e "${GREEN}✓ Found directory: specs/$dir${NC}"
        fi
    done

    echo ""
}

# Validate all specifications
validate_all() {
    echo "Validating functional specifications..."
    for spec in specs/functional/*.spec.md; do
        [[ -f "$spec" ]] && validate_spec "$spec" "functional"
    done
    echo ""

    echo "Validating API specifications..."
    for spec in specs/api/*.spec.md; do
        [[ -f "$spec" ]] && validate_spec "$spec" "api"
    done
    echo ""

    echo "Validating data specifications..."
    for spec in specs/data/*.spec.md; do
        [[ -f "$spec" ]] && validate_spec "$spec" "data"
    done
    echo ""

    echo "Validating acceptance criteria..."
    for spec in specs/acceptance/*.md; do
        [[ -f "$spec" ]] && validate_spec "$spec" "acceptance"
    done
    echo ""

    echo "Validating validation rules..."
    for spec in specs/validation/*.spec.md; do
        [[ -f "$spec" ]] && validate_spec "$spec" "validation"
    done
}

# Check cross-references
check_references() {
    echo ""
    echo "Checking cross-references..."

    # Find all spec references
    local refs; refs=$(grep -r "see [a-z-]*\.spec\.md" specs/ 2>/dev/null | cut -d: -f2- || true)

    if [[ -n "$refs" ]]; then
        while IFS= read -r ref; do
            local filename; filename=$(echo "$ref" | grep -oP '[a-z-]+\.spec\.md')
            if ! find specs -name "$filename" | grep -q .; then
                echo -e "${YELLOW}⚠ Broken reference: $filename${NC}"
                WARNINGS=$((WARNINGS + 1))
            fi
        done <<< "$refs"
    fi
}

# Check for TODOs in specs
check_todos() {
    echo ""
    echo "Checking for incomplete specifications..."

    local todos; todos=$(grep -r "TODO\|FIXME\|XXX" specs/ 2>/dev/null || true)

    if [[ -n "$todos" ]]; then
        echo "$todos" | while IFS= read -r todo; do
            echo -e "${YELLOW}⚠ Found TODO: $todo${NC}"
            WARNINGS=$((WARNINGS + 1))
        done
    fi
}

# Generate validation report
generate_report() {
    echo ""
    echo "================================"
    echo "Specification Validation Report"
    echo "================================"
    echo ""
    echo "Total Specifications: $TOTAL_SPECS"
    echo "Valid Specifications: $VALID_SPECS"
    echo "Errors: $ERRORS"
    echo "Warnings: $WARNINGS"
    echo ""

    if [[ $ERRORS -eq 0 ]] && [[ $WARNINGS -eq 0 ]]; then
        echo -e "${GREEN}✓ All specifications are valid!${NC}"
        return 0
    elif [[ $ERRORS -eq 0 ]]; then
        echo -e "${YELLOW}⚠ Specifications valid with $WARNINGS warnings${NC}"
        return 0
    else
        echo -e "${RED}✗ Specification validation failed with $ERRORS errors${NC}"
        return 1
    fi
}

# Main execution
main() {
    # Check if in project root
    if [[ ! -f "bin/rack" ]]; then
        echo "Error: Must be run from project root directory"
        exit 1
    fi

    # Create specs directory if it doesn't exist
    if [[ ! -d "specs" ]]; then
        echo "Error: specs/ directory not found"
        echo "Run 'mkdir -p specs/{functional,api,data,acceptance,validation}' to create structure"
        exit 1
    fi

    check_structure
    validate_all
    check_references
    check_todos
    generate_report
}

# Run validation
main "$@"