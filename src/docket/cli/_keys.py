"""docket keys / docket auth — API key management + honest model-provider-auth status.

``run_keys(sub, extra)`` and ``run_auth(sub, extra)`` return the process exit
code; the coordinator wraps each in a Typer command and raises
``typer.Exit(code)``. Secrets live in ``~/.docket/secrets.json`` /
``secrets.meta.json`` (``core/secrets.py``) — docket-owned JSON written
through ``edges/store.py``.

There is no daemon left to own an interactive OAuth-style provider login flow,
and no docket-native replacement exists yet — rather than silently no-op or
pretend to succeed, every ``docket auth`` subcommand says so plainly and
points at ``docket keys add <PROVIDER>_API_KEY`` as the credential path that
is real today (``edges/adapters/llm.py`` reads the central store directly,
after explicit process/provider overrides).
"""

from __future__ import annotations

import getpass as _getpass
import re as _re
import sys
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.core.utils import project_ids
from docket.edges import store


def _load_secrets() -> dict[str, str]:
    return _secrets.load_secrets()


def _save_secrets(secrets: dict[str, str]) -> None:
    _secrets.save_secrets(secrets)


def _load_secrets_meta() -> dict[str, Any]:
    return _secrets.load_secrets_meta()


def _touch_secrets_meta(name: str, event: str) -> None:
    _secrets.touch_meta(name, event)


_PROVIDER_KEYS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
    "GOOGLE_AI_API_KEY": "google",
    "OPENROUTER_API_KEY": "openrouter",
    "AI_GATEWAY_API_KEY": "ai-gateway",
    "VERCEL_OIDC_TOKEN": "ai-gateway",
    "GROQ_API_KEY": "groq",
    "MISTRAL_API_KEY": "mistral",
    "XAI_API_KEY": "xai",
    "CEREBRAS_API_KEY": "cerebras",
    "HUGGINGFACE_TOKEN": "huggingface",
}

_KEY_PREFIXES: dict[str, tuple[str, int]] = {
    "ANTHROPIC_API_KEY": ("sk-ant-", 40),
    "OPENAI_API_KEY": ("sk-", 40),
    "GOOGLE_AI_API_KEY": ("AIza", 0),
    "OPENROUTER_API_KEY": ("sk-or-", 0),
}

# Stored secrets that are docket's own operational credentials, not a model
# provider's -- these are excluded from `_sync_keys_to_agents`'s per-agent
# .env write. Every project agent's workspace is a wider blast radius than
# the one process that actually needs the credential; `TELEGRAM_BOT_TOKEN`
# is read by `core/telegram.py`/`docket serve` only, and no agent's own turn
# has any legitimate use for docket's channel bot's own token.
_NON_AGENT_KEYS: frozenset[str] = frozenset({_cfg.TELEGRAM_BOT_TOKEN_KEY})


def _mask_key(value: str) -> str:
    if len(value) > 12:
        return value[:4] + "****" + value[-4:]
    return "****"


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty if ok."""
    if name in _KEY_PREFIXES:
        prefix, min_len = _KEY_PREFIXES[name]
        if not value.startswith(prefix):
            return False, f"should start with '{prefix}'"
        if min_len and len(value) < min_len:
            return False, f"too short (< {min_len} chars)"
    return True, ""


def _sync_keys_to_agents() -> None:
    """Write .env files to agent workspaces with their provider keys."""
    secrets = _load_secrets()
    if not secrets:
        return

    for aid in project_ids():
        ws = _cfg.workspace_dir(aid)
        if not ws.is_dir():
            continue
        raw = store.read_json(_cfg.meta_path(aid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        agent_provider = model.split("/")[0] if "/" in model else ""

        env_lines: list[str] = []
        for key_name, key_provider in _PROVIDER_KEYS.items():
            if key_name not in secrets:
                continue
            if key_provider == agent_provider or key_provider not in _PROVIDER_KEYS.values():
                env_lines.append(f'{key_name}="{secrets[key_name]}"')

        for key_name, value in secrets.items():
            if key_name not in _PROVIDER_KEYS and key_name not in _NON_AGENT_KEYS:
                env_lines.append(f'{key_name}="{value}"')

        env_file = ws / ".env"
        env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        env_file.chmod(0o600)


def _keys_list() -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No API keys stored yet.")
        ui.console.print("  Add a key: docket keys add <KEY_NAME>")
        ui.console.print("  Interactive setup: docket keys setup")
        return 0

    ui.header("Stored API Keys")
    ui.console.print()
    meta = _load_secrets_meta()
    for name, value in sorted(secrets.items()):
        masked = _mask_key(value)
        entry = meta.get(name, {})
        added = entry.get("added_at", "")[:10] if entry else ""
        date_str = f"  added {added}" if added else ""
        ok, _ = _validate_key_format(name, value)
        badge = "[green]✓[/green]" if ok else "[yellow]⚠[/yellow]"
        ui.console.print(f"  {badge} {name:<32}  {masked}{date_str}")
    ui.console.print()
    return 0


def _keys_add(name: str) -> int:
    if not _re.match(r"^[A-Z][A-Z0-9_]*$", name):
        ui.error(
            f"Invalid key name '{name}'. Use UPPERCASE_WITH_UNDERSCORES (e.g. ANTHROPIC_API_KEY)."
        )
        return 1

    secrets = _load_secrets()
    if name in secrets:
        ui.warn(f"Key '{name}' already exists. Use 'docket keys rotate' to update it.")
        return 1

    try:
        value = _getpass.getpass(f"Enter value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        return 0

    if not value:
        ui.error("Value cannot be empty.")
        return 1

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "added")
    _sync_keys_to_agents()
    audit_log("keys.add", name)

    ui.success(f"Key '{name}' stored.")
    return 0


def _keys_remove(name: str) -> int:
    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' not found.")
        return 1

    if sys.stdin.isatty():
        ans = input(f"Remove '{name}'? [y/N]: ").strip().lower()
        if ans != "y":
            ui.warn("Cancelled.")
            return 0

    del secrets[name]
    _save_secrets(secrets)
    _touch_secrets_meta(name, "removed")
    _sync_keys_to_agents()
    audit_log("keys.remove", name)

    ui.success(f"Key '{name}' removed.")
    return 0


def _keys_rotate(name: str) -> int:
    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' does not exist. Use 'docket keys add' to create it.")
        return 1

    try:
        value = _getpass.getpass(f"Enter new value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        return 0

    if not value:
        ui.error("Value cannot be empty.")
        return 1

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "rotated")
    _sync_keys_to_agents()
    audit_log("keys.rotate", name)

    ui.success(f"Key '{name}' rotated.")
    return 0


def _keys_validate(name: str | None) -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return 0

    targets = {name: secrets[name]} if name and name in secrets else secrets
    if name and name not in secrets:
        ui.error(f"Key '{name}' not found.")
        return 1

    any_fail = False
    for key_name, value in sorted(targets.items()):
        ok, reason = _validate_key_format(key_name, value)
        if ok:
            ui.console.print(f"  [green]✓[/green] {key_name}")
        else:
            ui.console.print(f"  [yellow]⚠[/yellow] {key_name}: {reason}")
            any_fail = True

    if any_fail:
        return 1
    return 0


def _keys_export() -> int:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return 0

    for name, value in sorted(secrets.items()):
        # Shell-safe: escape single quotes
        safe_value = value.replace("'", "'\\''")
        print(f"export {name}='{safe_value}'")
    return 0


def _keys_setup() -> int:
    if not sys.stdin.isatty():
        ui.error("docket keys setup requires an interactive TTY.")
        return 1

    ui.header("API Key Setup Wizard")
    ui.console.print()
    ui.console.print("Walk through key providers. Press Enter to skip any.")
    ui.console.print()

    providers = [
        ("ANTHROPIC_API_KEY", "Anthropic (Claude)", "sk-ant-"),
        ("OPENAI_API_KEY", "OpenAI (GPT)", "sk-"),
        ("GOOGLE_AI_API_KEY", "Google AI (Gemini)", "AIza"),
        ("OPENROUTER_API_KEY", "OpenRouter", "sk-or-"),
        ("AI_GATEWAY_API_KEY", "Vercel AI Gateway", ""),
    ]

    secrets = _load_secrets()
    changed = False

    for key_name, label, _prefix in providers:
        exists = key_name in secrets
        status = f"[already set: {_mask_key(secrets[key_name])}]" if exists else "[not set]"
        ui.console.print(f"[bold]{label}[/bold] {status}")
        action = input(f"  Configure {key_name}? [y/N]: ").strip().lower()
        if action != "y":
            ui.console.print()
            continue

        try:
            value = _getpass.getpass(f"  {key_name}: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.warn("\nAborted.")
            return 0

        if not value:
            ui.warn("  Skipped (empty).")
            ui.console.print()
            continue

        ok, reason = _validate_key_format(key_name, value)
        if not ok:
            ui.warn(f"  Format warning: {reason}")
            if input("  Save anyway? [y/N]: ").strip().lower() != "y":
                ui.console.print()
                continue

        secrets[key_name] = value
        event = "rotated" if exists else "added"
        _touch_secrets_meta(key_name, event)
        audit_log("keys.rotate" if exists else "keys.add", key_name)
        changed = True
        ui.success(f"  {key_name} saved.")
        ui.console.print()

    if changed:
        _save_secrets(secrets)
        _sync_keys_to_agents()

        ui.success("Keys saved; matching credentials synced to agent workspaces.")
    else:
        ui.info("No changes made.")
    return 0


def run_keys(sub: str | None, extra: list[str]) -> int:
    """Dispatch the keys subcommand. Returns the process exit code.

    sub:   list (default) | add | remove | rotate | validate | export | setup
    extra: trailing positional args (e.g. KEY_NAME) from the Typer context.
    """
    action = sub or "list"

    if action == "list":
        return _keys_list()
    if action == "add":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys add <KEY_NAME>")
            return 1
        return _keys_add(name)
    if action == "remove":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys remove <KEY_NAME>")
            return 1
        return _keys_remove(name)
    if action == "rotate":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys rotate <KEY_NAME>")
            return 1
        return _keys_rotate(name)
    if action == "validate":
        name = extra[0] if extra else None
        return _keys_validate(name)
    if action == "export":
        return _keys_export()
    if action == "setup":
        return _keys_setup()

    ui.console.print("[bold]docket keys — API key management[/bold]")
    ui.console.print()
    ui.console.print("  docket keys list                  Show stored keys (masked)")
    ui.console.print("  docket keys add <KEY_NAME>        Store a new key")
    ui.console.print("  docket keys remove <KEY_NAME>     Remove a key")
    ui.console.print("  docket keys rotate <KEY_NAME>     Update an existing key")
    ui.console.print("  docket keys validate [KEY_NAME]   Check format validity")
    ui.console.print("  docket keys export                Print export statements")
    ui.console.print("  docket keys setup                 Interactive setup wizard")
    ui.console.print()
    return 1


def _extract_provider(extra: list[str], default: str = "anthropic") -> tuple[str, list[str]]:
    """Pull a `--provider <name>` / `--provider=<name>` flag out of ``extra``.

    Returns (provider, remaining_extra). Defaults to "anthropic" when no flag
    is present, for backward compatibility with invocations that predate the
    --provider flag.
    """
    provider = default
    remaining: list[str] = []
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok == "--provider" and i + 1 < len(extra):
            provider = extra[i + 1]
            i += 2
            continue
        if tok.startswith("--provider="):
            provider = tok.split("=", 1)[1]
            i += 1
            continue
        remaining.append(tok)
        i += 1
    return provider, remaining


_AUTH_GONE_MESSAGE = (
    "No docket-native provider-auth flow exists yet (there is no daemon"
    " left to shell out to for an OAuth-like token exchange).\n"
    "  What works today: store a credential directly and docket's own chat client reads it —\n"
    "    docket keys add {env_var}\n"
    "  edges/adapters/llm.py reads that stored key directly; a matching environment variable\n"
    "  remains an optional process-only override."
)

_PROVIDER_ENV_VAR: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_AI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ai-gateway": "AI_GATEWAY_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}


def run_auth(sub: str | None, extra: list[str]) -> int:
    """Dispatch the auth subcommand. Returns the process exit code.

    sub:   status (default) | login | key | setup | choose
    extra: may include `--provider <name>` (defaults to "anthropic").

    There is no docket-native replacement for an interactive provider-login
    flow, so every path below says that plainly rather than silently
    no-op'ing or reporting a fake success — see the module docstring.
    """
    action = sub or "status"
    provider, _rest = _extract_provider(extra)
    env_var = _PROVIDER_ENV_VAR.get(provider, f"{provider.upper()}_API_KEY")

    if action == "status":
        stored = _secrets.secrets_keys()
        present = [name for name in _PROVIDER_ENV_VAR.values() if name in stored]
        if present:
            ui.console.print()
            for name in present:
                ui.console.print(f"  [green]●[/green] {name}  (stored via 'docket keys')")
            ui.console.print()
            ui.success("At least one provider credential is stored.")
        else:
            ui.warn("No provider API keys stored yet.")
        ui.dim(
            f"  No docket-native subscription/OAuth auth exists yet — see: docket auth {provider}"
        )
        return 0

    if action in ("login", "key", "setup", "choose"):
        ui.error(_AUTH_GONE_MESSAGE.format(env_var=env_var))
        return 1

    ui.error(
        f"Unknown auth subcommand '{action}'.\n"
        "Usage:\n"
        "  docket auth                        — show which provider keys are stored\n"
        "  docket keys add <PROVIDER>_API_KEY — the real, working credential path\n"
        "  docket auth login|key|setup        — no docket-native replacement yet"
    )
    return 1
