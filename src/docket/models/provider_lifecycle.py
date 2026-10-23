from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docket.agent.llm import ModelLimits
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.process import process as _process
from docket.models.catalog import (
    ProviderError,
    ProviderSpec,
    _with_inherited_identity,
    check_rank_anchors,
    delete_provider,
    load_catalog,
    observed_at,
    resolve_credential,
    save_provider,
)
from docket.platform import read_modify_write

if TYPE_CHECKING:
    from docket.models.adapters.openai_http import ProbeResult
from docket.agent.llm import Endpoint
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.models.adapters import openai_http as _llm


def record_observed_models(spec: ProviderSpec, probe: ProbeResult) -> None:
    """Replace *spec*'s observed models with what *probe* advertised, dated today. A probe that
    is not a 200 records nothing and leaves an earlier observation alone. The only writer of
    ``Home.provider_models_file``."""
    if probe.status != 200:
        return
    models = {
        model_id: {
            "contextWindow": probe.limits.get(model_id, ModelLimits()).context_window,
            "maxTokens": probe.limits.get(model_id, ModelLimits()).max_output,
        }
        for model_id in sorted(set(probe.model_ids) | set(probe.limits))
    }
    entry = {"observedAt": _clock.today_iso(), "models": models}

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        providers = current.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        providers[spec.name] = entry
        return {"providers": providers}

    read_modify_write(current_home().provider_models_file, _update)


def refresh_observed_models_due() -> list[str]:
    """Probe every operator-registered (``global``) provider not yet observed today and record
    the result; a built-in nobody registered is never probed. Returns the names refreshed."""
    catalog = load_catalog()
    refreshed: list[str] = []
    for name in sorted(catalog.entries):
        if catalog.source_of(name) != "global" or observed_at(name) == _clock.today_iso():
            continue
        spec = catalog.entries[name]
        try:
            probe = probe_spec(spec)
            if probe.status == 200:
                record_observed_models(spec, probe)
                refreshed.append(name)
        except Exception:
            continue
    return refreshed


@dataclass(frozen=True)
class ProviderVerification:
    """A classified probe of a provider's ``/models`` route (ADR 0011 §4) -- pure, no I/O.
    ``reachable`` is False only for a transport failure; every HTTP status, including a
    rejected credential, is reachable and explains itself in ``warning`` instead."""

    reachable: bool
    status: int | None
    credential_present: bool
    credential_name: str
    advertised: tuple[str, ...]
    warning: str


def verify_endpoint(spec: ProviderSpec, probe: ProbeResult) -> ProviderVerification:
    """Classify *probe* of *spec*'s ``/models`` route per ADR 0011 §4's table. A transport
    failure (``probe.status is None``) is the only unreachable outcome; every HTTP status
    registers, with a warning naming what is not a clean 200."""
    credential_value, _source = resolve_credential(spec)
    credential_present = bool(credential_value)
    credential_name = spec.auth.credentials[0] if spec.auth.credentials else ""

    if probe.status is None:
        return ProviderVerification(
            reachable=False,
            status=None,
            credential_present=credential_present,
            credential_name=credential_name,
            advertised=(),
            warning=probe.transport_error,
        )

    known_ids = {row.id for row in spec.models}
    advertised = tuple(sorted(mid for mid in probe.model_ids if mid not in known_ids))

    warning = ""
    if probe.status == 200:
        if advertised:
            warning = f"endpoint also advertises: {', '.join(advertised)}"
    elif probe.status in (401, 403):
        who = credential_name or "a credential"
        warning = (
            f"{who} was rejected (HTTP {probe.status})"
            if credential_present
            else f"{who} is missing (HTTP {probe.status})"
        )
    elif probe.status == 404:
        warning = "no /models route; capability not verified"
    else:
        warning = f"endpoint returned HTTP {probe.status}"

    return ProviderVerification(
        reachable=True,
        status=probe.status,
        credential_present=credential_present,
        credential_name=credential_name,
        advertised=advertised,
        warning=warning,
    )


@dataclass(frozen=True)
class Registration:
    """Outcome of ``register_provider``. Rendered by ``interfaces/cli/commands/setup_model_provider.py``."""

    spec: ProviderSpec
    verification: ProviderVerification
    changed: bool


def probe_spec(spec: ProviderSpec, *, credential: str | None = None) -> ProbeResult:
    """Probe *spec*'s ``/models`` with its resolved credential, or with *credential* when the
    caller holds a value it has not stored yet (``DOCKET_LLM_API_KEY`` still wins); nothing is
    saved."""

    credential_value, source = resolve_credential(spec)
    if credential and source != "override":
        credential_value = credential
    endpoint = Endpoint(
        base_url=spec.base_url,
        model_id="x",
        api_key=credential_value,
        provider=spec.name,
        auth_type=spec.auth.type,
        auth_header=spec.auth.header,
        headers=tuple(spec.headers.items()),
    )
    return _llm.probe_models(endpoint)


def register_provider(spec: ProviderSpec, *, probe: ProbeResult | None = None) -> Registration:
    """Verify *spec* with the resolved credential and classify the result; persist only when
    reachable (model-profiles.spec.md "Provider readiness" 3). The default probe builds an
    ``Endpoint`` straight from *spec*, never a saved entry, since nothing is written yet."""
    check_rank_anchors(spec)
    if probe is None:
        probe = probe_spec(spec)

    verification = verify_endpoint(spec, probe)
    if not verification.reachable:
        return Registration(spec=spec, verification=verification, changed=False)

    existing = load_catalog().get(spec.name)
    desired = _with_inherited_identity(spec)
    changed = existing != desired
    save_provider(spec)
    record_observed_models(spec, probe)

    status_label = str(verification.status) if verification.status is not None else "unreachable"
    _audit.audit_log("provider.add", f"name={spec.name} scope=global status={status_label}")
    return Registration(spec=desired, verification=verification, changed=changed)


def remove_provider(name: str) -> None:
    """Remove *name* from the global catalog. A built-in with no global override has nothing
    to remove -- ``ProviderError`` names the built-in scope rather than silently no-op'ing."""
    removed = delete_provider(name)
    if not removed:
        scope = load_catalog().source_of(name)
        if scope == "built-in":
            raise ProviderError(
                current_home().providers_file,
                "name",
                f"'{name}' is a built-in provider with no global override -- nothing to remove",
            )
        raise ProviderError(
            current_home().providers_file, "name", f"'{name}' is not in the provider catalog"
        )

    _audit.audit_log("provider.remove", f"name={name}")


def export_provider(name: str) -> str:
    """Render *name*'s resolved catalog entry as a ``kind: provider`` document -- the inverse
    of ``load_provider_document``, proven to round-trip (export -> fresh home -> add ->
    identical ``show --json``)."""
    spec = load_catalog().get(name)
    if spec is None:
        raise ProviderError(
            current_home().providers_file, "name", f"'{name}' is not in the provider catalog"
        )

    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ProviderError(
            current_home().providers_file, "file", "PyYAML not installed -- run: pip install pyyaml"
        ) from None

    payload = {
        "kind": "provider",
        **spec.model_dump(by_alias=True, exclude_defaults=True, exclude_none=True),
    }
    return str(_yaml.safe_dump(payload, sort_keys=False))


@dataclass(frozen=True)
class ModelReadiness:
    """Structural readiness of one selected runtime model, with no secret values."""

    model: str
    provider: str
    base_url: str
    ready: bool
    credential_name: str
    credential_present: bool
    context_window: int | None
    max_output: int | None
    issue: str


def model_readiness(model: str) -> ModelReadiness:
    """Resolve the selected model and require credentials only for known hosted routes.

    This is deliberately structural: it does not spend a remote model request. Local provider
    reachability is established at registration time; the deterministic driver test owns actual
    Chat Completions/tool-wire capability.
    """

    provider, _, _model_id = model.partition("/")
    spec = load_catalog().get(provider)
    credential_names = tuple(spec.auth.credentials) if spec else ()
    credential_name = credential_names[0] if credential_names else ""
    credential_present = any(
        bool(_process.env_value(name)) or bool(_secrets.secret_value(name))
        for name in credential_names
    )
    endpoint = _llm.resolve_endpoint(model)
    if endpoint is None:
        detail = (
            f"{credential_name} is present but is not an endpoint" if credential_present else ""
        )
        issue = detail or "no callable OpenAI-compatible endpoint is configured"
        return ModelReadiness(
            model=model,
            provider=provider,
            base_url="",
            ready=False,
            credential_name=credential_name,
            credential_present=credential_present,
            context_window=None,
            max_output=None,
            issue=issue,
        )

    if credential_names and not endpoint.api_key:
        return ModelReadiness(
            model=model,
            provider=provider,
            base_url=endpoint.base_url,
            ready=False,
            credential_name=credential_name,
            credential_present=False,
            context_window=endpoint.context_window_tokens,
            max_output=endpoint.max_output_tokens,
            issue=f"{credential_name} is required for the resolved endpoint",
        )

    return ModelReadiness(
        model=model,
        provider=provider,
        base_url=endpoint.base_url,
        ready=True,
        credential_name=credential_name,
        credential_present=bool(endpoint.api_key),
        context_window=endpoint.context_window_tokens,
        max_output=endpoint.max_output_tokens,
        issue="",
    )
