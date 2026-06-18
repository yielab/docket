#!/usr/bin/env bash
# Interactive picker - fzf or numbered fallback

# List project agent IDs (agents whose workspace is under $PROJECTS_DIR)
project_ids() {
  if [[ ! -d "$PROJECTS_DIR" ]]; then echo ""; return; fi
  for dir in "$PROJECTS_DIR"/*/; do
    [[ -d "$dir" ]] && basename "$dir"
  done
}

# List all agent IDs (both project and specialist agents)
all_agent_ids() {
  # Get project agents
  if [[ -d "$PROJECTS_DIR" ]]; then
    for dir in "$PROJECTS_DIR"/*/; do
      [[ -d "$dir" ]] && basename "$dir"
    done
  fi

  # Get specialist agents (direct subdirs of workspaces/)
  if [[ -d "$OPENCLAW_DIR/workspaces" ]]; then
    for dir in "$OPENCLAW_DIR/workspaces"/*/; do
      local agent_id
      agent_id=$(basename "$dir")
      # Skip the projects directory itself
      [[ "$agent_id" == "projects" ]] && continue
      [[ -d "$dir" ]] && echo "$agent_id"
    done
  fi
}

# Interactive project selector using fzf (falls back to numbered list if fzf missing)
pick_project() {
  local prompt="${1:-Select project}"
  local ids; ids=$(project_ids)
  if [[ -z "$ids" ]]; then
    error_hint "No projects found in $PROJECTS_DIR" "Run: docket add"
  fi

  if command -v fzf &>/dev/null; then
    dbg "Using fzf picker"
    local selected
    selected=$(echo "$ids" | fzf --prompt="$prompt > " --height=40% --border --ansi 2>/dev/null || true)
    if [[ -z "$selected" ]]; then
      warn "Selection cancelled."
      exit 0
    fi
    echo "$selected"
  else
    dbg "fzf not found — using numbered fallback"
    warn "fzf not installed. Install with: brew install fzf"
    echo ""
    echo -e "${BOLD}$prompt:${RESET}"
    local i=1
    local -a _items=()
    while IFS= read -r item; do
      printf "  %2d) %s\n" "$i" "$item"
      _items[$i]="$item"
      i=$((i + 1))
    done <<< "$ids"
    echo ""
    read -rp "Enter number [1-$((i-1))]: " _choice
    if [[ -z "${_choice:-}" ]] || [[ -z "${_items[$_choice]:-}" ]]; then
      warn "Invalid selection. Aborted."
      exit 0
    fi
    echo "${_items[$_choice]}"
  fi
}

# Interactive agent selector (includes both projects and specialists)
pick_agent() {
  local prompt="${1:-Select agent}"
  local ids; ids=$(all_agent_ids)
  if [[ -z "$ids" ]]; then
    error "No agents found"
  fi

  if command -v fzf &>/dev/null; then
    dbg "Using fzf picker"
    local selected
    selected=$(echo "$ids" | fzf --prompt="$prompt > " --height=40% --border --ansi 2>/dev/null || true)
    if [[ -z "$selected" ]]; then
      warn "Selection cancelled."
      exit 0
    fi
    echo "$selected"
  else
    dbg "fzf not found — using numbered fallback"
    warn "fzf not installed. Install with: brew install fzf"
    echo ""
    echo -e "${BOLD}$prompt:${RESET}"
    local i=1
    local -a _items=()
    while IFS= read -r item; do
      printf "  %2d) %s\n" "$i" "$item"
      _items[$i]="$item"
      i=$((i + 1))
    done <<< "$ids"
    echo ""
    read -rp "Enter number [1-$((i-1))]: " _choice
    if [[ -z "${_choice:-}" ]] || [[ -z "${_items[$_choice]:-}" ]]; then
      warn "Invalid selection. Aborted."
      exit 0
    fi
    echo "${_items[$_choice]}"
  fi
}
