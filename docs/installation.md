# Installation Guide

Complete guide to installing and configuring rack for OpenClaw agent management.

## Prerequisites

### Required

- **Operating System**: Linux or macOS
- **Bash**: Version 4.0 or higher
- **Python**: Version 3.7 or higher
- **OpenClaw**: Latest version from [openclaw.dev](https://openclaw.dev)
- **systemctl**: For service management (usually pre-installed)

### Optional

- **fzf**: Fuzzy finder for enhanced interactive selection
  ```bash
  # macOS
  brew install fzf

  # Ubuntu/Debian
  sudo apt install fzf

  # Arch Linux
  sudo pacman -S fzf
  ```

- **numfmt**: For human-readable token counts (from GNU coreutils)
- **jq**: For manual JSON inspection

## Installation Methods

### Method 1: Quick Install (Recommended)

The quick install script will:
1. Clone the repository
2. Install rack to `/usr/local/bin`
3. Set proper permissions
4. Run initial setup

```bash
curl -fsSL https://raw.githubusercontent.com/yourusername/rack-cli/main/install.sh | bash
```

Then bootstrap OpenClaw:
```bash
rack install
```

### Method 2: Manual Installation

#### Step 1: Clone Repository

```bash
cd ~/Downloads  # or your preferred location
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli
```

#### Step 2: Make Executable

```bash
chmod +x bin/rack
```

#### Step 3: Add to PATH

**Option A: Symlink (recommended)**
```bash
sudo ln -s "$(pwd)/bin/rack" /usr/local/bin/rack
```

**Option B: Update shell profile**
```bash
# For bash
echo 'export PATH="$PATH:'"$(pwd)/bin"'"' >> ~/.bashrc
source ~/.bashrc

# For zsh
echo 'export PATH="$PATH:'"$(pwd)/bin"'"' >> ~/.zshrc
source ~/.zshrc
```

#### Step 4: Bootstrap OpenClaw

```bash
rack install
```

This will:
- Check dependencies
- Initialize OpenClaw configuration
- Create specialist agents (programmer, reviewer, tester, etc.)
- Configure security sentinel
- Set up workspace directories
- Start the gateway service

### Method 3: Development Installation

For contributing or testing:

```bash
# Clone repository
git clone https://github.com/yourusername/rack-cli.git
cd rack-cli

# Run in development mode (no PATH modification needed)
./bin/rack --help

# Run tests
./tests/test-lifecycle.sh
```

## Post-Installation

### Verify Installation

```bash
# Check rack is available
rack --help

# Check version
rack doctor

# View system status
rack list
```

### Configure Telegram (Optional)

1. **Get OpenClaw Telegram Bot**
   - Follow OpenClaw documentation to create a bot
   - Store bot token in OpenClaw config

2. **Create Telegram Groups**
   - Create a group for each project agent
   - Add your bot to each group
   - Send a test message in each group

3. **Wire Agents**
   ```bash
   # Get group IDs from logs
   tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log

   # Wire each agent
   rack wire myproject
   # Enter group ID when prompted
   ```

### First Project Setup

```bash
# Add your first project
rack add

# Interactive prompts will guide you through:
# 1. Project type (repo or task)
# 2. Display name
# 3. Codebase path (for repo type)
# 4. Description
# 5. Tech stack (auto-detected)
# 6. Model selection
# 7. Telegram group (optional)

# Verify creation
rack info myproject
```

## Troubleshooting

### rack: command not found

**Solution**: Ensure rack is in your PATH
```bash
# Check if symlink exists
ls -l /usr/local/bin/rack

# Or add to PATH manually
export PATH="$PATH:/path/to/rack-cli/bin"
```

### OpenClaw not found

**Solution**: Install OpenClaw
```bash
# Follow instructions at https://openclaw.dev
# Or check your package manager
brew install openclaw  # macOS
```

### Permission denied

**Solution**: Fix permissions
```bash
chmod +x bin/rack
# Or
sudo chmod +x /usr/local/bin/rack
```

### Gateway service not starting

**Solution**: Check systemd
```bash
# View service status
systemctl --user status openclaw-gateway.service

# Check logs
journalctl --user -u openclaw-gateway.service -f

# Restart service
systemctl --user restart openclaw-gateway.service
```

### Python 3 not found

**Solution**: Install Python
```bash
# Ubuntu/Debian
sudo apt install python3

# macOS
brew install python3

# Verify version
python3 --version  # Should be 3.7+
```

### Specialist agents missing

**Solution**: Re-run installation
```bash
# This will recreate missing agents
rack install

# Or check what's missing
rack team check
```

## Upgrading

### From Previous Versions

```bash
# Pull latest changes
cd /path/to/rack-cli
git pull origin main

# Re-run installation
rack install

# Verify upgrade
rack doctor
```

### Backup Before Upgrade

```bash
# Backup OpenClaw config
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.backup-$(date +%s)

# Backup project workspaces
tar -czf ~/openclaw-workspaces-backup-$(date +%s).tar.gz \
  ~/.openclaw/workspaces/projects
```

## Uninstallation

### Remove rack Only

```bash
# Remove symlink
sudo rm /usr/local/bin/rack

# Or remove from PATH in shell profile
# Edit ~/.bashrc or ~/.zshrc and remove rack PATH entry
```

### Complete Removal (Including OpenClaw)

```bash
# Stop gateway
systemctl --user stop openclaw-gateway.service

# Disable service
systemctl --user disable openclaw-gateway.service

# Backup data (optional)
tar -czf ~/openclaw-backup-$(date +%s).tar.gz ~/.openclaw

# Remove OpenClaw directory
rm -rf ~/.openclaw

# Remove rack
sudo rm /usr/local/bin/rack
```

## Next Steps

- [Read the Commands Documentation](commands.md)
- [Understand the Architecture](architecture.md)
- [Follow the Quick Start Tutorial](../README.md#quick-start)
- [Configure Team Coordination](../README.md#team-coordination)
