# Contributing to rack-cli

Thank you for your interest in contributing to rack-cli! This document provides guidelines and instructions for contributing to this project.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- A clear and descriptive title
- Steps to reproduce the issue
- Expected behavior
- Actual behavior
- Your environment (OS, Bash version, OpenClaw version)
- Any relevant logs or error messages

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- A clear and descriptive title
- Detailed description of the proposed feature
- Use case and motivation
- Any implementation ideas (optional)

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the test suite (`./tests/run-all-tests.sh`)
5. Commit with descriptive messages (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR-USERNAME/rack-cli.git
cd rack-cli

# Create a feature branch
git checkout -b feature/your-feature

# Make changes and test
./tests/run-all-tests.sh

# Run with debug mode for troubleshooting
DEBUG=1 rack <command>
```

## Code Style Guidelines

### Bash Conventions

- Use `set -euo pipefail` for strict error handling
- Follow Google's Shell Style Guide
- Use meaningful variable names (snake_case for locals, UPPER_CASE for globals)
- Add comments for complex logic
- Keep functions focused and under 50 lines when possible

### File Structure

- Command implementations go in `lib/commands/`
- Helper functions go in `lib/helpers/`
- Tests go in `tests/`
- Documentation goes in `docs/`

### Function Template

```bash
# Description: Brief description of function purpose
# Arguments:
#   $1 - Description of first argument
#   $2 - Description of second argument (optional)
# Returns:
#   0 - Success
#   1 - Error
# Example:
#   my_function "arg1" "arg2"
my_function() {
  local arg1="${1:-}"
  local arg2="${2:-default}"

  # Implementation

  return 0
}
```

## Testing

All contributions must include appropriate tests:

- Unit tests for helper functions (`tests/unit/`)
- Integration tests for commands (`tests/test-lifecycle.sh`)

Run tests before submitting:

```bash
# All tests
./tests/run-all-tests.sh

# Unit tests only
./tests/unit/test-helpers.sh

# Integration tests
./tests/test-lifecycle.sh
```

## Documentation

- Update relevant documentation in `docs/`
- Add command documentation to `docs/commands.md`
- Update README.md if adding major features
- Include inline comments for complex logic

## Commit Messages

Follow conventional commit format:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Test updates
- `chore:` Maintenance tasks

Examples:
```
feat: add smart routing configuration
fix: resolve session key parsing issue
docs: update installation instructions
```

## Questions?

Feel free to open an issue for questions or discussions about potential contributions.

Thank you for contributing to rack-cli!