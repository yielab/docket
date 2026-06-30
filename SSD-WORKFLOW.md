# SSD (Spec-Driven Development) Workflow Guide

## Overview

This project strictly follows SSD (Spec-Driven Development) practices to ensure quality, maintainability, and clear requirements. No code should be written without specifications, and all specifications must be validated continuously.

## Core Principles

1. **Specification First**: Write the spec before any code
2. **Test-Driven**: Write tests from specs before implementation
3. **Continuous Validation**: Specs stay in sync with code
4. **Traceability**: Every feature traces back to a spec
5. **Living Documentation**: Specs are the source of truth

## Project Structure for SSD

```
docket/
├── specs/                          # All specifications
│   ├── README.md                  # Spec overview and index
│   ├── functional/                # Feature specifications
│   │   ├── agent-lifecycle.spec.md
│   │   ├── session-scoping.spec.md
│   │   └── workflow.spec.md
│   ├── api/                      # Interface contracts
│   │   ├── cli-interface.spec.md
│   │   └── openclaw-api.spec.md
│   ├── data/                     # Data structures
│   │   └── workspace-structure.spec.md
│   ├── acceptance/               # User stories & criteria
│   │   └── user-stories.md
│   └── validation/              # Validation rules
│       └── input-validation.spec.md
├── scripts/                     # SSD automation
│   ├── validate-specs.sh       # Validate spec format
│   └── spec-coverage.sh        # Check coverage
├── src/docket/                  # Python package (cli/ → core/ → edges/)
└── tests/                       # Test implementation
    ├── python/                  # pytest suite (unit + integration)
    ├── golden/                  # Byte-parity golden suite
    └── evals/                   # Specialist-role evals
```

## Workflow Steps

### 1. Feature Request Phase

When a new feature is requested:

```bash
# Create feature branch
git checkout -b feature/new-feature

# Create specification
cat > specs/functional/new-feature.spec.md << 'EOF'
# New Feature Specification

**Version**: 0.1.0
**Status**: Draft
**Last Updated**: $(date +%Y-%m-%d)

## Purpose
Clear description of what this feature does

## Scope
What is included and what is not

## Requirements
- **MUST** requirement 1
- **SHOULD** requirement 2
- **MAY** optional feature

## Interface
Command syntax and options

## Examples
Usage examples

## Validation
How to verify it works

## Changelog
### Version 0.1.0
- Initial draft
EOF

# Validate specification
./scripts/validate-specs.sh
```

### 2. Specification Review

Before implementation:

1. Review specification with stakeholders
2. Get approval on requirements
3. Update spec status to "Approved"
4. Create acceptance criteria

### 3. Test Development Phase

Write tests BEFORE implementation:

```python
# tests/python/test_new_feature.py
from typer.testing import CliRunner

from docket.cli import app

runner = CliRunner()


def test_new_feature_must_requirement():
    """This test should FAIL initially (red phase)."""
    # Act
    result = runner.invoke(app, ["new-feature", "test-data"])

    # Assert (from spec)
    assert result.exit_code == 0, "should succeed"
    assert "expected output" in result.stdout
```

```bash
# Run the test (should fail — red phase)
uv run pytest tests/python/test_new_feature.py
# ✗ Test fails - this is expected!
```

### 4. Implementation Phase

Now implement to make tests pass. Commands are Typer functions in `src/docket/cli/`; domain
logic lives in `core/` and any I/O goes through `edges/` (`store.py` for docket JSON, the ACL
`edges/adapters/openclaw.py` for OpenClaw state, `edges/adapters/system.py` for shell-outs).

```python
# src/docket/cli/__init__.py  (or a cli/_<group>.py module for a larger group)
import typer

from docket import ui
from docket.cli import app


@app.command("new-feature")
def new_feature(value: str = typer.Argument(...)) -> None:
    """Implementation that satisfies the spec."""
    # Pure logic lives in core/; I/O goes through edges/.
    ui.success("Feature executed successfully")
```

```bash
# Run the tests again
uv run pytest tests/python/test_new_feature.py
# ✓ Tests pass!
```

### 5. Validation Phase

Ensure everything is aligned:

```bash
# Validate specifications
./scripts/validate-specs.sh

# Check coverage
./scripts/spec-coverage.sh

# Run all tests (pytest + golden parity + evals)
./tests/run-all-tests.sh

# Run the CI gates (all blocking)
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
bash tests/golden/run.sh verify-all

# Update spec status
sed -i 's/Status: Draft/Status: Complete/' specs/functional/new-feature.spec.md
```

### 6. Documentation Phase

Update user-facing documentation:

```bash
# Update README
# Update CHANGELOG
# Update help text in src/docket/cli/_help.py
# Commit with spec reference

git add .
git commit -m "Add: new-feature per specs/functional/new-feature.spec.md

- Implements requirements from spec v1.0.0
- All acceptance criteria met
- Tests passing: 15/15"
```

## Specification Standards

### Required Sections

Every specification MUST include:

1. **Version**: Semantic version (X.Y.Z)
2. **Status**: Draft | Review | Approved | Complete | Deprecated
3. **Purpose**: What problem does this solve?
4. **Scope**: Clear boundaries
5. **Requirements**: RFC 2119 keywords (MUST, SHOULD, MAY)
6. **Examples**: Concrete usage examples
7. **Validation**: How to verify compliance
8. **Changelog**: Version history

### RFC 2119 Keywords

Use these consistently:

- **MUST/SHALL**: Absolute requirement
- **MUST NOT**: Absolute prohibition
- **SHOULD**: Strong recommendation
- **SHOULD NOT**: Not recommended
- **MAY**: Truly optional

### Example Specification Template

```markdown
# Feature Name Specification

**Version**: 1.0.0
**Status**: Draft
**Last Updated**: 2024-01-20

## Purpose
One paragraph explaining why this feature exists.

## Scope
This specification covers:
- Item 1
- Item 2

This specification does NOT cover:
- Item A
- Item B

## Requirements

### Functional Requirements
1. The system **MUST** do X
2. The system **SHOULD** support Y
3. The system **MAY** provide Z

### Non-functional Requirements
1. Performance **MUST** be < 2 seconds
2. Memory usage **SHOULD** be < 100MB

## Interface

### Command Syntax
```
docket feature <required> [optional]
```

### Options
- `--flag`: Description

### Return Codes
- 0: Success
- 1: Error

## Examples

### Basic Usage
```bash
docket feature example
# Output: Success
```

## Validation

### Pre-conditions
- Condition 1
- Condition 2

### Post-conditions
- Result 1
- Result 2

### Test Cases
1. Test happy path
2. Test error conditions
3. Test edge cases

## Changelog

### Version 1.0.0 (2024-01-20)
- Initial specification
```

## Continuous Integration

### Pre-commit Hook

Install the pre-commit hook:

```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/usr/bin/env bash

echo "Running SSD validation..."

# Check specs
if ! ./scripts/validate-specs.sh; then
    echo "Specification validation failed!"
    exit 1
fi

# Check coverage
if ! ./scripts/spec-coverage.sh | grep -q "Overall Coverage: [789][0-9]%"; then
    echo "Warning: Specification coverage is low"
fi

# Run tests
if ! ./tests/run-all-tests.sh; then
    echo "Tests failed!"
    exit 1
fi

echo "SSD validation passed ✓"
EOF

chmod +x .git/hooks/pre-commit
```

### GitHub Actions Workflow

```yaml
name: SSD Validation

on: [push, pull_request]

jobs:
  validate-specs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate Specifications
        run: ./scripts/validate-specs.sh

      - name: Check Coverage
        run: |
          ./scripts/spec-coverage.sh --export
          cat specs/coverage-report.md >> $GITHUB_STEP_SUMMARY

      - name: Run Tests
        run: ./tests/run-all-tests.sh

      - name: Upload Coverage Report
        uses: actions/upload-artifact@v4
        with:
          name: spec-coverage
          path: specs/coverage-report.md
```

## Common Patterns

### Adding a New Command

1. Create spec: `specs/functional/command-name.spec.md`
2. Write tests: `tests/python/test_command.py`
3. Implement: a Typer command in `src/docket/cli/` (logic in `core/`, I/O via `edges/`)
4. Update docs: README.md, `src/docket/cli/_help.py`
5. Validate: `./scripts/validate-specs.sh` + the CI gates

### Modifying Existing Feature

1. Update spec with new version
2. Add changelog entry in spec
3. Update tests for new behavior
4. Modify implementation
5. Run full test suite
6. Update documentation

### Deprecating a Feature

1. Mark spec status as "Deprecated"
2. Add deprecation notice to spec
3. Add warning to implementation
4. Plan migration path
5. Set removal date

## Best Practices

### DO:
- ✅ Write specs before code
- ✅ Keep specs up to date
- ✅ Use RFC 2119 keywords consistently
- ✅ Include examples in every spec
- ✅ Version your specs
- ✅ Test against specs, not implementation
- ✅ Review specs in pull requests

### DON'T:
- ❌ Write code without specs
- ❌ Change behavior without updating specs
- ❌ Skip the test-first approach
- ❌ Use vague requirements
- ❌ Ignore validation warnings
- ❌ Let specs become stale

## Troubleshooting

### Spec Validation Fails

```bash
# Check specific issues
./scripts/validate-specs.sh

# Common fixes:
# - Add missing sections
# - Use proper markdown formatting
# - Include version and status
```

### Coverage Too Low

```bash
# Identify gaps
./scripts/spec-coverage.sh

# Focus on:
# - Undocumented commands
# - Missing test coverage
# - Incomplete specifications
```

### Tests Don't Match Specs

```bash
# Review spec requirements
grep "MUST\|SHALL" specs/functional/feature.spec.md

# Ensure each MUST has a test
grep "def test_" tests/python/test_feature.py

# Update tests to match specs exactly
```

## Benefits of SSD

1. **Clear Requirements**: Everyone knows what to build
2. **Test Coverage**: Tests derived from specs are comprehensive
3. **Documentation**: Specs serve as living documentation
4. **Maintainability**: Changes tracked through spec versions
5. **Quality**: Fewer bugs due to clear specifications
6. **Collaboration**: Specs facilitate team communication
7. **Traceability**: Every line of code traces to requirements

## Resources

- [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt) - Requirement Keywords
- [Semantic Versioning](https://semver.org/) - Version numbering
- [TDD Guide](https://martinfowler.com/bliki/TestDrivenDevelopment.html) - Test-first development
- [Living Documentation](https://leanpub.com/livingdocumentation) - Specs as documentation

## Getting Help

- Run `./scripts/validate-specs.sh -h` for validation help
- Run `./scripts/spec-coverage.sh -h` for coverage options
- Check `specs/README.md` for specification index
- Review existing specs in `specs/functional/` for examples

---

Remember: **No code without specs, no specs without tests, no tests without validation!**