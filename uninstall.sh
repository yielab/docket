#!/usr/bin/env bash
# Rack CLI Uninstaller
# Removes rack binary and library files from ~/.local/

set -euo pipefail

INSTALL_DIR="${HOME}/.local"
BIN_FILE="${INSTALL_DIR}/bin/rack"
LIB_DIR="${INSTALL_DIR}/lib/rack"

echo ""
echo "=================================="
echo "  Rack CLI Uninstaller"
echo "=================================="
echo ""

# Check if rack is installed
if [[ ! -f "$BIN_FILE" ]] && [[ ! -d "$LIB_DIR" ]]; then
  echo "✓ Rack is not installed"
  exit 0
fi

echo "This will remove:"
if [[ -f "$BIN_FILE" ]]; then
  echo "  • $BIN_FILE"
fi
if [[ -d "$LIB_DIR" ]]; then
  echo "  • $LIB_DIR"
fi
echo ""

read -rp "Continue? [y/N]: " CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""

# Remove binary
if [[ -f "$BIN_FILE" ]]; then
  echo "→ Removing rack binary..."
  rm -f "$BIN_FILE"
  echo "  ✓ Removed $BIN_FILE"
fi

# Remove library directory
if [[ -d "$LIB_DIR" ]]; then
  echo "→ Removing library files..."
  rm -rf "$LIB_DIR"
  echo "  ✓ Removed $LIB_DIR"
fi

echo ""
echo "✓ Rack uninstalled successfully"
echo ""
echo "Note: This does NOT remove:"
echo "  • OpenClaw installation"
echo "  • Agent workspaces (~/.openclaw/workspaces)"
echo "  • OpenClaw config (~/.openclaw/openclaw.json)"
echo ""
echo "To completely remove OpenClaw and all agents, see:"
echo "  https://openclaw.dev/docs/uninstall"
echo ""
