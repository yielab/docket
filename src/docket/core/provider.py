"""Provider catalog: the model providers docket knows, as `kind: provider` documents.

A provider is a `ProviderSpec` -- name, dialect, base URL, named credentials (never a value),
and selectable models -- loaded the same way a role or policy is (model-profiles.spec.md
"Provider catalog"). Two scopes, nearest-wins by name: built-in (`config.PROVIDER_TEMPLATES_DIR`)
and global (`config.PROVIDERS_FILE`, the operator's own). `edges/adapters/llm.py`'s
`resolve_endpoint` reads the merged catalog; this module has no knowledge of terminals.

`register_local_provider` pings and registers a local endpoint via `save_provider`.
`migrate_fleet_providers` ports a pre-catalog `fleet.json -> providers` block in once; a literal
API key there moves into the secret store, referenced by name, never copied into the document.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

import docket.config as _cfg
from docket.edges import store as _store

# Defaults match the Qwen3-30B-A3B llama.cpp setup (server on :8080, -c 16384).
DEFAULT_PROVIDER = "local"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL_ID = "qwen3-30b-a3b"
DEFAULT_MODEL_NAME = "Qwen3 30B-A3B (local)"
DEFAULT_CTX = 16384
DEFAULT_MAX_TOKENS = 8192

# Single owner of this table -- edges/adapters/llm.py imports it rather than keeping its own
# copy, so a provider added here is never silently missing from the request path (or vice
# versa). Used only for a provider absent from the catalog; a catalog entry names its own
# credentials in `auth.credentials`. Retired once every hosted provider ships as a built-in
# catalog document (a later card).
PROVIDER_CREDENTIAL_NAMES: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_AI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "ai-gateway": ("AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN"),
}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ProviderError(Exception):
    """*file*: *field*: *message* (valid: ...) -- a provider document failed to load or a
    catalog write was rejected. ``valid`` is populated only for a closed-vocabulary failure."""

    def __init__(
        self, file: Path | str, field: str, message: str, valid: tuple[str, ...] = ()
    ) -> None:
        self.file = Path(file)
        self.field = field
        self.message = message
        self.valid = tuple(valid)
        super().__init__(str(self))

    def __str__(self) -> str:
        rendered = f"{self.file}: {self.field}: {self.message}"
        if self.valid:
            rendered = f"{rendered} (valid: {', '.join(self.valid)})"
        return rendered


class AuthSpec(BaseModel):
    """How a request authenticates against a provider -- names only, never a value."""

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["bearer", "none"]
    credentials: list[str] = Field(default_factory=list)

    @field_validator("credentials")
    @classmethod
    def _valid_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not _CREDENTIAL_NAME_RE.match(name):
                raise ValueError(f"'{name}' is not a valid credential name (^[A-Z][A-Z0-9_]*$)")
        return value


class ModelRow(BaseModel):
    """One selectable model id and its exact limits (either may be unknown)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    context_window: int | None = Field(None, alias="contextWindow", gt=0)
    max_tokens: int | None = Field(None, alias="maxTokens", gt=0)


class ProviderSpec(BaseModel):
    """A `kind: provider` document -- see specs/functional/model-profiles.spec.md
    ("Provider catalog"). ``kind`` itself is the document envelope's concern
    (`load_provider_document`/`core.config_docs`), not a field of the parsed model."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    dialect: Literal["openai-chat"] = "openai-chat"
    base_url: str = Field(alias="baseUrl")
    auth: AuthSpec
    local: bool = False
    models: list[ModelRow] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _default_auth_for_local(cls, data: Any) -> Any:
        """``local: true`` implies ``auth.type: none`` when ``auth`` is not given at all --
        an explicit ``auth`` block always wins."""
        if isinstance(data, dict) and data.get("local") and "auth" not in data:
            data = {**data, "auth": {"type": "none"}}
        return data

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"'{value}' is not a valid provider name (^[a-z0-9][a-z0-9-]*$)")
        return value

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError(f"'{value}' must be an http:// or https:// URL")
        return value

    @field_validator("models")
    @classmethod
    def _unique_ids(cls, value: list[ModelRow]) -> list[ModelRow]:
        seen: set[str] = set()
        for row in value:
            if row.id in seen:
                raise ValueError(f"duplicate model id '{row.id}'")
            seen.add(row.id)
        return value


def _validation_to_provider_error(path: Path | str, exc: ValidationError) -> ProviderError:
    """Refine pydantic's first error into a ``ProviderError`` naming the field and, for a
    closed-vocabulary failure (an unknown ``dialect``/``auth.type``), the valid values --
    the same refinement ``core/config_docs.py``'s ``_refine_with_model`` does for a role."""
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"]) if first["loc"] else ""
    valid: tuple[str, ...] = ()
    expected = (first.get("ctx") or {}).get("expected")
    if isinstance(expected, str):
        valid = tuple(
            v.strip("'\" ") for v in re.split(r"\s+or\s+|,\s*", expected) if v.strip("'\" ")
        )
    return ProviderError(path, field, first["msg"], valid)


def load_provider_document(path: str | Path) -> ProviderSpec:
    """Read *path* as a `kind: provider` document. Raises ``ProviderError`` naming the file,
    field and message on any failure -- bad YAML, missing ``kind``/``name``, an unknown
    ``dialect``/``auth.type``, or a credential count mismatch."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProviderError(p, "file", f"cannot read file: {exc}") from exc

    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ProviderError(p, "file", "PyYAML not installed -- run: pip install pyyaml") from None
    try:
        raw = _yaml.safe_load(text)
    except Exception as exc:
        raise ProviderError(p, "file", f"YAML parse error: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ProviderError(p, "file", f"document must be a mapping (got {type(raw).__name__})")

    kind = raw.get("kind")
    if kind != "provider":
        raise ProviderError(p, "kind", f"expected 'provider', got {kind!r}", valid=("provider",))
    if not raw.get("name"):
        raise ProviderError(p, "name", "a provider document requires 'name'")

    try:
        spec = ProviderSpec.model_validate(raw)
    except ValidationError as exc:
        raise _validation_to_provider_error(p, exc) from exc

    if spec.auth.type == "bearer" and not spec.auth.credentials:
        raise ProviderError(
            p, "auth.credentials", "bearer auth requires at least one credential name"
        )
    if spec.auth.type == "none" and spec.auth.credentials:
        raise ProviderError(p, "auth.credentials", "none auth accepts no credential name")
    return spec


@dataclass(frozen=True)
class Catalog:
    """The merged provider catalog: the operator's own (global) entries override a built-in of
    the same name, nearest-wins -- the same rule as a role overlay, one level shorter."""

    entries: dict[str, ProviderSpec]
    scopes: dict[str, str]  # name -> "built-in" | "global"

    def get(self, name: str) -> ProviderSpec | None:
        return self.entries.get(name)

    def source_of(self, name: str) -> str:
        """``"built-in"`` or ``"global"``, or ``""`` when *name* is not in the catalog."""
        return self.scopes.get(name, "")


def _load_builtin_providers() -> dict[str, ProviderSpec]:
    directory = _cfg.PROVIDER_TEMPLATES_DIR
    entries: dict[str, ProviderSpec] = {}
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.yaml")):
        try:
            spec = load_provider_document(path)
        except ProviderError:
            continue
        entries[spec.name] = spec
    return entries


def _load_global_providers() -> dict[str, ProviderSpec]:
    raw = _store.read_json(_cfg.PROVIDERS_FILE)
    providers = raw.get("providers") if isinstance(raw, dict) else None
    entries: dict[str, ProviderSpec] = {}
    if not isinstance(providers, dict):
        return entries
    for name, block in providers.items():
        if not isinstance(block, dict):
            continue
        try:
            entries[str(name)] = ProviderSpec.model_validate(block)
        except ValidationError:
            continue
    return entries


def load_catalog() -> Catalog:
    """The merged provider catalog. Runs the one-shot ``fleet.json -> providers`` migration
    first (idempotent -- a no-op once migrated, or when there was nothing to migrate)."""
    migrate_fleet_providers()
    entries: dict[str, ProviderSpec] = {}
    scopes: dict[str, str] = {}
    for name, spec in _load_builtin_providers().items():
        entries[name] = spec
        scopes[name] = "built-in"
    for name, spec in _load_global_providers().items():
        entries[name] = spec
        scopes[name] = "global"
    return Catalog(entries=entries, scopes=scopes)


def save_provider(spec: ProviderSpec) -> None:
    """Write *spec* into the global catalog (``config.PROVIDERS_FILE``), through
    ``edges/store.py`` -- the sole writer of docket-owned JSON."""

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        providers = current.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        providers[spec.name] = spec.model_dump(by_alias=True, exclude_none=True)
        current["providers"] = providers
        return current

    _store.read_modify_write(_cfg.PROVIDERS_FILE, _update)


def delete_provider(name: str) -> bool:
    """Remove *name* from the global catalog. Returns False when it wasn't there (a built-in
    of the same name, if any, is unaffected -- this never touches the built-in scope)."""
    removed = False

    def _update(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        providers = current.get("providers")
        if not isinstance(providers, dict) or name not in providers:
            return None
        del providers[name]
        current["providers"] = providers
        removed = True
        return current

    _store.read_modify_write(_cfg.PROVIDERS_FILE, _update)
    return removed


def resolve_credential(spec: ProviderSpec) -> tuple[str, str]:
    """Resolve *spec*'s credential value: ``(value, source)``, source one of ``"override"``
    (``DOCKET_LLM_API_KEY``), ``"env"``, ``"store"`` or ``"none"``, checked in that order per
    name in ``auth.credentials``."""
    override = os.environ.get("DOCKET_LLM_API_KEY", "").strip()
    if override:
        return override, "override"
    if spec.auth.type == "none":
        return "", "none"
    for name in spec.auth.credentials:
        value = os.environ.get(name, "").strip()
        if value:
            return value, "env"
    from docket.core import secrets as _secrets

    for name in spec.auth.credentials:
        value = _secrets.secret_value(name) or ""
        if value:
            return value, "store"
    return "", "none"


def _is_loopback(base_url: str) -> bool:
    return "127.0.0.1" in base_url or "localhost" in base_url


def _is_placeholder_key(value: str) -> bool:
    return value.strip() in ("", "local")


def _all_zero_cost(raw_models: Any) -> bool:
    if not isinstance(raw_models, list) or not raw_models:
        return False
    for entry in raw_models:
        if not isinstance(entry, dict):
            return False
        cost = entry.get("cost")
        if not isinstance(cost, dict):
            return False
        if float(cost.get("input", 1) or 0) != 0 or float(cost.get("output", 1) or 0) != 0:
            return False
    return True


def _migrate_one(name: str, block: dict[str, Any]) -> bool:
    """Port one ``fleet.json -> providers`` block into the global catalog. Returns True when a
    literal credential value was moved into the central secret store (for the audit count)."""
    base_url = str(block.get("baseUrl") or "").strip()
    if not base_url:
        return False

    raw_models = block.get("models")
    models: list[ModelRow] = []
    if isinstance(raw_models, list):
        for entry in raw_models:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or "").strip()
            if not model_id:
                continue
            ctx = entry.get("contextWindow")
            max_tok = entry.get("maxTokens")
            models.append(
                ModelRow(
                    id=model_id,
                    contextWindow=ctx if isinstance(ctx, int) and ctx > 0 else None,
                    maxTokens=max_tok if isinstance(max_tok, int) and max_tok > 0 else None,
                )
            )

    is_local = _is_loopback(base_url) or _all_zero_cost(raw_models)

    raw_key = str(block.get("apiKey") or "").strip()
    moved_secret = False
    if _is_placeholder_key(raw_key):
        auth = AuthSpec(type="none")
    else:
        from docket.core import audit as _audit
        from docket.core import secrets as _secrets

        credential_name = f"{name.upper().replace('-', '_')}_API_KEY"
        secrets = _secrets.load_secrets()
        secrets[credential_name] = raw_key
        _secrets.save_secrets(secrets)
        _secrets.touch_meta(credential_name, "added")
        _audit.audit_log(
            "provider.migrate", f"moved {name}'s apiKey into the secret store as {credential_name}"
        )
        moved_secret = True
        auth = AuthSpec(type="bearer", credentials=[credential_name])

    spec = ProviderSpec(
        name=name,
        dialect="openai-chat",
        base_url=base_url,
        auth=auth,
        local=is_local,
        models=models,
        note="",
    )
    save_provider(spec)
    return moved_secret


def migrate_fleet_providers() -> None:
    """Port ``fleet.json -> providers`` into the global catalog once, then clear the fleet
    field. A no-op once migrated, or when there was nothing to migrate."""
    from docket.core import fleet as _fleet

    cfg = _fleet.load_fleet()
    if not cfg.providers:
        return

    for name, block in cfg.providers.items():
        if isinstance(block, dict):
            _migrate_one(name, block)

    def _clear(current: dict[str, Any]) -> dict[str, Any] | None:
        if not current.get("providers"):
            return None
        current["providers"] = {}
        return current

    _store.read_modify_write(_cfg.FLEET_FILE, _clear)


def ping_endpoint(base_url: str, timeout: float = 5.0) -> bool:
    """Return True if GET <base_url>/models responds (any 2xx/whatever, no error).

    Kept as a standalone function so tests can monkeypatch it (no real network in tests).
    """
    url = f"{base_url}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


@dataclass(frozen=True)
class ProviderRegistration:
    """Outcome of register_local_provider(). Rendered by cli/_provider.py."""

    name: str
    base_url: str
    model_id: str
    model_name: str
    ctx: int
    max_tokens: int
    reachable: bool
    changed: bool


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
    from docket.core import secrets as _secrets
    from docket.edges.adapters import llm as _llm

    provider, _, _model_id = model.partition("/")
    credential_names = PROVIDER_CREDENTIAL_NAMES.get(provider, ())
    credential_name = credential_names[0] if credential_names else ""
    credential_present = any(
        bool(os.environ.get(name, "").strip()) or bool(_secrets.secret_value(name))
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


def register_local_provider(
    name: str = DEFAULT_PROVIDER,
    base_url: str = DEFAULT_BASE_URL,
    model_id: str = DEFAULT_MODEL_ID,
    model_name: str = DEFAULT_MODEL_NAME,
    ctx: int = DEFAULT_CTX,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ProviderRegistration:
    """Ping the endpoint and register the provider in docket's own provider catalog. Pure
    orchestration -- no output. Idempotent: re-running with the same arguments writes nothing.
    ``model_name`` has no home in the document; kept only so old callers keep compiling."""
    reachable = ping_endpoint(base_url)
    changed = False
    if reachable:
        desired = ProviderSpec(
            name=name,
            dialect="openai-chat",
            base_url=base_url,
            auth=AuthSpec(type="none"),
            local=True,
            models=[ModelRow(id=model_id, contextWindow=ctx, maxTokens=max_tokens)],
        )
        existing = load_catalog().get(name)
        if existing != desired:
            save_provider(desired)
            changed = True
    return ProviderRegistration(
        name=name,
        base_url=base_url,
        model_id=model_id,
        model_name=model_name,
        ctx=ctx,
        max_tokens=max_tokens,
        reachable=reachable,
        changed=changed,
    )
