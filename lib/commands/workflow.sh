#!/usr/bin/env bash
# Command: workflow

cmd_workflow() {
  local id="${1:-}" action="${2:-list}"
  [[ -z "$id" ]] && id=$(pick_project "Manage workflows for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local workflows_dir="$workspace/workflows"

  case "$action" in
    list)
      header "Workflows: $(meta_get "$id" "name" "$id")"
      echo ""

      if [[ ! -d "$workflows_dir" ]]; then
        warn "No workflows directory"
        echo "  Create one: rack workflow $id create"
        return
      fi

      local count; count=$(find "$workflows_dir" -name '*.lobster.y*ml' 2>/dev/null | wc -l | tr -d ' ')
      if [[ "$count" -eq 0 ]]; then
        dim "  No workflows defined yet"
        echo ""
        echo "Create a workflow template:"
        echo "  rack workflow $id create <workflow-name>"
        return
      fi

      echo -e "${BOLD}Defined workflows:${RESET}"
      find "$workflows_dir" -name '*.lobster.y*ml' | while read -r wf; do
        local wf_name; wf_name=$(basename "$wf" | sed 's/\.lobster\.y.*ml$//')
        local steps; steps=$(grep -c '^  - ' "$wf" 2>/dev/null || echo "?")
        printf "  ${GREEN}●${RESET} %-24s %s steps\n" "$wf_name" "$steps"
      done

      echo ""
      echo "Run a workflow:"
      echo "  lobster run --workspace $workspace --workflow <name>"
      echo ""
      ;;

    create)
      local workflow_name="${3:-}"
      [[ -z "$workflow_name" ]] && error_hint "Workflow name required" "Usage: rack workflow $id create <name>"

      mkdir -p "$workflows_dir"
      local wf_file="$workflows_dir/${workflow_name}.lobster.yml"

      if [[ -f "$wf_file" ]]; then
        warn "Workflow '$workflow_name' already exists"
        echo "  Edit: rack edit $id"
        return
      fi

      local stack; stack=$(meta_get "$id" "stack" "")
      local codebase; codebase=$(meta_get "$id" "codebase" "")
      local test_cmd; test_cmd=$(test_cmd_for_stack "$stack")

      cat > "$wf_file" <<LOBSTER
# Lobster Workflow: $workflow_name
# Project: $(meta_get "$id" "name" "$id")
#
# Deterministic pipeline — zero tokens for plumbing
# Only calls LLM for creative work

name: $workflow_name
description: "Automated workflow for $(meta_get "$id" "name" "$id")"

steps:
  - id: check-status
    type: shell
    command: |
      cd $codebase
      git status --short

  - id: run-tests
    type: shell
    command: |
      cd $codebase
      $test_cmd
    continueOnError: false

  - id: llm-analysis
    type: llm
    prompt: |
      Analyze the test results and codebase state.
      Provide a brief summary and suggest next steps.
    approval: required
    # Pauses here and sends Telegram notification

  - id: apply-changes
    type: shell
    command: |
      cd $codebase
      # Apply any changes suggested by LLM
      echo "Changes applied"

  - id: verify
    type: shell
    command: |
      cd $codebase
      $test_cmd

outputs:
  - testResults
  - analysis

notifications:
  onComplete: telegram
  onError: telegram
LOBSTER

      chmod 600 "$wf_file"
      success "Workflow created: $wf_file"

      echo ""
      info "Next steps:"
      echo "  1. Edit workflow: \${EDITOR:-nano} $wf_file"
      echo "  2. Run workflow:  lobster run --workspace $workspace --workflow $workflow_name"
      echo ""
      ;;

    show)
      local workflow_name="${3:-}"
      [[ -z "$workflow_name" ]] && error_hint "Workflow name required" "Usage: rack workflow $id show <name>"

      local wf_file="$workflows_dir/${workflow_name}.lobster.yml"
      [[ ! -f "$wf_file" ]] && error "Workflow '$workflow_name' not found"

      header "Workflow: $workflow_name"
      echo ""
      cat "$wf_file"
      echo ""
      ;;

    delete)
      local workflow_name="${3:-}"
      [[ -z "$workflow_name" ]] && error_hint "Workflow name required" "Usage: rack workflow $id delete <name>"

      local wf_file="$workflows_dir/${workflow_name}.lobster.yml"
      [[ ! -f "$wf_file" ]] && error "Workflow '$workflow_name' not found"

      read -rp "Delete workflow '$workflow_name'? [y/N]: " CONFIRM
      [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }

      rm -f "$wf_file"
      success "Workflow '$workflow_name' deleted"
      ;;

    *)
      error_hint "Unknown action '$action'" "Use: list, create, show, or delete"
      ;;
  esac
}

