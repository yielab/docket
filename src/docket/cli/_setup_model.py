"""The model setup commands: `setup provider` (endpoints and credentials) and `setup model`."""

from __future__ import annotations

import contextlib
import getpass as _getpass
import os
import re as _re
import sys
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.core import models_policy as _mp
from docket.core import provider as _prov
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.edges.adapters import system as _system

provider_app = typer.Typer(
    name="provider",
    help="Model endpoints and their credentials.",
    no_args_is_help=True,
)
model_app = typer.Typer(
    name="model",
    no_args_is_help=False,
    invoke_without_command=True,
)

_DEFAULT_CTX = 16384
_DEFAULT_MAX_TOKENS = 8192
_KEY_NAME = _re.compile(r"^[A-Z][A-Z0-9_]*$")


def _say(text: str = "") -> None:
    ui.console.print(escape(text))


# -- credentials ---------------------------------------------------------------------------


def _keyring_active() -> bool:
    return _cfg.secrets_backend_requested() == "keyring" and _system.secret_tool_available()


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """(ok, reason); the prefix hint comes from the catalog entry that declares ``name``."""
    prefix = ""
    for spec in _prov.load_catalog().entries.values():
        if name in spec.auth.credentials and spec.credential_prefix:
            prefix = spec.credential_prefix
            break
    if prefix and not value.startswith(prefix):
        return False, f"should start with '{prefix}'"
    return True, ""


def _write_credential(name: str, value: str, event: str) -> bool:
    """Store ``value`` (keyring or 0600 file), touch the meta and audit ``keys.<event>``."""
    secrets = _secrets.load_secrets()
    if _keyring_active():
        if not _system.secret_tool_store(_cfg.KEYRING_SERVICE, name, value):
            ui.error(
                f"Could not store {name} in the OS keyring",
                "It is not stored in plaintext under DOCKET_SECRETS_BACKEND=keyring",
            )
            return False
        secrets[name] = ""
    else:
        secrets[name] = value
    _secrets.save_secrets(secrets)
    meta_event = "added" if event == "add" else "rotated"
    _secrets.touch_meta(name, meta_event)
    audit_log(f"keys.{event}", name)
    return True


def _read_hidden(name: str, label: str = "Enter value for") -> str | None:
    try:
        return _getpass.getpass(f"{label} {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("Aborted.")
        return None


def prompt_and_store(name: str) -> bool:
    """Prompt for ``name`` on a hidden line and store it; ``False`` on an empty or failed entry."""
    value = _read_hidden(name)
    if value is None:
        return False
    if not value:
        ui.error("Value cannot be empty")
        return False
    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format: {reason}")
    return _write_credential(name, value, "add")


def credential_add(name: str) -> int:
    """Prompt for a new credential; refuses a name that already exists."""
    if not _KEY_NAME.match(name):
        ui.error(f"Invalid credential name {name}", "Use UPPERCASE_WITH_UNDERSCORES")
        return 1
    if name in _secrets.load_secrets():
        ui.error(f"Credential {name} already exists", "Use docket setup provider rotate")
        return 1
    return 0 if prompt_and_store(name) else 1


def credential_rotate(name: str, value: str | None = None) -> int:
    """Replace the value of an existing credential (prompting when ``value`` is None)."""
    if name not in _secrets.load_secrets():
        ui.error(f"Credential {name} does not exist", "Add it with docket setup provider add")
        return 1
    if value is None:
        value = _read_hidden(name, "Enter new value for")
    if not value:
        ui.error("Value cannot be empty")
        return 1
    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format: {reason}")
    return 0 if _write_credential(name, value, "rotate") else 1


def credential_remove(name: str) -> int:
    """Delete one stored credential."""
    secrets = _secrets.load_secrets()
    if name not in secrets:
        ui.error(f"Credential {name} is not stored")
        return 1
    if _keyring_active():
        _system.secret_tool_clear(_cfg.KEYRING_SERVICE, name)
    del secrets[name]
    _secrets.save_secrets(secrets)
    _secrets.touch_meta(name, "removed")
    audit_log("keys.remove", name)
    return 0


# -- provider ------------------------------------------------------------------------------


def _credential_name_for(name: str) -> str:
    return _re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") + "_API_KEY"


def _build_spec(
    name: str, url: str | None, *, credential_given: bool, model: str | None, ctx: int, max_t: int
) -> _prov.ProviderSpec | None:
    """The document ``add`` registers: the catalog entry, or a custom one built from ``url``."""
    existing = _prov.load_catalog().get(name)
    if existing is not None and url is None and model is None:
        return existing
    base = url or (existing.base_url if existing else None)
    if base is None:
        ui.error(
            f"{name} is not a known provider",
            f"Pass its URL: docket setup provider add {name} <url>",
        )
        return None
    if existing is not None:
        auth = existing.auth
    elif credential_given:
        auth = _prov.AuthSpec(type="bearer", credentials=[_credential_name_for(name)])
    else:
        auth = _prov.AuthSpec(type="none")
    row_id = model or (existing.models[0].id if existing and existing.models else "local-model")
    rows = [_prov.ModelRow(id=row_id, contextWindow=ctx, maxTokens=max_t)]
    try:
        return _prov.ProviderSpec(
            name=name,
            dialect="openai-chat",
            base_url=base,
            auth=auth,
            local=auth.type == "none",
            models=rows,
            presets=existing.presets if existing else [],
        )
    except ValidationError as exc:
        ui.error(f"Invalid provider {name}", str(exc).splitlines()[0])
        return None


def _supply_credential(spec: _prov.ProviderSpec, flag_value: str | None) -> bool:
    """Store the provider's credential from the flag, its env var, or a hidden prompt (TTY)."""
    if spec.auth.type == "none" or not spec.auth.credentials:
        return True
    cred = spec.auth.credentials[0]
    stored = _secrets.secrets_keys()
    value = flag_value or os.environ.get(cred, "")
    if not value and cred in stored:
        return True
    if not value:
        if not _contract._is_tty():
            ui.error(f"{cred} is required", f"Pass --credential or export {cred}")
            return False
        entered = _read_hidden(cred)
        if not entered:
            return False
        value = entered
    ok, reason = _validate_key_format(cred, value)
    if not ok:
        ui.warn(f"Key format: {reason}")
    return _write_credential(cred, value, "rotate" if cred in stored else "add")


def _preset_for(spec: _prov.ProviderSpec) -> str | None:
    known = _mp.known_presets()
    if spec.name in known:
        return spec.name
    for preset in spec.presets:
        if preset.name in known:
            return preset.name
    return None


def _select_custom(spec: _prov.ProviderSpec) -> None:
    """Point every role at the provider's first model (no preset exists for a custom entry)."""
    model = f"{spec.name}/{spec.models[0].id}" if spec.models else ""
    if not model:
        return
    updates = {f"role.{role}": model for role in _mp.ALL_ROLES}
    updates["default"] = model
    _mp.write_registry(updates)
    audit_log("models.preset", f"provider={spec.name} model={model}")
    _mp.reapply_role_policy()


def _roles_line() -> str:
    parts = []
    for role in ("lead", "implementer"):
        try:
            parts.append(f"{role} -> {_mp.resolve_role_model(role)}")
        except Exception as exc:
            parts.append(f"{role}: {exc}")
    return ", ".join(parts)


def add_provider(
    name: str,
    url: str | None = None,
    *,
    credential: str | None = None,
    model: str | None = None,
    ctx: int = _DEFAULT_CTX,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    preset: bool = True,
) -> int:
    """Store the credential, probe ``/models``, register, apply the preset; the wizard reuses it."""
    if Path(name).is_file():
        try:
            file_spec = _prov.load_provider_document(name)
        except _prov.ProviderError as exc:
            ui.error(str(exc))
            return 1
        return _register(file_spec, credential, preset)
    spec = _build_spec(
        name, url, credential_given=credential is not None, model=model, ctx=ctx, max_t=max_tokens
    )
    if spec is None:
        return 1
    return _register(spec, credential, preset)


def _register(spec: _prov.ProviderSpec, credential: str | None, preset: bool) -> int:
    if not _supply_credential(spec, credential):
        return 1
    reg = _prov.register_provider(spec)
    v = reg.verification
    if not v.reachable:
        detail = f": {v.warning}" if v.warning else ""
        ui.error(
            f"Could not reach {spec.base_url}/models{detail}",
            "Nothing was registered; fix the URL or start the server and retry",
        )
        return 1
    ui.success(f"Provider {spec.name}: {spec.base_url}" + ("" if reg.changed else " (unchanged)"))
    from docket.cli import _setup

    _setup.step_security()
    _setup.step_policies()
    if v.warning:
        ui.warn(v.warning)
    if not preset:
        return 0
    chosen = _preset_for(reg.spec)
    if chosen is not None:
        apply_preset(chosen, quiet=True)
    else:
        _select_custom(reg.spec)
    ui.success(_roles_line())
    return 0


@provider_app.command("add")
def provider_add(
    name: str = typer.Argument(..., help="Provider name: a catalog entry or a new one"),
    url: str | None = typer.Argument(None, help="Base URL of an OpenAI-compatible endpoint"),
    credential: str | None = typer.Option(
        None, "--credential", help="The API key (else its env var, else a hidden prompt)"
    ),
    model: str | None = typer.Option(None, "--model", help="Model id for a custom endpoint"),
    ctx: int = typer.Option(_DEFAULT_CTX, "--ctx", help="Context window in tokens"),
    max_tokens: int = typer.Option(_DEFAULT_MAX_TOKENS, "--max-tokens", help="Output cap"),
    no_preset: bool = typer.Option(False, "--no-preset", help="Register only; leave roles alone"),
) -> None:
    """Add a provider: store its credential, probe /models, apply its preset.

    Example: docket setup provider add anthropic --credential <key>"""
    rc = add_provider(
        name,
        url,
        credential=credential,
        model=model,
        ctx=ctx,
        max_tokens=max_tokens,
        preset=not no_preset,
    )
    if rc == 0:
        _contract.next_step("docket setup")
    raise typer.Exit(rc)


@provider_app.command("list")
def provider_list(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """List every provider with its scope, dialect, URL and credential.

    Example: docket setup provider list"""
    catalog = _prov.load_catalog()
    rows = []
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        rows.append(
            {
                "name": name,
                "scope": catalog.source_of(name),
                "dialect": spec.dialect,
                "baseUrl": spec.base_url,
                "credential": ", ".join(spec.auth.credentials),
            }
        )
    if json_out:
        _contract.emit_json(rows)
        return
    ui.header("Providers")
    ui.table(
        [[r["name"], r["scope"], r["dialect"], r["baseUrl"], r["credential"] or "-"] for r in rows],
        ["NAME", "SCOPE", "DIALECT", "BASE URL", "CREDENTIAL"],
    )


@provider_app.command("show")
def provider_show(
    name: str = typer.Argument(..., help="Provider name"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show one provider's document.

    Example: docket setup provider show local"""
    catalog = _prov.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown provider {name}", "List them with docket setup provider list")
        raise typer.Exit(1)
    scope = catalog.source_of(name)
    if json_out:
        _contract.emit_json({"scope": scope, **spec.model_dump(by_alias=True)})
        return
    ui.header("Provider", f"{name} ({scope})")
    creds = f" ({', '.join(spec.auth.credentials)})" if spec.auth.credentials else ""
    rows = [
        ["dialect", spec.dialect],
        ["base URL", spec.base_url],
        ["auth", spec.auth.type + creds],
        ["local", str(spec.local)],
        ["models", ", ".join(row.id for row in spec.models) or "-"],
    ]
    ui.table(rows, ["FIELD", "VALUE"])


@provider_app.command("remove")
def provider_remove(
    name: str = typer.Argument(..., help="Provider name"),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation"),
) -> None:
    """Remove a provider's global document and its stored credential.

    Example: docket setup provider remove local --yes"""
    catalog = _prov.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown provider {name}", "List them with docket setup provider list")
        raise typer.Exit(1)
    stored = _secrets.secrets_keys()
    others = {c for n, s in catalog.entries.items() if n != name for c in s.auth.credentials}
    creds = [c for c in spec.auth.credentials if c in stored and c not in others]
    has_document = catalog.source_of(name) == "global"
    if not has_document and not creds:
        ui.error(f"{name} is a built-in provider with nothing stored", "There is nothing to remove")
        raise typer.Exit(1)
    if not _contract.confirm(f"Remove provider {name}", yes=yes):
        ui.warn("Cancelled.")
        raise typer.Exit(0)
    if has_document:
        _prov.remove_provider(name)
    for cred in creds:
        credential_remove(cred)
    ui.success(f"Removed provider {name}" if has_document else f"Removed credential for {name}")
    _contract.next_step("docket setup")


@provider_app.command("export")
def provider_export(
    name: str = typer.Argument(..., help="Provider name"),
    file: Path | None = typer.Argument(None, help="Write the document here (default: stdout)"),
) -> None:
    """Print a provider as a kind: provider document.

    Example: docket setup provider export local provider.yaml"""
    try:
        text = _prov.export_provider(name)
    except _prov.ProviderError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from None
    if file is None:
        sys.stdout.write(text)
        return
    file.write_text(text, encoding="utf-8")
    ui.success(f"Exported {name} to {file}")


@provider_app.command("rotate")
def provider_rotate(
    name: str = typer.Argument(..., help="Provider name"),
    credential: str | None = typer.Option(None, "--credential", help="The new API key"),
) -> None:
    """Replace a provider's stored credential.

    Example: docket setup provider rotate anthropic"""
    spec = _prov.load_catalog().get(name)
    if spec is None or not spec.auth.credentials:
        ui.error(f"Provider {name} has no credential", "Check docket setup provider show " + name)
        raise typer.Exit(1)
    rc = credential_rotate(spec.auth.credentials[0], credential)
    if rc == 0:
        ui.success(f"Rotated {spec.auth.credentials[0]}")
        _contract.next_step("docket setup")
    raise typer.Exit(rc)


# -- model ---------------------------------------------------------------------------------


def _registry_roles() -> dict[str, str]:
    if not _cfg.MODEL_REGISTRY_FILE.exists():
        return {}
    import json as _j

    try:
        data = _j.loads(_cfg.MODEL_REGISTRY_FILE.read_text(encoding="utf-8")).get("roles", {})
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@model_app.callback(invoke_without_command=True)
def model_callback(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Which model each role runs on (bare: show the policy).

    Example: docket setup model"""
    if ctx.invoked_subcommand is not None:
        return
    model_list(json_out)


@model_app.command("list")
def model_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """Show the role to model policy with pricing and source.

    Example: docket setup model list --json"""
    role_models, tiers, default_model = _mp.load_registry()
    overrides = _registry_roles()
    rows = []
    for role in _mp.ALL_ROLES:
        m = role_models.get(role, _cfg.DEFAULT_MODEL)
        source = "user" if overrides.get(role) == m else "builtin"
        rows.append(
            {
                "role": role,
                "model": m,
                "price": _mp.pricing_label(m),
                "source": source,
                "why": _mp.role_why(role),
            }
        )
    if json_out:
        _contract.emit_json({"roles": rows, "default": default_model})
        return
    ui.header("Role to model policy")
    ui.table(
        [[r["role"], r["model"], r["price"], r["source"], r["why"]] for r in rows],
        ["ROLE", "MODEL", "PRICE", "SOURCE", "WHY"],
    )
    _say(f"default  {default_model}")
    _say(
        f"rank anchors  {tiers.get('premium', '')} -> {tiers.get('standard', '')} -> {tiers.get('economy', '')}"
    )
    shown = {d for r in rows if (d := _mp.prices_as_of(str(r["model"])))}
    if shown:
        ui.dim("PRICE is an estimate from a snapshot, not recorded spend")
    ui.dim("Change: docket setup model set <role|default> <provider/model>")


@model_app.command("set")
def model_set(
    key: str = typer.Argument(..., help="A role name, or default"),
    model: str = typer.Argument(..., help="provider/model"),
) -> None:
    """Pin one role (or the default) to a model.

    Example: docket setup model set implementer anthropic/claude-sonnet-4-5"""
    try:
        validated, warnings = _mp.validate_model(model)
    except ValueError as exc:
        ui.error(str(exc), "Use provider/model")
        raise typer.Exit(1) from None
    for w in warnings:
        ui.warn(w)
    role_models, _tiers, default_model = _mp.load_registry()
    if key == "default":
        before, updates = default_model, {"default": validated}
    elif _mp.is_role(key):
        before, updates = role_models.get(key, _cfg.DEFAULT_MODEL), {f"role.{key}": validated}
    else:
        ui.error(f"Unknown role {key}", "Use one of: " + " ".join(_mp.ALL_ROLES) + " default")
        raise typer.Exit(1)
    _mp.write_registry(updates)
    audit_log("models.set", f"role={key} {before}->{validated}")
    ui.success(f"{key} -> {validated}")
    if _mp.is_role(key):
        _mp.reapply_role_policy()
    _contract.next_step("docket setup")


def _preset_rows() -> list[list[str]]:
    table = _mp.preset_table()
    rows = []
    for p in _mp.known_presets():
        t = table[p]
        rows.append([p, t["cost"], t["key"] or "-", t["note"]])
    return rows


def apply_preset(preset: str, *, quiet: bool = False) -> None:
    """Write a preset's role rows, re-resolve the agents and report the roles that matter."""
    table = _mp.preset_table()
    registered = _prov.load_catalog().get(preset)
    t = table[preset]
    econ, std, prem = t["economy"], t["standard"], t["premium"]
    if preset == "local" and registered is not None and registered.models:
        registered_id = registered.models[0].id.strip()
        if registered_id:
            econ = std = prem = f"local/{registered_id}"
    before_roles, _tiers, before_default = _mp.load_registry()
    cheap = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "cheap"]
    strong = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "strong"]
    updates = {"default": std, "rank.economy": econ, "rank.standard": std, "rank.premium": prem}
    updates.update({f"role.{r}": econ for r in cheap})
    updates.update({f"role.{r}": std for r in strong})
    _mp.write_registry(updates)
    after = dict.fromkeys(cheap, econ)
    after.update(dict.fromkeys(strong, std))
    changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{after[r]}" for r in _mp.ALL_ROLES
    )
    audit_log("models.preset", f"preset={preset} default:{before_default}->{std} roles:{changes}")
    _mp.reapply_role_policy()
    if quiet:
        return
    ui.success(f"Preset {preset} applied")
    _say(f"  {' '.join(cheap)} -> {econ}")
    _say(f"  {' '.join(strong)} -> {std}")
    _say("  cost -> " + ("free per-token" if t["cost"] == "free" else "paid"))
    if t["note"]:
        _say(f"  note -> {t['note']}")
    state = _prov.model_readiness(std)
    if state.credential_name and not state.credential_present:
        ui.warn(f"API key {state.credential_name} is not stored yet")
        ui.dim(f"Store it: docket setup provider add {preset} --credential <key>")
    elif preset == "local":
        ui.success("Registered local endpoint selected; no API key needed.")


@model_app.command("preset")
def model_preset(
    name: str | None = typer.Argument(None, help="Preset to apply; omit to list them"),
) -> None:
    """List the provider presets, or apply one to every role.

    Example: docket setup model preset local"""
    if name is None:
        ui.header("Provider presets")
        ui.table(_preset_rows(), ["PRESET", "COST", "KEY NEEDED", "NOTE"])
        return
    if name not in _mp.preset_table():
        ui.error(f"Unknown preset {name}", "Valid: " + " ".join(_mp.known_presets()))
        raise typer.Exit(1)
    apply_preset(name)
    _contract.next_step("docket setup")


@model_app.command("reset")
def model_reset(yes: bool = typer.Option(False, "--yes", help="Do not ask")) -> None:
    """Remove every override and restore the built-in role policy.

    Example: docket setup model reset --yes"""
    if not _cfg.MODEL_REGISTRY_FILE.exists():
        ui.success("No overrides: already on the built-in policy")
        return
    if not _contract.confirm("Remove all model overrides", yes=yes):
        ui.warn("Cancelled.")
        raise typer.Exit(0)
    before_roles, _t, before_default = _mp.load_registry()
    _mp.write_registry({}, reset=True)
    with contextlib.suppress(FileNotFoundError):
        _cfg.MODEL_REGISTRY_FILE.unlink()
    after_roles, _t2, after_default = _mp.load_registry()
    changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{after_roles.get(r, _cfg.DEFAULT_MODEL)}"
        for r in _mp.ALL_ROLES
    )
    audit_log("models.reset", f"default:{before_default}->{after_default} roles:{changes}")
    _mp.reapply_role_policy()
    ui.success("Restored the built-in model policy")
    _contract.next_step("docket setup")
