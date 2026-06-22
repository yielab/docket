#!/usr/bin/env bash
# redact — strip secrets from text before writing to traces or sending over Telegram.
# Pure: no I/O. Reads the key registry only for values the user has stored.

# redact <text> → prints sanitized text to stdout.
# Patterns stripped: API key shapes, bearer tokens, emails, stored key values.
redact() {
  local text="$1"
  [[ -z "$text" ]] && return 0

  # Collect stored key values (best-effort; silently skip if unavailable).
  local stored_keys=()
  if declare -f _docket_stored_key_values >/dev/null 2>&1; then
    while IFS= read -r v; do
      [[ -n "$v" ]] && stored_keys+=("$v")
    done < <(_docket_stored_key_values 2>/dev/null)
  fi

  DOCKET_STORED_KEYS="$(printf '%s\n' "${stored_keys[@]+"${stored_keys[@]}"}")" \
    python3 - "$text" <<'PY'
import re, os, sys

text = sys.argv[1]

# Generic secret patterns
PATTERNS = [
    # API keys / bearer tokens (common prefixes + 20+ hex/base64 chars)
    r'(?:sk|pk|api|key|tok|secret|bearer|auth|Basic|Bearer)\s*[=:\s]+[A-Za-z0-9/_\-+.]{20,}',
    # Anthropic / OpenAI style keys
    r'(?:ANTHROPIC|OPENAI|GOOGLE|OPENROUTER|COHERE)[_A-Z]*[=:\s]+[A-Za-z0-9/_\-+.]{20,}',
    # Explicit key= forms
    r'[A-Z][A-Z0-9_]{5,}_(?:API_KEY|SECRET|TOKEN|KEY)\s*[=:]\s*\S+',
    # Email addresses
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
]

for p in PATTERNS:
    text = re.sub(p, '[REDACTED]', text, flags=re.IGNORECASE)

# Redact any stored key values (exact match, replace before regex to avoid ordering issues)
stored = [v.strip() for v in (os.environ.get('DOCKET_STORED_KEYS') or '').splitlines() if len(v.strip()) > 8]
for v in stored:
    text = text.replace(v, '[REDACTED]')

print(text, end='')
PY
}

# Hook: if lib/helpers/secrets.sh is loaded, expose stored key values.
# This function is overridden by secrets.sh when it is sourced.
_docket_stored_key_values() {
  : # no-op by default
}
