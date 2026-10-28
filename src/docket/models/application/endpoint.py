from __future__ import annotations

import os

from docket.agent.ports import Endpoint
from docket.governance import secrets as _secrets
from docket.models import catalog as _prov
from docket.models.catalog import ModelProfile, ProviderSpec

# ── endpoint resolution ───────────────────────────────────────────────────────


def resolve_endpoint(model: str) -> Endpoint | None:
    """Resolve a ``provider/model-id`` string to a callable endpoint.

    Precedence, highest first:

    1. ``DOCKET_LLM_BASE_URL`` / ``DOCKET_LLM_API_KEY`` — a process-wide
       override that points every model at one endpoint. Exists for local
       development and for tests that want a stub server without touching
       stored config.
    2. The provider catalog entry for ``<provider>`` (``models/catalog.py``'s
       ``load_catalog``) — built-in overridden by the operator's own (global), nearest-wins.
    3. ``DOCKET_LLM_BASE_URL`` alone, only for a provider absent from the catalog (every hosted
       gateway docket knows ships as a built-in catalog document; this step is the one escape
       hatch left for a provider that is neither).

    For a catalog entry, the API key comes from ``models/catalog.py``'s ``resolve_credential``
    (``DOCKET_LLM_API_KEY`` -> environment -> Docket's central key store, per name in
    ``auth.credentials``). For a provider absent from the catalog, the key falls back through
    ``DOCKET_LLM_API_KEY``, then the derived ``<PREFIX>_API_KEY`` environment variable, then the
    same name in the central key store. Returns ``None`` when no base URL can be found, so
    callers report an actionable "no endpoint configured" rather than posting into the void.
    """
    provider, _, model_id = model.partition("/")
    if not model_id:
        provider, model_id = "", model

    env_base = _endpoint_override()
    env_key = os.environ.get("DOCKET_LLM_API_KEY", "").strip()

    spec = _catalog_row(provider)

    if spec is not None:
        api_key, _source = _prov.resolve_credential(spec)
        return endpoint_from_spec(spec, provider, model_id, api_key)

    # Absent from the catalog: only DOCKET_LLM_BASE_URL can resolve it, deriving the
    # credential's env name from the provider prefix (never a per-provider literal here).
    base_url = env_base
    if not base_url:
        return None

    api_key = env_key
    if not api_key and provider:
        credential_name = f"{provider.upper().replace('-', '_')}_API_KEY"
        api_key = os.environ.get(credential_name, "").strip()
        if not api_key:
            api_key = _secrets.secret_value(credential_name) or ""

    return Endpoint(
        base_url=base_url,
        model_id=model_id,
        api_key=api_key,
        provider=provider,
        context_window_tokens=None,
        max_output_tokens=None,
    )


def resolve_profile(model: str) -> ModelProfile:
    """The model profile of the catalog row *model* (``provider/model-id``) names. A provider
    absent from the catalog, and every model while ``DOCKET_LLM_BASE_URL`` overrides the endpoint,
    is ``hosted``: the same lookup ``resolve_endpoint`` makes."""
    provider, _, model_id = model.partition("/")
    spec = _catalog_row(provider) if model_id else None
    return _prov.profile_of(spec, model_id) if spec else _prov.BUILTIN_PROFILES["hosted"]


def _catalog_row(provider: str) -> ProviderSpec | None:
    """*provider*'s catalog row, unless ``DOCKET_LLM_BASE_URL`` overrides every endpoint."""
    if not provider or _endpoint_override():
        return None
    return _prov.load_catalog().get(provider)


def _endpoint_override() -> str:
    return os.environ.get("DOCKET_LLM_BASE_URL", "").strip()


def endpoint_from_spec(spec: ProviderSpec, provider: str, model_id: str, api_key: str) -> Endpoint:
    """The endpoint catalog entry *spec* (named *provider*) gives *model_id*, with *api_key*
    already resolved; each limit is declared, else observed, else unknown."""

    limits = _prov.resolve_limits(spec, model_id)
    return Endpoint(
        base_url=spec.base_url,
        model_id=model_id,
        api_key=api_key,
        provider=provider,
        context_window_tokens=limits.context_window,
        max_output_tokens=limits.max_output,
        auth_type=spec.auth.type,
        auth_header=spec.auth.header,
        headers=tuple(spec.headers.items()),
    )
