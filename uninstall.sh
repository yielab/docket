#!/usr/bin/env bash
# Docket CLI Uninstaller
# Removes docket binary and library files from ~/.local/

set -euo pipefail

# Honor the same prefix install.sh used (DOCKET_PREFIX), defaulting to ~/.local.
INSTALL_DIR="${DOCKET_PREFIX:-${HOME}/.local}"
BIN_FILE="${INSTALL_DIR}/bin/docket"
LIB_DIR="${INSTALL_DIR}/lib/docket-cli"     # Bash lib (pre-cutover installs)
LEGACY_LIB_DIR="${INSTALL_DIR}/lib/docket"  # Python venv (current) / very old layout

echo ""
echo "=================================="
echo "  Docket CLI Uninstaller"
echo "=================================="
echo ""

# Check if docket is installed (current or legacy lib path)
if [[ ! -f "$BIN_FILE" ]] && [[ ! -d "$LIB_DIR" ]] && [[ ! -d "$LEGACY_LIB_DIR" ]]; then
  echo "✓ Docket is not installed"
  exit 0
fi

echo "This will remove:"
if [[ -f "$BIN_FILE" ]]; then
  echo "  • $BIN_FILE"
fi
if [[ -d "$LIB_DIR" ]]; then
  echo "  • $LIB_DIR"
fi
if [[ -d "$LEGACY_LIB_DIR" ]]; then
  echo "  • $LEGACY_LIB_DIR (legacy)"
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
  echo "→ Removing docket binary..."
  rm -f "$BIN_FILE"
  echo "  ✓ Removed $BIN_FILE"
fi

# Remove library directory (current + legacy)
if [[ -d "$LIB_DIR" ]]; then
  echo "→ Removing library files..."
  rm -rf "$LIB_DIR"
  echo "  ✓ Removed $LIB_DIR"
fi
if [[ -d "$LEGACY_LIB_DIR" ]]; then
  rm -rf "$LEGACY_LIB_DIR"
  echo "  ✓ Removed $LEGACY_LIB_DIR (legacy)"
fi

echo ""
echo "✓ Docket uninstalled successfully"
echo ""
DOCKET_HOME_DISPLAY="${DOCKET_HOME:-${HOME}/.docket}"
echo "Note: This does NOT remove ${DOCKET_HOME_DISPLAY} — docket's own state:"
echo "  • agent/pod workspaces (SOUL.md, HEARTBEAT.md, memory/, task ledgers)"
echo "  • the fleet registry, audit log, traces, and API keys (0600 JSON)"
echo ""
echo "That is real, non-recoverable data (memory logs, task history, audit"
echo "trail) — this uninstaller intentionally leaves it in place. To remove it"
echo "yourself once you are sure you no longer need it:"
echo "  rm -rf ${DOCKET_HOME_DISPLAY}"
echo ""
