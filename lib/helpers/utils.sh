#!/usr/bin/env bash
# Utility helpers - slugify, stack detection, etc.

# ── Portable primitives (avoid GNU-only flags) ────────────────────────────────

# File mtime in epoch seconds (GNU coreutils stat vs BSD/macOS stat).
file_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

# File size in bytes (GNU vs BSD).
file_size() { stat -c %s "$1" 2>/dev/null || stat -f %z "$1" 2>/dev/null; }

# File mode as octal (GNU vs BSD).
file_mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null; }

# Newest file in <dir> matching shell glob <pattern>, by mtime. Portable
# replacement for `find -printf '%T@ %p'` (GNU-only). Echoes the path, or nothing.
# Usage: newest_file <dir> <glob>
newest_file() {
  local dir="$1" pat="$2" f t best=0 newest=""
  for f in "$dir"/$pat; do
    [[ -e "$f" ]] || continue
    t=$(file_mtime "$f"); [[ -z "$t" ]] && continue
    if (( t > best )); then best="$t"; newest="$f"; fi
  done
  [[ -n "$newest" ]] && echo "$newest"
}

# In-place edit that works on both GNU and BSD sed (whose -i syntax differs).
# Usage: portable_sed_i <sed-expr> <file>
portable_sed_i() {
  local expr="$1" file="$2" tmp
  tmp=$(mktemp) || return 1
  if sed "$expr" "$file" > "$tmp" 2>/dev/null; then
    cat "$tmp" > "$file"   # preserve original mode/inode; don't mv across perms
    rm -f "$tmp"
  else
    rm -f "$tmp"; return 1
  fi
}

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//'
}

# Last memory file date (returns date string from most recent YYYY-MM-DD.md or "—")
last_activity() {
  local id="$1"
  local mem_dir="$PROJECTS_DIR/$id/memory"
  if [[ -d "$mem_dir" ]]; then
    local latest
    latest=$(find "$mem_dir" -maxdepth 1 -name '*.md' 2>/dev/null | sort | tail -1)
    if [[ -n "$latest" ]]; then
      basename "$latest" .md
    else
      echo "—"
    fi
  else
    echo "—"
  fi
}

# Detect tech stack from codebase by inspecting manifest files
detect_stack() {
  local path="$1"; local stack=()

  # Runtime / language markers
  [[ -f "$path/package.json" ]]                                && stack+=("Node.js")
  [[ -f "$path/composer.json" ]]                               && stack+=("PHP")
  [[ -f "$path/requirements.txt" || -f "$path/pyproject.toml" ]] && stack+=("Python")
  [[ -f "$path/Gemfile" ]]                                     && stack+=("Ruby")
  [[ -f "$path/go.mod" ]]                                      && stack+=("Go")
  [[ -f "$path/Cargo.toml" ]]                                  && stack+=("Rust")
  [[ -f "$path/pom.xml" ]]                                     && stack+=("Java/Maven")
  [[ -f "$path/docker-compose.yml" || -f "$path/Dockerfile" ]] && stack+=("Docker")
  [[ -d "$path/.git" ]]                                        && stack+=("git")

  # JS/TS framework hints (from package.json dependencies)
  if [[ -f "$path/package.json" ]]; then
    grep -q '"next"'       "$path/package.json" 2>/dev/null && stack+=("Next.js")
    grep -q '"react"'      "$path/package.json" 2>/dev/null && stack+=("React")
    grep -q '"vue"'        "$path/package.json" 2>/dev/null && stack+=("Vue")
    grep -q '"fastify"'    "$path/package.json" 2>/dev/null && stack+=("Fastify")
    grep -q '"express"'    "$path/package.json" 2>/dev/null && stack+=("Express")
    grep -q '"typescript"' "$path/package.json" 2>/dev/null && stack+=("TypeScript")
  fi

  # Python framework hints
  if [[ -f "$path/requirements.txt" ]]; then
    grep -qi "fastapi" "$path/requirements.txt" 2>/dev/null && stack+=("FastAPI")
    grep -qi "django"  "$path/requirements.txt" 2>/dev/null && stack+=("Django")
    grep -qi "flask"   "$path/requirements.txt" 2>/dev/null && stack+=("Flask")
    grep -qi "pytest"  "$path/requirements.txt" 2>/dev/null && stack+=("pytest")
  fi

  # PHP framework hints
  if [[ -f "$path/composer.json" ]]; then
    grep -q '"drupal"'   "$path/composer.json" 2>/dev/null && stack+=("Drupal")
    grep -q '"laravel"'  "$path/composer.json" 2>/dev/null && stack+=("Laravel")
    grep -q '"symfony"'  "$path/composer.json" 2>/dev/null && stack+=("Symfony")
  fi

  local IFS=", "; echo "${stack[*]:-unknown}"
}

test_cmd_for_stack() {
  local s="$1"
  echo "$s" | grep -q "pytest\|Python\|FastAPI\|Django\|Flask" && { echo "pytest -v"; return; }
  echo "$s" | grep -q "Node\|npm\|Next\|React\|Express\|Fastify" && { echo "npm test"; return; }
  echo "$s" | grep -q "PHP\|Drupal\|Laravel" && { echo "./vendor/bin/phpunit"; return; }
  echo "$s" | grep -q "Go" && { echo "go test ./..."; return; }
  echo "$s" | grep -q "Rust" && { echo "cargo test"; return; }
  echo "# add test command"
}
