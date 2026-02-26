#!/usr/bin/env bash
# Core initialization - strict mode and debug settings

# Strict mode for better error handling
set -euo pipefail

# Debug mode (export DEBUG=1 or pass --debug)
DEBUG="${DEBUG:-0}"
