"""System adapter: typed wrappers over docker, sandbox-exec, and git.

Every shell-out to a container runtime, sandbox tool, or git lives here. Every subprocess call
catches FileNotFoundError / TimeoutExpired / OSError and degrades gracefully so a missing binary
never crashes a command. Functions are module-level and typed so callers can monkeypatch them.
Imports ``docket.core.security`` for ``match_high_risk``. ``run_command`` is the only function
here that runs a free-form command through a real shell (``shell=True``); every other function
builds a fixed argv itself -- see ``specs/functional/security-gates.spec.md`` for the scoping
rationale, which also covers the exec-sandbox section below (mechanism only; the decision to use
one belongs to ``core/tools.py``'s ``ToolContext.sandbox``).
"""

from __future__ import annotations

import os


def env_value(name: str) -> str:
    """One environment variable, stripped; ``""`` when unset. Read live, for the credential names
    a provider or exporter document declares."""
    return os.environ.get(name, "").strip()


def credential_env_values(names: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
    """The stripped, non-empty values of every variable that is in *names* or ends in one of
    *suffixes*, so a key exported in the shell after startup is seen. Read live."""
    values = []
    for name, raw in os.environ.items():
        if name in names or name.endswith(suffixes):
            value = raw.strip()
            if value:
                values.append(value)
    return values


def secrets_backend_requested() -> str:
    """Which stored-secret backend the operator asked for: ``"keyring"`` (secret-tool/libsecret)
    or the default ``"file"`` (secrets.json). Read live, never cached: a change made in the
    environment mid-process takes effect on the next call. Whether ``secret-tool`` exists is
    ``secret_tool_available``."""
    return os.environ.get("DOCKET_SECRETS_BACKEND", "file")


def no_trace() -> bool:
    """True when DOCKET_NO_TRACE=1 asks every trace write to be a no-op. Read live."""
    return os.environ.get("DOCKET_NO_TRACE", "0") == "1"


def no_export() -> bool:
    """True when DOCKET_NO_EXPORT=1 asks every export queue and flush action to be a no-op.
    Read live."""
    return os.environ.get("DOCKET_NO_EXPORT", "0") == "1"
