from __future__ import annotations

import os
import re as _re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from rich.markup import escape

from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import setup as _setup
from docket.interfaces.cli.commands.setup_model_credentials import (
    _read_hidden,
    _validate_key_format,
    _write_credential,
)
from docket.interfaces.cli.render import ui
from docket.kernel.errors import DocumentError, Unavailable
from docket.kernel.home import current_home
from docket.models import catalog as _prov
from docket.models import provider_lifecycle as _provider_lifecycle
from docket.models import selection as _mp


def _say(text: str = "") -> None:
    ui.console.print(escape(text))


# -- provider ------------------------------------------------------------------------------


def _credential_name_for(name: str) -> str:
    return _re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") + "_API_KEY"


def _rows_with_limits(
    name: str, rows: list[_prov.ModelRow], model: str | None, ctx: int | None, max_t: int | None
) -> list[dict[str, object]] | None:
    """The provider's inherited rows as documents, with ``--ctx``/``--max-tokens`` applied to the
    row ``--model`` names (appended when new) or, with no ``--model``, to the only row. ``None``
    when a limit flag has no single row to land on."""
    documents = [row.model_dump(by_alias=True, exclude_none=True) for row in rows]
    limits: dict[str, object] = {}
    if ctx is not None:
        limits["contextWindow"] = ctx
    if max_t is not None:
        limits["maxTokens"] = max_t
    target = model
    if target is None:
        if not limits:
            return documents
        if len(rows) != 1:
            ui.error(
                f"--ctx and --max-tokens need --model: {name} lists {len(rows)} models",
                f"Pass the model they describe: docket setup provider add {name} --model <id>",
            )
            return None
        target = rows[0].id
    for document in documents:
        if document["id"] == target:
            document.update(limits)
            return documents
    return [*documents, {"id": target, **limits}]


def _build_spec(
    name: str,
    url: str | None,
    *,
    credential_given: bool,
    model: str | None,
    ctx: int | None,
    max_t: int | None,
) -> _prov.ProviderSpec | None:
    """The document ``add`` registers: the catalog entry (its rows kept, limits applied), or a
    custom one built from ``url``."""
    existing = _prov.load_catalog().get(name)
    if existing is not None and url is None and model is None and ctx is None and max_t is None:
        return existing
    base = url or (existing.base_url if existing else None)
    if base is None:
        ui.error(
            f"{name} is not a known provider",
            f"Pass its URL: docket setup provider add {name} <url>",
        )
        return None
    try:
        if existing is not None:
            rows = _rows_with_limits(name, existing.models, model, ctx, max_t)
            if rows is None:
                return None
            return _prov.ProviderSpec.model_validate(
                {**existing.model_dump(by_alias=True), "baseUrl": base, "models": rows}
            )
        if credential_given:
            auth = _prov.AuthSpec(type="bearer", credentials=[_credential_name_for(name)])
        else:
            auth = _prov.AuthSpec(type="none")
        row = _prov.ModelRow(id=model or "local-model", contextWindow=ctx, maxTokens=max_t)
        return _prov.ProviderSpec(
            name=name,
            dialect="openai-chat",
            base_url=base,
            auth=auth,
            local=auth.type == "none",
            models=[row],
            presets=[],
        )
    except ValidationError as exc:
        ui.error(f"Invalid provider {name}", str(exc).splitlines()[0])
        return None


@dataclass(frozen=True)
class _PendingCredential:
    """A credential value gathered but not yet stored; ``name`` is empty when none is needed."""

    name: str = ""
    value: str = ""
    event: str = "add"

    def store(self) -> bool:
        return not self.value or _write_credential(self.name, self.value, self.event)


def _collect_credential(
    spec: _prov.ProviderSpec, flag_value: str | None
) -> _PendingCredential | None:
    """Gather the provider's credential from the flag, its env var, or a hidden prompt (TTY),
    storing nothing; ``None`` after printing why it cannot be had or stored."""
    if spec.auth.type == "none" or not spec.auth.credentials:
        return _PendingCredential()
    cred = spec.auth.credentials[0]
    stored = _secrets.secrets_keys()
    value = flag_value or os.environ.get(cred, "")
    if not value and cred in stored:
        return _PendingCredential()
    try:
        _secrets.store_backend()
    except Unavailable as exc:
        ui.error(exc.message, exc.hint)
        return None
    if not value:
        if not _contract.is_tty():
            ui.error(f"{cred} is required", f"Pass --credential or export {cred}")
            return None
        entered = _read_hidden(cred)
        if not entered:
            return None
        value = entered
    ok, reason = _validate_key_format(cred, value)
    if not ok:
        ui.warn(f"Key format: {reason}")
    return _PendingCredential(cred, value, "rotate" if cred in stored else "add")


def _preset_for(spec: _prov.ProviderSpec) -> str | None:
    known = _mp.known_presets()
    if spec.name in known:
        return spec.name
    for preset in spec.presets:
        if preset.name in known:
            return preset.name
    return None


def report_repoints(moved: list[_mp.RoleRepoint], *, provider: str = "") -> None:
    """Name every pod and role a role-table change moved, grouped by pod. The role table is the
    fleet's, so one write can move members of every pod; with *provider*, say how to avoid it."""
    if not moved:
        return
    pods = sorted({m.pod for m in moved})
    ui.warn(f"Moved {len(moved)} agent(s) in {len(pods)} pod(s) to the new role models:")
    for pod in pods:
        parts = [f"{m.role} {m.before or '-'} -> {m.after}" for m in moved if m.pod == pod]
        _say(f"  pod {pod or '-'}: " + ", ".join(parts))
    if provider:
        _say(
            f"  To register a provider without moving them: docket setup provider add {provider} --no-preset"
        )


def _select_custom(spec: _prov.ProviderSpec) -> None:
    """Point every role at the provider's first model (no preset exists for a custom entry)."""
    model = f"{spec.name}/{spec.models[0].id}" if spec.models else ""
    if not model:
        return
    updates = {f"role.{role}": model for role in _mp.ALL_ROLES}
    updates["default"] = model
    _mp.write_registry(updates)
    audit_log("models.preset", f"provider={spec.name} model={model}")
    report_repoints(_mp.reapply_role_policy(), provider=spec.name)


def apply_preset(preset: str, *, quiet: bool = False, provider: str = "") -> None:
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
        f"{r}:{before_roles.get(r, current_home().default_model)}->{after[r]}"
        for r in _mp.ALL_ROLES
    )
    audit_log("models.preset", f"preset={preset} default:{before_default}->{std} roles:{changes}")
    report_repoints(_mp.reapply_role_policy(), provider=provider)
    if quiet:
        return
    ui.success(f"Preset {preset} applied")
    _say(f"  {' '.join(cheap)} -> {econ}")
    _say(f"  {' '.join(strong)} -> {std}")
    _say("  cost -> " + ("free per-token" if t["cost"] == "free" else "paid"))
    if t["note"]:
        _say(f"  note -> {t['note']}")
    state = _provider_lifecycle.model_readiness(std)
    if state.credential_name and not state.credential_present:
        ui.warn(f"API key {state.credential_name} is not stored yet")
        ui.dim(f"Store it: docket setup provider add {preset} --credential <key>")
    elif preset == "local":
        ui.success("Registered local endpoint selected; no API key needed.")


def _roles_line() -> str:
    parts = []
    for role in ("lead", "implementer"):
        try:
            parts.append(f"{role} -> {_mp.resolve_role_model(role)}")
        except Exception as exc:
            parts.append(f"{role}: {exc}")
    return ", ".join(parts)


def _register(
    spec: _prov.ProviderSpec, credential: str | None, preset: bool, *, defaulted: bool = False
) -> int:
    try:
        _prov.check_rank_anchors(spec)
    except DocumentError as exc:
        ui.error(str(exc))
        return 1
    pending = _collect_credential(spec, credential)
    if pending is None:
        return 1
    probe = _provider_lifecycle.probe_spec(spec, credential=pending.value)
    if probe.status is None:
        detail = f": {probe.transport_error}" if probe.transport_error else ""
        ui.error(
            f"Could not reach {spec.base_url}/models{detail}",
            "Nothing was registered; fix the URL or start the server and retry",
        )
        return 1
    note = ""
    if defaulted and probe.status == 200:
        if probe.model_ids:
            chosen_id = sorted(probe.model_ids)[0]
            spec = spec.model_copy(
                update={"models": [spec.models[0].model_copy(update={"id": chosen_id})]}
            )
            note = f" (model {chosen_id})"
        else:
            note = " (no model advertised; recorded local-model)"
    if not pending.store():
        return 1
    reg = _provider_lifecycle.register_provider(spec, probe=probe)
    v = reg.verification
    ui.success(
        f"Provider {spec.name}: {spec.base_url}{note}" + ("" if reg.changed else " (unchanged)")
    )

    _setup.step_security()
    _setup.step_policies()
    if v.warning:
        ui.warn(v.warning)
    if not preset:
        return 0
    chosen = _preset_for(reg.spec)
    if chosen is not None:
        apply_preset(chosen, quiet=True, provider=reg.spec.name)
    else:
        _select_custom(reg.spec)
    ui.success(_roles_line())
    return 0


def add_provider(
    name: str,
    url: str | None = None,
    *,
    credential: str | None = None,
    model: str | None = None,
    ctx: int | None = None,
    max_tokens: int | None = None,
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
    defaulted = model is None and url is not None and _prov.load_catalog().get(name) is None
    spec = _build_spec(
        name, url, credential_given=credential is not None, model=model, ctx=ctx, max_t=max_tokens
    )
    if spec is None:
        return 1
    return _register(spec, credential, preset, defaulted=defaulted)
