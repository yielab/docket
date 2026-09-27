"""Provider catalog: the model providers docket knows, as `kind: provider` documents.

A provider is a `ProviderSpec` -- name, dialect, base URL, named credentials (never a value),
selectable models with optional pricing, and named presets -- loaded the same way a role or
policy is (model-profiles.spec.md "Provider catalog"). Two scopes, nearest-wins by name: built-in
(`config.PROVIDER_TEMPLATES_DIR`, the documents under `templates/providers/`) and global
(`config.PROVIDERS_FILE`, the operator's own). `edges/adapters/llm.py`'s `resolve_endpoint` reads
the merged catalog; this module has no knowledge of terminals. `core/models_policy.py`'s
`presets`/`preset_table`/`is_local_provider`/`is_marketplace`/`price_for`/`rank_anchors` are the
only readers of the catalog's presets and pricing; every other per-provider fact (base URLs,
credential names, key-format prefixes) derives from this module too, so no module keeps its
own copy.

`register_provider` verifies a document against its live `/models` route with the resolved
credential (`edges/adapters/llm.py::probe_models` does the socket work; `verify_endpoint` here
stays pure) and classifies the result instead of collapsing it to a boolean -- see
model-profiles.spec.md "Provider readiness" 3 and ADR 0011 §4. `migrate_fleet_providers` ports a
pre-catalog `fleet.json -> providers` block in once; a literal API key there moves into the
secret store, referenced by name, never copied into the document.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

import docket.config as _cfg
from docket.edges import store as _store

if TYPE_CHECKING:
    from docket.edges.adapters.llm import ProbeResult

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RANK_RE = re.compile(r"^(economy|standard|premium)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


class Price(BaseModel):
    """USD per million tokens. ``cacheRead``/``cacheWrite`` default to 0 for a provider that
    never discounts a cache hit -- absence is not the same claim as a priced $0.00 hit, but
    every provider docket ships a price row for today prices every field explicitly."""

    model_config = ConfigDict(populate_by_name=True)

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(0.0, alias="cacheRead", ge=0)
    cache_write: float = Field(0.0, alias="cacheWrite", ge=0)


class ModelRow(BaseModel):
    """One selectable model id, its exact limits (either may be unknown), and its optional
    price -- a model with no ``price`` reports cost as ``n/a`` (or the marketplace/local
    variant), never a fabricated figure."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    context_window: int | None = Field(None, alias="contextWindow", gt=0)
    max_tokens: int | None = Field(None, alias="maxTokens", gt=0)
    price: Price | None = None


class Preset(BaseModel):
    """A named rank triple attached to the provider that defines it -- what
    `core/models_policy.py`'s old `PRESET_TABLE` held per row, minus the fields (``key``,
    ``cost``) that are derived from the owning `ProviderSpec` instead of stored twice."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    ranks: dict[str, str]
    note: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"'{value}' is not a valid preset name (^[a-z0-9][a-z0-9-]*$)")
        return value

    @field_validator("ranks")
    @classmethod
    def _closed_rank_names(cls, value: dict[str, str]) -> dict[str, str]:
        for rank in value:
            if not _RANK_RE.match(rank):
                raise ValueError(f"'{rank}' is not a valid rank (economy, standard, premium)")
        return value


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
    marketplace: bool = False
    credential_prefix: str = Field("", alias="credentialPrefix")
    prices_as_of: str = Field("", alias="pricesAsOf")
    models: list[ModelRow] = Field(default_factory=list)
    presets: list[Preset] = Field(default_factory=list)
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

    @field_validator("prices_as_of")
    @classmethod
    def _valid_prices_as_of(cls, value: str) -> str:
        if value and not _DATE_RE.match(value):
            raise ValueError(f"'{value}' is not a YYYY-MM-DD date")
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

    @model_validator(mode="after")
    def _prices_as_of_required_with_a_price(self) -> ProviderSpec:
        if not self.prices_as_of and any(row.price is not None for row in self.models):
            raise ValueError("pricesAsOf is required when any model row carries a price")
        return self


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


_INHERITABLE_IDENTITY_FIELDS = ("presets", "marketplace", "credential_prefix", "prices_as_of")


def _with_inherited_identity(spec: ProviderSpec) -> ProviderSpec:
    """Fill the identity fields *spec* left unset (``model_fields_set``, so an explicit clear
    still wins) from the built-in of the same name: an endpoint write under a built-in's name
    must not erase its presets or pricing. Also applied before an on-disk comparison."""
    missing = [f for f in _INHERITABLE_IDENTITY_FIELDS if f not in spec.model_fields_set]
    if not missing:
        return spec
    builtin = _load_builtin_providers().get(spec.name)
    if builtin is None:
        return spec
    return spec.model_copy(update={f: getattr(builtin, f) for f in missing})


def save_provider(spec: ProviderSpec) -> None:
    """Write *spec* into the global catalog (``config.PROVIDERS_FILE``), through
    ``edges/store.py`` -- the sole writer of docket-owned JSON."""
    spec = _with_inherited_identity(spec)

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
    """Outcome of ``register_provider``. Rendered by ``cli/_provider.py``."""

    spec: ProviderSpec
    verification: ProviderVerification
    changed: bool


def register_provider(spec: ProviderSpec, *, probe: ProbeResult | None = None) -> Registration:
    """Verify *spec* with the resolved credential and classify the result; persist only when
    reachable (model-profiles.spec.md "Provider readiness" 3). The default probe builds an
    ``Endpoint`` straight from *spec*, never a saved entry, since nothing is written yet."""
    if probe is None:
        from docket.core.llm import Endpoint
        from docket.edges.adapters.llm import probe_models

        credential_value, _source = resolve_credential(spec)
        endpoint = Endpoint(
            base_url=spec.base_url,
            model_id="x",
            api_key=credential_value,
            provider=spec.name,
        )
        probe = probe_models(endpoint)

    verification = verify_endpoint(spec, probe)
    if not verification.reachable:
        return Registration(spec=spec, verification=verification, changed=False)

    existing = load_catalog().get(spec.name)
    desired = _with_inherited_identity(spec)
    changed = existing != desired
    save_provider(spec)

    from docket.core import audit as _audit

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
                _cfg.PROVIDERS_FILE,
                "name",
                f"'{name}' is a built-in provider with no global override -- nothing to remove",
            )
        raise ProviderError(_cfg.PROVIDERS_FILE, "name", f"'{name}' is not in the provider catalog")

    from docket.core import audit as _audit

    _audit.audit_log("provider.remove", f"name={name}")


def export_provider(name: str) -> str:
    """Render *name*'s resolved catalog entry as a ``kind: provider`` document -- the inverse
    of ``load_provider_document``, proven to round-trip (export -> fresh home -> add ->
    identical ``show --json``)."""
    spec = load_catalog().get(name)
    if spec is None:
        raise ProviderError(_cfg.PROVIDERS_FILE, "name", f"'{name}' is not in the provider catalog")

    try:
        import yaml as _yaml
    except ImportError:
        raise ProviderError(
            _cfg.PROVIDERS_FILE, "file", "PyYAML not installed -- run: pip install pyyaml"
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
    from docket.core import secrets as _secrets
    from docket.edges.adapters import llm as _llm

    provider, _, _model_id = model.partition("/")
    spec = load_catalog().get(provider)
    credential_names = tuple(spec.auth.credentials) if spec else ()
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
