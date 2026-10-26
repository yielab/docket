"""docket-owned secrets storage: ~/.docket/secrets.json + secrets.meta.json.

Provider API keys `docket setup provider` manages, and their bookkeeping metadata
(added/rotated timestamps). Always docket-owned — never an external-runtime file
format — and living under ``DOCKET_HOME``.

Consumers share this module rather than reading files directly: the keys CLI,
doctor checks, model endpoint resolver, and trace redaction. Centralising those
lookups keeps file/keyring behavior and secret handling consistent.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from docket.governance import secrets as _secrets
from docket.kernel import clock as _clock
from docket.kernel.errors import Unavailable
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.platform import read_json, write_json


def load_secrets() -> dict[str, str]:
    """Return the stored {KEY_NAME: value} map ({} if absent/malformed)."""
    raw = read_json(current_home().secrets_file)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def save_secrets(secrets: dict[str, str]) -> None:
    write_json(current_home().secrets_file, secrets)


def load_secrets_meta() -> dict[str, Any]:
    """Return the raw secrets.meta.json contents ({} if absent/malformed)."""
    raw = read_json(current_home().secrets_meta_file)
    return raw if isinstance(raw, dict) else {}


def save_secrets_meta(meta: dict[str, Any]) -> None:
    write_json(current_home().secrets_meta_file, meta)


def secrets_keys() -> set[str]:
    """Return the set of stored key names."""
    return set(load_secrets().keys())


def secret_value(name: str) -> str | None:
    """Resolve one stored secret without exposing unrelated credentials."""
    raw = load_secrets()
    if name not in raw:
        return None
    if _process.secrets_backend_requested() == "keyring" and _process.secret_tool_available():
        value = _process.secret_tool_lookup(current_home().keyring_service, name)
    else:
        value = raw.get(name)
    clean = str(value or "").strip()
    return clean or None


def store_backend() -> str:
    """The backend a credential write goes to: ``"keyring"`` or ``"file"``. Raises ``Unavailable``
    when the keyring was requested and ``secret-tool`` is not on ``PATH``, so a write never
    falls back to plaintext in silence."""
    if _process.secrets_backend_requested() != "keyring":
        return "file"
    if not _process.secret_tool_available():
        raise Unavailable(
            "DOCKET_SECRETS_BACKEND=keyring but secret-tool is not on PATH",
            "Install libsecret-tools, or unset DOCKET_SECRETS_BACKEND to store in secrets.json",
        )
    return "keyring"


def secret_values() -> list[str]:
    """Return the stored secret VALUES (for trace/Telegram redaction).

    Mirrors the file-vs-keyring backend split ``docket setup provider`` uses: the file
    backend stores ``{KEY: value}`` in secrets.json, so the values are the
    dict values; the keyring backend keeps only an index there (no values at
    rest), so it returns nothing. Empty/short values are the caller's concern.
    """
    raw = load_secrets()
    if not raw:
        return []
    backend = "file"
    if _process.secrets_backend_requested() == "keyring" and _process.secret_tool_available():
        backend = "keyring"
    if backend == "keyring":
        service = current_home().keyring_service
        out: list[str] = []
        for key in raw:
            value = _process.secret_tool_lookup(service, str(key))
            if value:
                out.append(value)
        return out
    return [v for v in raw.values() if v]


def touch_meta(name: str, event: str) -> None:
    """Record an add/rotate/remove event for *name* in secrets.meta.json.

    ``event``: "added" | "rotated" | "removed". Mirrors the timestamps
    ``docket setup --fix``'s key-hygiene report reads.
    """

    meta = load_secrets_meta()
    now = _clock.stamp()
    if event == "removed":
        meta.pop(name, None)
    else:
        entry: dict[str, Any] = meta.get(name) or {}
        entry.setdefault("added_at", now)
        if event == "rotated":
            entry["rotated_at"] = now
        meta[name] = entry
    save_secrets_meta(meta)


# Secret-shape patterns stripped from payloads before writing.
# Stored secret values are also redacted after the regex pass (see _stored_secret_values).
#
# Every quantifier here either shares no characters with what follows it, or is capped at
# a length no real identifier/local-part/domain-label exceeds. Payloads handed to redact()
# are untrusted and can be one long unbroken run of alnum characters (base64, a hex dump, a
# minified bundle); an uncapped quantifier immediately followed by a required literal drawn
# from the same character class forces the engine to try every split point in the run
# before it can rule out a match there, which is quadratic (or worse) in the run's length.
# Capping the quantifier bounds that search to a constant per position without narrowing
# which real secrets match -- an env-var name or an email local-part/domain never actually
# runs to thousands of characters, so the cap only ever rejects noise, not a real value.
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk|pk|api|key|tok|secret|bearer|auth|Basic|Bearer)[=:\s]+[A-Za-z0-9/_\-+.]{20,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ANTHROPIC|OPENAI|GOOGLE|OPENROUTER|AI_GATEWAY|VERCEL|COHERE)"
        r"[_A-Z]*[=:\s]+[A-Za-z0-9/_\-+.]{20,}",
        re.IGNORECASE,
    ),
    re.compile(r"[A-Z][A-Z0-9_]{5,40}_(?:API_KEY|SECRET|TOKEN|KEY)\s*[=:]\s*\S+", re.IGNORECASE),
    # Bare vendor tokens with no `key=` prefix: OpenAI/Anthropic `sk-...`, GitHub `gh?_...`,
    # Slack `xox?-...`, and a Telegram bot token (`<digits>:<35 chars>`).
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk-ant-|sk-proj-|sk-|ghp_|gho_|ghs_|xox[abp]-)[A-Za-z0-9_\-]{20,}"
    ),
    re.compile(r"(?<![A-Za-z0-9])\d{8,10}:[A-Za-z0-9_\-]{35}(?![A-Za-z0-9_\-])"),
    # More fixed secret shapes: GitHub fine-grained and OAuth/user/refresh tokens, AWS access key
    # ids, a variable named for a password, a JWT, a PEM private key block and an Authorization
    # header's credential.
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,255}"),
    re.compile(r"(?<![A-Za-z0-9])gh[ur]_[A-Za-z0-9]{36,255}"),
    re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"[A-Z][A-Z0-9_]{0,40}PASSWORD\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_\-]{5,512}\.eyJ[A-Za-z0-9_\-]{5,512}\.[A-Za-z0-9_\-]{5,512}"),
    re.compile(
        r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----(?:[\s\S]{0,8192}?-----END [A-Z ]{0,30}PRIVATE KEY-----)?"
    ),
    re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic|Token)\s+\S{8,512}", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,255}\.[a-zA-Z]{2,24}", re.IGNORECASE),
)


_ENV_CREDENTIAL_NAMES = ("DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN")
_ENV_CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def _stored_secret_values() -> list[str]:
    """Secret values longer than 8 chars (redact.sh's >8 filter): docket's own store plus every
    credential-shaped variable in this process's environment, since a key exported in the shell
    never rests in the store. Best-effort, so redaction never fails a trace write."""
    values: list[str] = []
    with contextlib.suppress(Exception):
        values.extend(v for v in (s.strip() for s in _secrets.secret_values()) if len(v) > 8)
    values.extend(
        v
        for v in _process.credential_env_values(_ENV_CREDENTIAL_NAMES, _ENV_CREDENTIAL_SUFFIXES)
        if len(v) > 8
    )
    return values


def redact(text: str) -> str:
    """Strip secret-shaped substrings from *text*. Applies the always-on
    regex patterns, then redacts the exact VALUES of any stored secrets
    (replaced after the regex pass)."""
    if not text:
        return text
    for pat in _REDACT_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    for value in _stored_secret_values():
        text = text.replace(value, "[REDACTED]")
    return text
