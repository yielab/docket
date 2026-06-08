#!/usr/bin/env bash
# Command: context - Agent context & memory management (replaces memory)

cmd_context() {
  local id="${1:-}"
  local subcmd="${2:-show}"
  shift 2 2>/dev/null || shift 1 2>/dev/null || true

  [[ -z "$id" ]] && id=$(pick_project "Select agent")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Agent '$id' not found"

  case "$subcmd" in
    show)       _context_show     "$id" "$workspace" ;;
    search)     _context_search   "$id" "$workspace" "$@" ;;
    snapshot)   _context_snapshot "$id" "$workspace" ;;
    index)      _context_index    "$id" "$workspace" ;;
    compress)   _context_compress "$id" "$workspace" ;;
    project)    _context_project  "$id" "$workspace" ;;
    *)
      # Bare word with no hyphen is treated as a search query
      if [[ -n "$subcmd" && "$subcmd" != "-"* ]]; then
        _context_search "$id" "$workspace" "$subcmd" "$@"
      else
        _context_show "$id" "$workspace"
      fi
      ;;
  esac
}

_context_show() {
  local id="$1" workspace="$2"

  header "Context: $(meta_get "$id" "name" "$id")"
  echo ""

  echo "${BOLD}Recent Activity${RESET}"
  echo "────────────────────────────────────────────────────────────"

  local memory_dir="$workspace/memory"
  if [[ -d "$memory_dir" ]]; then
    local recent_logs; recent_logs=$(find "$memory_dir" -name "*.md" -type f | sort -r | head -3)
    if [[ -z "$recent_logs" ]]; then
      dim "  No activity logs found"
    else
      while IFS= read -r log_file; do
        local date; date=$(basename "$log_file" .md)
        echo ""
        echo "${CYAN}$date${RESET}"
        tail -10 "$log_file" | head -5
      done <<< "$recent_logs"
    fi
  else
    dim "  No memory directory"
  fi

  echo ""
  echo ""

  if [[ -f "$workspace/HEARTBEAT.md" ]]; then
    echo "${BOLD}Active Tasks${RESET}"
    echo "────────────────────────────────────────────────────────────"
    local tasks; tasks=$(grep -E "^- \[" "$workspace/HEARTBEAT.md" | head -5)
    if [[ -n "$tasks" ]]; then
      echo "$tasks"
    else
      dim "  No active tasks"
    fi
    echo ""
    echo ""
  fi

  echo "${BOLD}Gateway Activity${RESET}"
  echo "────────────────────────────────────────────────────────────"
  if [[ -f "$LOG_FILE" ]]; then
    local agent_logs; agent_logs=$(grep "$id" "$LOG_FILE" 2>/dev/null | tail -5)
    if [[ -n "$agent_logs" ]]; then
      echo "$agent_logs" | cut -c1-100
    else
      dim "  No recent gateway activity"
    fi
  else
    dim "  No gateway log for today"
  fi

  echo ""
  echo ""

  echo "${BOLD}Context Statistics${RESET}"
  echo "────────────────────────────────────────────────────────────"
  local memory_dir="$workspace/memory"
  local log_count=0
  [[ -d "$memory_dir" ]] && log_count=$(find "$memory_dir" -name "*.md" -type f | wc -l)

  local latest_session
  latest_session=$(ls -t "$HOME/.openclaw/agents/$id/sessions/" 2>/dev/null | head -1)
  local session_size=0
  if [[ -n "$latest_session" && -f "$HOME/.openclaw/agents/$id/sessions/$latest_session" ]]; then
    session_size=$(stat -c%s "$HOME/.openclaw/agents/$id/sessions/$latest_session" 2>/dev/null \
      || stat -f%z "$HOME/.openclaw/agents/$id/sessions/$latest_session" 2>/dev/null || echo 0)
  fi
  local size_mb; size_mb=$(python3 -c "print(f'{$session_size / 1048576:.1f}')" 2>/dev/null || echo "0.0")

  echo "  Memory logs: $log_count"
  echo "  Session size: ${size_mb}MB"
  echo "  Last activity: $(last_activity "$id")"

  echo ""
  echo ""
  echo "${BOLD}Quick Actions${RESET}"
  echo "────────────────────────────────────────────────────────────"
  echo "  Search memory:    ${GREEN}rack context $id search <query>${RESET}"
  echo "  Create snapshot:  ${GREEN}rack context $id snapshot${RESET}"
  echo "  Index memory:     ${GREEN}rack context $id index${RESET}"
  echo "  Compress old:     ${GREEN}rack context $id compress${RESET}"
  echo "  Project summary:  ${GREEN}rack context $id project${RESET}"
}

_context_index() {
  local id="$1" workspace="$2"
  local memory_dir="$workspace/memory"
  [[ ! -d "$memory_dir" ]] && { warn "No memory directory"; return; }

  header "Indexing Memory: $(meta_get "$id" "name" "$id")"
  echo ""
  info "Scanning memory files..."

  local memory_index="$workspace/.memory-index.json"
  python3 - "$memory_dir" "$memory_index" <<'PY'
import json, sys, os, re
from pathlib import Path
from datetime import datetime

memory_dir  = Path(sys.argv[1])
index_file  = sys.argv[2]

index = {
    "indexed_at": datetime.now().isoformat(),
    "files": [], "keywords": {}, "decisions": []
}

for log_file in sorted(memory_dir.glob("*.md")):
    if log_file.name.startswith("MEMORY"):
        continue
    try:
        content = log_file.read_text()
        entries = content.split('\n## ')
        index["files"].append({
            "path": str(log_file), "date": log_file.stem,
            "size": len(content), "entries": len(entries),
            "preview": content[:200].replace('\n', ' ')
        })
        for kw_tuple in re.findall(r'\*\*([^*]+)\*\*|`([^`]+)`', content):
            kw = (kw_tuple[0] or kw_tuple[1]).lower()
            if len(kw) > 3:
                index["keywords"].setdefault(kw, []).append(log_file.stem)
    except Exception as e:
        print(f"Warning: could not index {log_file}: {e}", file=sys.stderr)

memory_md = memory_dir.parent / "MEMORY.md"
if memory_md.exists():
    content = memory_md.read_text()
    for title, body in re.findall(r'^## (.+?)$(.+?)(?=^## |\Z)', content, re.MULTILINE | re.DOTALL):
        index["decisions"].append({"title": title.strip(), "preview": body.strip()[:200]})

with open(index_file, 'w') as f:
    json.dump(index, f, indent=2)

print(f"Indexed {len(index['files'])} files, {len(index['keywords'])} keywords, {len(index['decisions'])} decisions")
PY

  success "Memory indexed: $workspace/.memory-index.json"
  echo ""
}

_context_search() {
  local id="$1" workspace="$2"
  shift 2
  local query="$*"
  [[ -z "$query" ]] && error "Search query required. Usage: rack context $id search <query>"

  local memory_index="$workspace/.memory-index.json"
  if [[ ! -f "$memory_index" ]]; then
    warn "Memory not indexed. Run: rack context $id index"
    return 1
  fi

  header "Search: $query"
  echo ""

  python3 - "$memory_index" "$query" <<'PY'
import json, sys

index  = json.load(open(sys.argv[1]))
query  = sys.argv[2].lower()
matches = []
for kw, dates in index["keywords"].items():
    if query in kw:
        matches.extend(dates)

decision_matches = [d for d in index["decisions"]
    if query in d["title"].lower() or query in d["preview"].lower()]

if decision_matches:
    print("Architectural Decisions:")
    for d in decision_matches[:5]:
        print(f"  • {d['title']}")
        print(f"    {d['preview'][:80]}...")
        print()

matches = sorted(set(matches), reverse=True)
if matches:
    print(f"Found in logs ({len(matches)} dates):")
    for date in matches[:10]:
        print(f"  • {date}")
elif not decision_matches:
    print("No matches found")
PY
}

_context_snapshot() {
  local id="$1" workspace="$2"
  local snapshot_file="$workspace/SNAPSHOT.md"
  local codebase; codebase=$(meta_get "$id" "codebase" "")
  local stack;    stack=$(meta_get "$id" "stack" "")

  header "Memory Snapshot: $(meta_get "$id" "name" "$id")"
  echo ""
  info "Creating snapshot..."

  cat > "$snapshot_file" <<SNAPSHOT
# Project Snapshot — $(date +%Y-%m-%d)

**Auto-generated** — fast-access context for agents

## Metadata
- **Project:** $(meta_get "$id" "name" "$id")
- **Codebase:** $codebase
- **Stack:** $stack
- **Model:** $(meta_get "$id" "model" "$DEFAULT_MODEL")
- **Session Key:** $(meta_get "$id" "sessionKey" "")

## Current State
$(if [[ -f "$workspace/HEARTBEAT.md" ]]; then
  echo "### Active Tasks"
  head -20 "$workspace/HEARTBEAT.md"
fi)

## Recent Activity (Last 7 Days)
$(find "$workspace/memory" -name "*.md" -mtime -7 2>/dev/null | sort -r | head -5 | while read -r log; do
  echo "### $(basename "$log" .md)"
  head -10 "$log" | tail -5
  echo ""
done)

## Architectural Decisions
$(if [[ -f "$workspace/MEMORY.md" ]]; then
  head -50 "$workspace/MEMORY.md"
fi)

## Quick Stats
- Total memory files: $(find "$workspace/memory" -name "*.md" 2>/dev/null | wc -l)
- Last activity: $(last_activity "$id")
- Size: $(du -sh "$workspace" 2>/dev/null | awk '{print $1}')

---
*Snapshot valid for 24h — regenerate if stale*
SNAPSHOT

  chmod 600 "$snapshot_file"
  success "Snapshot created: $snapshot_file"
  echo ""
  dim "Agents can read SNAPSHOT.md instead of full conversation history"
  echo ""
}

_context_compress() {
  local id="$1" workspace="$2"
  local memory_dir="$workspace/memory"
  [[ ! -d "$memory_dir" ]] && { warn "No memory directory"; return; }

  header "Compress Memory: $(meta_get "$id" "name" "$id")"
  echo ""
  info "Finding logs older than 30 days..."

  local archive_dir="$memory_dir/archive"
  mkdir -p "$archive_dir"

  local compressed=0
  while IFS= read -r log_file; do
    if [[ -f "$log_file" ]]; then
      gzip -9 "$log_file"
      mv "${log_file}.gz" "$archive_dir/"
      (( compressed++ ))
    fi
  done < <(find "$memory_dir" -maxdepth 1 -name "*.md" -mtime +30 -not -name "MEMORY.md")

  if [[ "$compressed" -eq 0 ]]; then
    success "No old logs to compress"
  else
    success "Compressed $compressed log file(s) → $archive_dir"
  fi
  echo ""
}

_context_project() {
  local id="$1" workspace="$2"

  header "Project Quick-Reference: $(meta_get "$id" "name" "$id")"
  echo ""

  echo -e "${BOLD}Metadata${RESET}"
  echo "  Codebase: $(meta_get "$id" "codebase" "")"
  echo "  Stack:    $(meta_get "$id" "stack" "")"
  echo "  Model:    $(meta_get "$id" "model" "$DEFAULT_MODEL")"
  echo "  Session:  $(meta_get "$id" "sessionKey" "")"
  echo ""

  if [[ -f "$workspace/HEARTBEAT.md" ]]; then
    echo -e "${BOLD}Active Tasks${RESET}"
    grep -E "^- \[" "$workspace/HEARTBEAT.md" | head -5 || dim "  none"
    echo ""
  fi

  if [[ -f "$workspace/MEMORY.md" ]]; then
    echo -e "${BOLD}Recent Decisions${RESET}"
    grep -E "^## " "$workspace/MEMORY.md" | head -5 | sed 's/^## /  • /' || true
    echo ""
  fi

  echo -e "${BOLD}Activity${RESET}"
  echo "  Last update:   $(last_activity "$id")"
  echo "  Memory files:  $(find "$workspace/memory" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')"
  echo ""
  dim "→ Full context: rack context $id snapshot"
  echo ""
}
