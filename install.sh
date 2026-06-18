#!/usr/bin/env bash
# docket-cli installer — git-clone or curl install.
#
# Usage (from a cloned repo):
#   ./install.sh [--prefix /usr/local]
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/yielab/docket/main/install.sh | bash
#
# Homebrew (macOS/Linux):
#   brew tap yielab/docket-cli https://github.com/yielab/docket
#   brew install docket-cli

set -euo pipefail

PREFIX="${DOCKET_PREFIX:-${HOME}/.local}"
[[ "${1:-}" == "--prefix" ]] && { PREFIX="${2:?--prefix requires a path}"; shift 2; }

BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/docket-cli"

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
if [[ ! -f "${SCRIPT_DIR}/bin/docket" ]]; then
  command -v curl >/dev/null 2>&1 || { echo "Error: curl is required for remote install."; exit 1; }
  tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT
  echo "Downloading docket-cli..."
  curl -fsSL "https://github.com/yielab/docket/archive/refs/heads/main.tar.gz" \
    | tar -xz -C "$tmpdir" --strip-components=1
  SCRIPT_DIR="$tmpdir"
fi

echo ""
echo "Installing docket-cli to ${PREFIX}..."

mkdir -p "$BIN_DIR" "$LIB_DIR"
cp -r "${SCRIPT_DIR}/lib/"* "$LIB_DIR/"
cp    "${SCRIPT_DIR}/bin/docket" "$BIN_DIR/docket"
chmod 755 "$BIN_DIR/docket"

# Ship VERSION beside lib/ so `docket --version` works post-install (the launcher
# checks $LIB_DIR/VERSION in the installed layout). No source-patching needed:
# bin/docket auto-detects the <prefix>/lib/docket-cli layout at runtime.
cp "${SCRIPT_DIR}/VERSION" "$LIB_DIR/VERSION" 2>/dev/null || true

find "$LIB_DIR" -type d -exec chmod 755 {} \;
find "$LIB_DIR" -type f -exec chmod 644 {} \;

echo "✓ Installation complete."
echo ""
echo "  Binary:  $BIN_DIR/docket"
echo "  Library: $LIB_DIR"
echo "  Version: $("$BIN_DIR/docket" --version 2>/dev/null || echo 'n/a')"
echo ""

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  echo "Add ${BIN_DIR} to your PATH (if not already):"
  echo "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.bashrc  # or ~/.zshrc"
  echo ""
fi

echo "Next steps:"
echo "  docket install   — bootstrap OpenClaw + specialist agents"
echo "  docket add       — create your first project agent"
echo "  docket doctor    — verify system health"
echo ""
echo "Optional — shell completions:"
echo "  bash:  echo 'eval \"\$(docket completions bash)\"' >> ~/.bashrc"
echo "  zsh:   echo 'eval \"\$(docket completions zsh)\"' >> ~/.zshrc"
echo ""
