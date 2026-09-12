#!/usr/bin/env bash
# Apply a reviewed moves.tsv (old_path<TAB>new_path<TAB>lane) produced by
# test_inventory.py: git-mv every row, then rewrite every literal reference to
# the old path across the tree so nothing points at a location that no longer
# exists. Idempotent-ish: re-running after a partial failure skips rows whose
# source is already gone and whose destination already exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MOVES="${1:-.maint/inv/moves.tsv}"
if [ ! -f "$MOVES" ]; then
    echo "apply_moves.sh: moves file not found: $MOVES" >&2
    echo "Generate it first: uv run python scripts/maint/test_inventory.py --out .maint/inv" >&2
    exit 1
fi

echo "== moving files =="
while IFS=$'\t' read -r old new _lane; do
    [ -z "$old" ] && continue
    if [ ! -e "$old" ]; then
        if [ -e "$new" ]; then
            echo "skip (already moved): $old -> $new"
            continue
        fi
        echo "apply_moves.sh: missing source and destination for row: $old -> $new" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$new")"
    git mv "$old" "$new"
    echo "moved: $old -> $new"
done < "$MOVES"

echo "== dropping the now-redundant tests/python package marker =="
if [ -f tests/python/__init__.py ]; then
    git rm -q tests/python/__init__.py
fi
if [ -d tests/python ] && [ -z "$(find tests/python -mindepth 1 2>/dev/null)" ]; then
    rmdir tests/python
fi

echo "== rewriting path references =="
# git grep only searches tracked worktree files, so a moved file's own new
# location is never matched against its own stale self-reference by accident,
# and .git/.maint (untracked/ignored) never need an explicit prune. Pathspecs
# exclude files this card does not own (ROADMAP.md) and history that must stay
# byte-identical (CHANGELOG.md, docs/cycles-ended/**, specs/README.md,
# docs/commands.md, mkdocs.yml, scripts/gen_cli_docs.py).
PATHSPEC_EXCLUDES=(
    ':!ROADMAP.md'
    ':!CHANGELOG.md'
    ':!docs/cycles-ended'
    ':!specs/README.md'
    ':!docs/commands.md'
    ':!mkdocs.yml'
    ':!scripts/gen_cli_docs.py'
)

while IFS=$'\t' read -r old new _lane; do
    [ -z "$old" ] && continue
    # Escape sed's regex metacharacters (only '.' appears in these paths) and
    # its replacement metacharacters ('&', '/', backslash) separately.
    old_pat=$(printf '%s' "$old" | sed 's/[.[\*^$]/\\&/g')
    new_lit=$(printf '%s' "$new" | sed 's/[&/\]/\\&/g')
    matches=$(git grep -lF -- "$old" -- . "${PATHSPEC_EXCLUDES[@]}" 2>/dev/null || true)
    for f in $matches; do
        sed -i "s#${old_pat}#${new_lit}#g" "$f"
    done
done < "$MOVES"

echo "== done =="
