#!/usr/bin/env bash
# Rack CLI Installer
# Installs rack binary and library files to ~/.local/

set -euo pipefail

INSTALL_DIR="${HOME}/.local"
BIN_DIR="${INSTALL_DIR}/bin"
LIB_DIR="${INSTALL_DIR}/lib/rack"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=================================="
echo "  Rack CLI Installer"
echo "=================================="
echo ""

# Create directories
echo "→ Creating installation directories..."
mkdir -p "$BIN_DIR"
mkdir -p "$LIB_DIR"

# Copy library files
echo "→ Copying library files..."
cp -r "$SCRIPT_DIR/lib/"* "$LIB_DIR/"

# Copy binary and make it executable
echo "→ Installing rack binary..."
cat > "$BIN_DIR/rack" <<'EOF'
#!/usr/bin/env bash
# rack — OpenClaw project agent manager (Modular Edition)
#
# Lifecycle commands:
#   rack list                  List all project agents
#   rack add                   Add a new project agent (interactive)
#   rack info   [id]           Detailed status of one project
#   rack delete [id]           Remove agent and optionally its workspace
#   rack reset  [id]           Clear memory, reset heartbeat (keep identity)
#   rack repair [id]           Fix permissions, routing, missing files
#
# Team coordination:
#   rack team status           View team state
#   rack team init             Create manager agent
#   rack team check            Health check for specialists
#
# Session management:
#   rack scope [id] show       Display current scope
#   rack scope [id] set <key>  Change project scope
#   rack scope [id] reset      Reset to default
#
# Workflows:
#   rack workflow [id] list            List workflows
#   rack workflow [id] create <name>   Create from template
#   rack workflow [id] show <name>     Display workflow
#   rack workflow [id] delete <name>   Remove workflow
#
# Telegram commands:
#   rack wire   [id]           Wire or update a Telegram group binding
#   rack unwire [id]           Remove Telegram binding
#
# Utility commands:
#   rack logs    [id]           View memory logs and gateway entries
#   rack edit    [id]           Open workspace files in $EDITOR
#   rack model   [id] [model]   View or change the model for a project
#   rack profile [id] [tier]    Set model profile (economy/standard/premium)
#   rack cost    [id]           Token usage and cost breakdown
#   rack doctor                 System-wide health check
#
# Usage:  rack <command> [agent-id] [args]
#         rack                 (shows list)

# Get library directory (installed in ~/.local/lib/rack)
LIB_DIR="${HOME}/.local/lib/rack"

# Source core modules
source "$LIB_DIR/core/init.sh"
source "$LIB_DIR/core/config.sh"

# Source helper modules
source "$LIB_DIR/helpers/output.sh"
source "$LIB_DIR/helpers/json.sh"
source "$LIB_DIR/helpers/session.sh"
source "$LIB_DIR/helpers/picker.sh"
source "$LIB_DIR/helpers/service.sh"
source "$LIB_DIR/helpers/utils.sh"
source "$LIB_DIR/helpers/workspace.sh"

# Source command modules
source "$LIB_DIR/commands/list.sh"
source "$LIB_DIR/commands/info.sh"
source "$LIB_DIR/commands/add.sh"
source "$LIB_DIR/commands/delete.sh"
source "$LIB_DIR/commands/reset.sh"
source "$LIB_DIR/commands/repair.sh"
source "$LIB_DIR/commands/wire.sh"
source "$LIB_DIR/commands/unwire.sh"
source "$LIB_DIR/commands/logs.sh"
source "$LIB_DIR/commands/edit.sh"
source "$LIB_DIR/commands/model.sh"
source "$LIB_DIR/commands/profile.sh"
source "$LIB_DIR/commands/scope.sh"
source "$LIB_DIR/commands/workflow.sh"
source "$LIB_DIR/commands/cost.sh"
source "$LIB_DIR/commands/doctor.sh"
source "$LIB_DIR/commands/install.sh"
source "$LIB_DIR/commands/team.sh"
source "$LIB_DIR/commands/help.sh"

# Source router
source "$LIB_DIR/core/router.sh"

# Parse arguments
declare -a _ARGS=("$@")
CMD="${_ARGS[0]:-list}"

# Handle --debug flag
if [[ "$CMD" == "--debug" ]]; then
  DEBUG=1
  CMD="${_ARGS[1]:-list}"
  _ARGS=("${_ARGS[@]:1}")
fi

# Route command
route_command "$CMD" "${_ARGS[@]:1}"
EOF

chmod +x "$BIN_DIR/rack"

echo "→ Setting permissions..."
find "$LIB_DIR" -type f -exec chmod 644 {} \;
find "$LIB_DIR" -type d -exec chmod 755 {} \;

echo ""
echo "✓ Installation complete!"
echo ""
echo "Installed to:"
echo "  Binary: $BIN_DIR/rack"
echo "  Library: $LIB_DIR"
echo ""

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
  echo "✓ $BIN_DIR is in your PATH"
else
  echo "⚠  Add $BIN_DIR to your PATH:"
  echo ""
  echo "  For bash, add to ~/.bashrc:"
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo ""
  echo "  For zsh, add to ~/.zshrc:"
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo ""
  echo "  Then run: source ~/.bashrc  (or ~/.zshrc)"
fi

echo ""
echo "Next steps:"
echo "  1. Run: rack install       (sets up OpenClaw)"
echo "  2. Run: rack add           (create your first agent)"
echo "  3. Run: rack doctor        (verify system health)"
echo ""
