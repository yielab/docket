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
DOCKET_VERSION="${DOCKET_VERSION:-0.2.0-beta.1}"
[[ "${1:-}" == "--prefix" ]] && { PREFIX="${2:?--prefix requires a path}"; shift 2; }

BIN_DIR="${PREFIX}/bin"

# Resolve the repo root (works from clone or from piped curl)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-./install.sh}")" && pwd 2>/dev/null)" || SCRIPT_DIR="$PWD"

# ── Preflight ──
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "Error: Bash 4.0+ required (found ${BASH_VERSION})."
  echo "  macOS: brew install bash && exec bash"
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required."; exit 1; }

# Python 3.11+ is required by the docket package (pyproject requires-python >=3.11).
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "Error: Python 3.11+ is required (found $(python3 -V 2>&1))."
  exit 1
fi

# When piped from curl, download the tarball instead
if [[ ! -f "${SCRIPT_DIR}/bin/docket" ]]; then
  command -v curl >/dev/null 2>&1 || { echo "Error: curl is required for remote install."; exit 1; }
  tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT
  release="docket-v${DOCKET_VERSION}.tar.gz"
  release_url="https://github.com/yielab/docket/releases/download/v${DOCKET_VERSION}/${release}"
  archive="${tmpdir}/${release}"
  checksum="${archive}.sha256"
  echo "Downloading docket-cli v${DOCKET_VERSION}..."
  curl -fsSL "$release_url" -o "$archive"
  curl -fsSL "${release_url}.sha256" -o "$checksum"
  expected_sha=$(awk 'NR == 1 {print $1}' "$checksum")
  if command -v sha256sum >/dev/null 2>&1; then
    actual_sha=$(sha256sum "$archive" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual_sha=$(shasum -a 256 "$archive" | awk '{print $1}')
  else
    echo "Error: sha256sum or shasum is required to verify the release checksum."
    exit 1
  fi
  if [[ ! "$expected_sha" =~ ^[0-9a-fA-F]{64}$ || "$actual_sha" != "$expected_sha" ]]; then
    echo "Error: release checksum verification failed; refusing to extract ${release}."
    exit 1
  fi
  echo "✓ Release checksum verified."
  tar -xzf "$archive" -C "$tmpdir" --strip-components=1
  SCRIPT_DIR="$tmpdir"
fi

echo ""
echo "Installing docket to ${PREFIX}..."

# docket is a Python package behind a thin launcher. Install the package into a
# dedicated venv — isolated, and avoids PEP 668 "externally-managed-environment"
# errors common on Homebrew/Debian Python — then generate a launcher that execs
# that venv's interpreter via `python -m docket` (so aliases/--version, handled
# in docket.__main__, work). The Bash lib/ was removed at the M6 cutover.
VENV_DIR="${PREFIX}/lib/docket/venv"
mkdir -p "$BIN_DIR" "$(dirname "$VENV_DIR")"

echo "→ Creating Python venv at ${VENV_DIR} ..."
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

echo "→ Installing the docket package ..."
if ! "$VENV_DIR/bin/python" -m pip install --quiet "${SCRIPT_DIR}"; then
  echo "Error: failed to install the docket Python package into the venv."
  exit 1
fi
"$VENV_DIR/bin/python" -c 'import docket' 2>/dev/null \
  || { echo "Error: docket not importable after install."; exit 1; }

echo "→ Writing launcher ${BIN_DIR}/docket ..."
cat > "$BIN_DIR/docket" <<LAUNCHER
#!/usr/bin/env bash
# docket launcher — execs the packaged CLI in its dedicated venv.
exec "${VENV_DIR}/bin/python" -m docket "\$@"
LAUNCHER
chmod 755 "$BIN_DIR/docket"

echo ""
echo "✓ Installation complete."
echo ""
echo "  Binary:  $BIN_DIR/docket"
echo "  Venv:    $VENV_DIR"
echo "  Version: $("$BIN_DIR/docket" --version 2>/dev/null || echo 'n/a')"
echo ""

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
  echo "Add ${BIN_DIR} to your PATH (if not already):"
  echo "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.bashrc  # or ~/.zshrc"
  echo ""
fi

echo "Next steps:"
echo "  docket install   — bootstrap docket's home + specialist agents"
echo "  docket add       — create your first project pod"
echo "  docket doctor    — verify system health"
echo ""
echo "Optional — shell completions:"
echo "  bash:  echo 'eval \"\$(docket completions bash)\"' >> ~/.bashrc"
echo "  zsh:   echo 'eval \"\$(docket completions zsh)\"' >> ~/.zshrc"
echo ""
