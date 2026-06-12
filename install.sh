#!/usr/bin/env bash
# rack-cli installer — git-clone or curl install.
#
# Usage (from a cloned repo):
#   ./install.sh [--prefix /usr/local]
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/santiagoyie/rack-cli/main/install.sh | bash
#
# Homebrew (macOS/Linux):
#   brew tap santiagoyie/rack-cli https://github.com/santiagoyie/rack-cli
#   brew install rack-cli

set -euo pipefail

PREFIX="${RACK_PREFIX:-${HOME}/.local}"
[[ "${1:-}" == "--prefix" ]] && { PREFIX="${2:?--prefix requires a path}"; shift 2; }

BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/rack-cli"

# Resolve the repo root (works from clone or from piped curl)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-./install.sh}")" && pwd 2>/dev/null)" || SCRIPT_DIR="$PWD"

# ── Preflight ──
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "Error: Bash 4.0+ required (found ${BASH_VERSION})."
  echo "  macOS: brew install bash && exec bash"
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required."; exit 1; }

# When piped from curl, download the tarball instead
if [[ ! -f "${SCRIPT_DIR}/bin/rack" ]]; then
  command -v curl >/dev/null 2>&1 || { echo "Error: curl is required for remote install."; exit 1; }
  tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT
  echo "Downloading rack-cli..."
  curl -fsSL "https://github.com/santiagoyie/rack-cli/archive/refs/heads/main.tar.gz" \
    | tar -xz -C "$tmpdir" --strip-components=1
  SCRIPT_DIR="$tmpdir"
fi

echo ""
echo "Installing rack-cli to ${PREFIX}..."

mkdir -p "$BIN_DIR" "$LIB_DIR"
cp -r "${SCRIPT_DIR}/lib/"* "$LIB_DIR/"
cp    "${SCRIPT_DIR}/bin/rack" "$BIN_DIR/rack"
chmod 755 "$BIN_DIR/rack"

# Patch the installed binary to use the fixed lib path instead of ../lib discovery.
# Use a portable sed -i that works on both GNU and macOS (BSD).
if sed --version 2>/dev/null | grep -q GNU; then
  sed -i "s|LIB_DIR=\"\$(cd \"\\\$SCRIPT_DIR/../lib\" && pwd)\"|LIB_DIR=\"${LIB_DIR}\"|" "$BIN_DIR/rack"
else
  sed -i '' "s|LIB_DIR=\"\$(cd \"\\\$SCRIPT_DIR/../lib\" && pwd)\"|LIB_DIR=\"${LIB_DIR}\"|" "$BIN_DIR/rack"
fi

find "$LIB_DIR" -type d -exec chmod 755 {} \;
find "$LIB_DIR" -type f -exec chmod 644 {} \;

echo "✓ Installation complete."
echo ""
echo "  Binary:  $BIN_DIR/rack"
echo "  Library: $LIB_DIR"
echo "  Version: $("$BIN_DIR/rack" --version 2>/dev/null || echo 'n/a')"
echo ""

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  echo "Add ${BIN_DIR} to your PATH (if not already):"
  echo "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.bashrc  # or ~/.zshrc"
  echo ""
fi

echo "Next steps:"
echo "  rack install   — bootstrap OpenClaw + specialist agents"
echo "  rack add       — create your first project agent"
echo "  rack doctor    — verify system health"
echo ""
