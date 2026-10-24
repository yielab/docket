"""The model setup commands: `setup provider` (endpoints and credentials) and `setup model`."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import typer

from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.setup_model_credentials import (
    credential_remove,
    credential_rotate,
)
from docket.interfaces.cli.commands.setup_model_provider import (
    _say,
    add_provider,
    apply_preset,
    report_repoints,
)
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.models import catalog as _prov
from docket.models import provider_lifecycle as _provider_lifecycle
from docket.teams import model_selection as _mp

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


@provider_app.command("add")
def provider_add(
    name: str = typer.Argument(..., help="Provider name: a catalog entry or a new one"),
    url: str | None = typer.Argument(None, help="Base URL of an OpenAI-compatible endpoint"),
    credential: str | None = typer.Option(
        None, "--credential", help="The API key (else its env var, else a hidden prompt)"
    ),
    model: str | None = typer.Option(None, "--model", help="Model id for a custom endpoint"),
    ctx: int | None = typer.Option(
        None, "--ctx", help="Context window in tokens (default: what /models publishes)"
    ),
    max_tokens: int | None = typer.Option(
        None, "--max-tokens", help="Output cap (default: what /models publishes)"
    ),
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
    limits = {row.id: _prov.resolve_limits(spec, row.id) for row in spec.models}
    if json_out:
        document = spec.model_dump(by_alias=True)
        document["models"] = [
            {**model, **_limits_json(limits[model["id"]])} for model in document["models"]
        ]
        _contract.emit_json({"scope": scope, **document})
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
    if limits:
        ui.table(
            [
                [
                    model_id,
                    _limit_text(found.context_window, found.context_window_source, found),
                    _limit_text(found.max_output, found.max_output_source, found),
                ]
                for model_id, found in limits.items()
            ],
            ["MODEL", "WINDOW", "OUTPUT"],
        )


def _limits_json(found: _prov.ResolvedLimits) -> dict[str, object]:
    return {
        "contextWindow": found.context_window,
        "maxTokens": found.max_output,
        "limitsSource": found.source,
        "contextWindowSource": found.context_window_source,
        "maxTokensSource": found.max_output_source,
        "observedAt": found.observed_at,
    }


def _limit_text(value: int | None, source: str, found: _prov.ResolvedLimits) -> str:
    if value is None:
        return "unknown"
    if source == "observed":
        return f"{value} (observed {found.observed_at})"
    return f"{value} ({source})"


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
        _provider_lifecycle.remove_provider(name)
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
        text = _provider_lifecycle.export_provider(name)
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
    if not current_home().model_registry_file.exists():
        return {}
    import json as _j

    try:
        data = _j.loads(current_home().model_registry_file.read_text(encoding="utf-8")).get(
            "roles", {}
        )
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
        m = role_models.get(role, current_home().default_model)
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
        before, updates = (
            role_models.get(key, current_home().default_model),
            {f"role.{key}": validated},
        )
    else:
        ui.error(f"Unknown role {key}", "Use one of: " + " ".join(_mp.ALL_ROLES) + " default")
        raise typer.Exit(1)
    _mp.write_registry(updates)
    audit_log("models.set", f"role={key} {before}->{validated}")
    ui.success(f"{key} -> {validated}")
    if _mp.is_role(key):
        report_repoints(_mp.reapply_role_policy())
    _contract.next_step("docket setup")


def _preset_rows() -> list[list[str]]:
    table = _mp.preset_table()
    rows = []
    for p in _mp.known_presets():
        t = table[p]
        rows.append([p, t["cost"], t["key"] or "-", t["note"]])
    return rows


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
    if not current_home().model_registry_file.exists():
        ui.success("No overrides: already on the built-in policy")
        return
    if not _contract.confirm("Remove all model overrides", yes=yes):
        ui.warn("Cancelled.")
        raise typer.Exit(0)
    before_roles, _t, before_default = _mp.load_registry()
    _mp.write_registry({}, reset=True)
    with contextlib.suppress(FileNotFoundError):
        current_home().model_registry_file.unlink()
    after_roles, _t2, after_default = _mp.load_registry()
    changes = ",".join(
        f"{r}:{before_roles.get(r, current_home().default_model)}->{after_roles.get(r, current_home().default_model)}"
        for r in _mp.ALL_ROLES
    )
    audit_log("models.reset", f"default:{before_default}->{after_default} roles:{changes}")
    report_repoints(_mp.reapply_role_policy())
    ui.success("Restored the built-in model policy")
    _contract.next_step("docket setup")
