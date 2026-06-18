#!/usr/bin/env bash
# Pluggable secret-storage backend (Phase 0).
#
#   file    (default) — 0600 ~/.openclaw/secrets.json holds {KEY: value}.
#   keyring           — values live in the OS keyring (libsecret `secret-tool`);
#                       secrets.json keeps a names-only index (empty values) so
#                       listing/sync still enumerate keys without secrets at rest.
#
# Select the keyring backend with DOCKET_SECRETS_BACKEND=keyring; it transparently
# falls back to file when no keyring tool is available. Secret VALUES are always
# passed via stdin/env or assembled inside Python — never via argv (which is
# world-readable through /proc) and never interpolated into source. See
# internal-docs/SECURITY-GATES-FEASIBILITY.md siblings / ROADMAP Phase 0.

_secrets_file() { echo "$OPENCLAW_DIR/secrets.json"; }

# Name of the keyring CLI to use, or non-zero if none is available.
_keyring_tool() {
  command -v secret-tool >/dev/null 2>&1 && { echo "secret-tool"; return 0; }
  return 1   # macOS 'security' backend is a documented TODO
}

# Resolve the effective backend (with availability fallback).
secrets_backend() {
  case "${DOCKET_SECRETS_BACKEND:-file}" in
    keyring) _keyring_tool >/dev/null 2>&1 && echo "keyring" || echo "file" ;;
    *)       echo "file" ;;
  esac
}

# Ensure the names index exists at 0600.
_secrets_ensure_index() {
  local f; f=$(_secrets_file)
  [[ -f "$f" ]] || { echo '{}' > "$f"; chmod 600 "$f"; }
}

# secret_put <KEY>   — store; value read from $DOCKET_KEY_VALUE.
secret_put() {
  local key="$1"
  _secrets_ensure_index
  local f; f=$(_secrets_file)
  if [[ "$(secrets_backend)" == "keyring" ]]; then
    printf '%s' "${DOCKET_KEY_VALUE:-}" \
      | secret-tool store --label="docket-cli: $key" service "${DOCKET_KEYRING_SERVICE:-docket-cli}" key "$key" >/dev/null 2>&1 \
      || { fail "keyring store failed for $key"; return 1; }
    DOCKET_KEY_VALUE="" _keys_store "$f" "$key"   # index entry only (no value at rest)
  else
    _keys_store "$f" "$key"                      # injection-safe file writer (keys.sh)
  fi
}

# secret_get <KEY>   — echo the value (empty if missing).
secret_get() {
  local key="$1"
  if [[ "$(secrets_backend)" == "keyring" ]]; then
    secret-tool lookup service "${DOCKET_KEYRING_SERVICE:-docket-cli}" key "$key" 2>/dev/null || true
  else
    local f; f=$(_secrets_file)
    [[ -f "$f" ]] || return 0
    python3 -c "import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2],''))
except Exception: pass" "$f" "$key" 2>/dev/null
  fi
}

# secret_has <KEY>   — exit 0 if the key exists in the index.
secret_has() {
  local key="$1" f; f=$(_secrets_file)
  [[ -f "$f" ]] || return 1
  python3 -c "import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])) else 1)" \
    "$f" "$key" 2>/dev/null
}

# secret_del <KEY>   — remove from keyring (if applicable) and the index.
secret_del() {
  local key="$1" f; f=$(_secrets_file)
  [[ "$(secrets_backend)" == "keyring" ]] && secret-tool clear service "${DOCKET_KEYRING_SERVICE:-docket-cli}" key "$key" >/dev/null 2>&1
  [[ -f "$f" ]] || return 0
  python3 - "$f" "$key" <<'PYEOF'
import json, os, sys
path, key = sys.argv[1], sys.argv[2]
with open(path) as f: secrets = json.load(f)
secrets.pop(key, None)
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(secrets, f, indent=2); f.write("\n")
os.chmod(tmp, 0o600); os.replace(tmp, path)
PYEOF
}

# secret_names      — echo stored key names, one per line.
secret_names() {
  local f; f=$(_secrets_file)
  [[ -f "$f" ]] || return 0
  python3 -c "import json,sys
try:
    [print(k) for k in json.load(open(sys.argv[1])).keys()]
except Exception: pass" "$f" 2>/dev/null
}

# secret_export_json — echo a full {KEY: value} JSON object. For the keyring
# backend, values are pulled from the keyring inside Python (never via bash
# argv). Used by the agent .env sync, which needs real values.
secret_export_json() {
  _secrets_ensure_index
  local f; f=$(_secrets_file)
  if [[ "$(secrets_backend)" == "keyring" ]]; then
    python3 - "$f" <<'PYEOF'
import json, os, subprocess, sys
idx = json.load(open(sys.argv[1]))
service = os.environ.get("DOCKET_KEYRING_SERVICE", "docket-cli")
out = {}
for k in idx:
    r = subprocess.run(["secret-tool", "lookup", "service", service, "key", k],
                       capture_output=True, text=True)
    out[k] = r.stdout
json.dump(out, sys.stdout)
PYEOF
  else
    cat "$f"
  fi
}
