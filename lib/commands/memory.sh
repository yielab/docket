#!/usr/bin/env bash
# Command: memory — Intelligent memory management for agents

cmd_memory() {
  local subcommand="${1:-}"

  case "$subcommand" in
    index)
      shift
      _memory_index "$@"
      ;;
    search)
      shift
      _memory_search "$@"
      ;;
    snapshot)
      shift
      _memory_snapshot "$@"
      ;;
    compress)
      shift
      _memory_compress "$@"
      ;;
    project)
      shift
      _memory_project "$@"
      ;;
    *)
      _memory_help
      ;;
  esac
}

_memory_help() {
  header "Memory Management"
  echo ""
  echo "Efficient context management for agents — avoid large context passing"
  echo ""
  echo -e "${BOLD}Usage:${RESET}"
  echo "  rack memory index <agent-id>           Index agent memory for fast search"
  echo "  rack memory search <agent-id> <query>  Search indexed memory"
  echo "  rack memory snapshot <agent-id>        Create current state snapshot"
  echo "  rack memory compress <agent-id>        Compress old memory logs"
  echo "  rack memory project <agent-id>         Show project quick-reference"
  echo ""
  echo -e "${BOLD}Examples:${RESET}"
  echo "  rack memory index myproject"
  echo "  rack memory search myproject 'authentication bug'"
  echo "  rack memory snapshot myproject"
  echo ""
}

_memory_index() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Index memory for")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found"

  local memory_dir="$workspace/memory"
  [[ ! -d "$memory_dir" ]] && { warn "No memory directory"; return; }

  header "Indexing Memory: $(meta_get "$id" "name" "$id")"
  echo ""

  info "Scanning memory files..."
  local memory_index="$workspace/.memory-index.json"

  # Build index with file paths, dates, and first 100 chars of each entry
  python3 - "$memory_dir" "$memory_index" <<'PY'
import json, sys, os, re
from pathlib import Path
from datetime import datetime

memory_dir = Path(sys.argv[1])
index_file = sys.argv[2]

index = {
    "indexed_at": datetime.now().isoformat(),
    "files": [],
    "keywords": {},
    "decisions": []
}

# Index daily logs
for log_file in sorted(memory_dir.glob("*.md")):
    if log_file.name.startswith("MEMORY"):
        continue

    try:
        content = log_file.read_text()
        entries = content.split('\n## ')

        file_entry = {
            "path": str(log_file),
            "date": log_file.stem,
            "size": len(content),
            "entries": len(entries),
            "preview": content[:200].replace('\n', ' ')
        }
        index["files"].append(file_entry)

        # Extract keywords (words in **bold** or `code`)
        keywords = re.findall(r'\*\*([^*]+)\*\*|`([^`]+)`', content)
        for kw_tuple in keywords:
            kw = (kw_tuple[0] or kw_tuple[1]).lower()
            if len(kw) > 3:
                if kw not in index["keywords"]:
                    index["keywords"][kw] = []
                index["keywords"][kw].append(log_file.stem)

    except Exception as e:
        print(f"Warning: could not index {log_file}: {e}", file=sys.stderr)

# Index architectural decisions from MEMORY.md
memory_md = memory_dir.parent / "MEMORY.md"
if memory_md.exists():
    content = memory_md.read_text()
    sections = re.findall(r'^## (.+?)$(.+?)(?=^## |\Z)', content, re.MULTILINE | re.DOTALL)
    for title, body in sections:
        index["decisions"].append({
            "title": title.strip(),
            "preview": body.strip()[:200]
        })

with open(index_file, 'w') as f:
    json.dump(index, f, indent=2)

print(f"Indexed {len(index['files'])} files, {len(index['keywords'])} keywords, {len(index['decisions'])} decisions")
PY

  success "Memory indexed: $memory_index"
  echo ""

  # Show stats
  local file_count; file_count=$(python3 -c "import json; print(len(json.load(open('$memory_index'))['files']))")
  local keyword_count; keyword_count=$(python3 -c "import json; print(len(json.load(open('$memory_index'))['keywords']))")

  echo "  Files: $file_count"
  echo "  Keywords: $keyword_count"
  echo ""
}

_memory_search() {
  local id="${1:-}"
  local query="${2:-}"

  [[ -z "$id" ]] && { error "Agent ID required"; return 1; }
  [[ -z "$query" ]] && { error "Search query required"; return 1; }

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found"

  local memory_index="$workspace/.memory-index.json"
  [[ ! -f "$memory_index" ]] && {
    warn "Memory not indexed. Run: rack memory index $id"
    return 1
  }

  header "Search Results: $query"
  echo ""

  # Search index
  python3 - "$memory_index" "$query" <<'PY'
import json, sys, re

index_file = sys.argv[1]
query = sys.argv[2].lower()

index = json.load(open(index_file))

# Search keywords
matches = []
for keyword, dates in index["keywords"].items():
    if query in keyword:
        matches.extend(dates)

# Search decisions
decision_matches = []
for decision in index["decisions"]:
    if query in decision["title"].lower() or query in decision["preview"].lower():
        decision_matches.append(decision)

# Deduplicate and sort
matches = sorted(set(matches), reverse=True)

if decision_matches:
    print("Architectural Decisions:")
    for d in decision_matches[:5]:
        print(f"  • {d['title']}")
        print(f"    {d['preview'][:80]}...")
        print()

if matches:
    print(f"Found in logs ({len(matches)} dates):")
    for date in matches[:10]:
        print(f"  • {date}")
else:
    print("No matches found")
PY
}

_memory_snapshot() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Snapshot memory for")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found"

  header "Memory Snapshot: $(meta_get "$id" "name" "$id")"
  echo ""

  local snapshot_file="$workspace/SNAPSHOT.md"
  local codebase; codebase=$(meta_get "$id" "codebase" "")
  local stack; stack=$(meta_get "$id" "stack" "")

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
$(find "$workspace/memory" -name "*.md" -mtime -7 | sort -r | head -5 | while read -r log; do
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

_memory_compress() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Compress memory for")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found"

  local memory_dir="$workspace/memory"
  [[ ! -d "$memory_dir" ]] && { warn "No memory directory"; return; }

  header "Memory Compression: $(meta_get "$id" "name" "$id")"
  echo ""

  info "Finding logs older than 30 days..."

  local archive_dir="$memory_dir/archive"
  mkdir -p "$archive_dir"

  local compressed=0
  while IFS= read -r log_file; do
    if [[ -f "$log_file" ]]; then
      local basename; basename=$(basename "$log_file")
      gzip -9 "$log_file"
      mv "${log_file}.gz" "$archive_dir/"
      compressed=$((compressed + 1))
      dbg "Compressed: $basename"
    fi
  done < <(find "$memory_dir" -maxdepth 1 -name "*.md" -mtime +30 -not -name "MEMORY.md")

  if [[ $compressed -eq 0 ]]; then
    success "No old logs to compress"
  else
    success "Compressed $compressed log files → $archive_dir"
  fi

  echo ""
}

_memory_project() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Show project reference for")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found"

  header "Project Quick-Reference: $(meta_get "$id" "name" "$id")"
  echo ""

  # Core metadata
  echo -e "${BOLD}Metadata${RESET}"
  echo "  Codebase: $(meta_get "$id" "codebase" "")"
  echo "  Stack: $(meta_get "$id" "stack" "")"
  echo "  Model: $(meta_get "$id" "model" "$DEFAULT_MODEL")"
  echo "  Session: $(meta_get "$id" "sessionKey" "")"
  echo ""

  # Active tasks
  if [[ -f "$workspace/HEARTBEAT.md" ]]; then
    echo -e "${BOLD}Active Tasks${RESET}"
    head -10 "$workspace/HEARTBEAT.md" | grep -E "^- \[" | head -5
    echo ""
  fi

  # Recent decisions
  if [[ -f "$workspace/MEMORY.md" ]]; then
    echo -e "${BOLD}Recent Decisions${RESET}"
    grep -E "^## " "$workspace/MEMORY.md" | head -5 | sed 's/^## /  • /'
    echo ""
  fi

  # Last activity
  echo -e "${BOLD}Activity${RESET}"
  echo "  Last update: $(last_activity "$id")"
  echo "  Memory files: $(find "$workspace/memory" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')"
  echo ""

  dim "→ Read SNAPSHOT.md for full context (rack memory snapshot $id)"
  echo ""
}
