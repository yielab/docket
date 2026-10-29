"""Provider catalog: the model providers docket knows, as `kind: provider` documents.

A provider is a `ProviderSpec` -- name, dialect, base URL, named credentials (never a value),
selectable models with optional pricing, and named presets -- loaded the same way a role or
policy is (model-profiles.spec.md "Provider catalog"). Two scopes, nearest-wins by name: built-in
(`kernel.templates.PROVIDER_TEMPLATES_DIR`, the documents under `templates/providers/`) and global
(`Home.providers_file`, the operator's own). `models/application/endpoint.py`'s `resolve_endpoint` reads
the merged catalog; this module has no knowledge of terminals. `teams/model_selection.py`'s
`presets`/`preset_table`/`is_local_provider`/`is_marketplace`/`price_for`/`rank_anchors` are the
only readers of the catalog's presets and pricing; every other per-provider fact (base URLs,
credential names, key-format prefixes) derives from this module too, so no module keeps its
own copy.

`register_provider` verifies a document against its live `/models` route with the resolved
credential (`models/adapters/openai_http.py::probe_models` does the socket work; `verify_endpoint` here
stays pure) and classifies the result instead of collapsing it to a boolean -- see
model-profiles.spec.md "Provider readiness" 3 and ADR 0011 §4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

import docket.kernel.templates as _templates
from docket.agent.ports import ModelLimits
from docket.kernel.errors import DocumentError, InvalidInput
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.models import document_fields as _documents
from docket.platform import read_json, read_modify_write

if TYPE_CHECKING:
    pass
from docket.governance import secrets as _secrets

_RANK_RE = re.compile(r"^(economy|standard|premium)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ProviderError(DocumentError):
    """A provider document failed to load, or a catalog write was rejected."""


class AuthSpec(BaseModel):
    """How a request authenticates against a provider -- names only, never a value.
    ``header`` names the request header a ``type: header`` credential rides on (Azure
    OpenAI's ``api-key``); required exactly when ``type`` is ``"header"``."""

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["bearer", "header", "none"]
    header: str = ""
    credentials: list[str] = Field(default_factory=list)

    @field_validator("credentials")
    @classmethod
    def _valid_names(cls, value: list[str]) -> list[str]:
        for name in value:
            _documents.check_credential_name(name, "auth.credentials")
        return value

    @model_validator(mode="after")
    def _header_required_for_header_auth(self) -> AuthSpec:
        if self.type == "header" and not self.header:
            raise InvalidInput("auth.header is required when auth.type is 'header'")
        return self


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
    `teams/model_selection.py`'s old `PRESET_TABLE` held per row, minus the fields (``key``,
    ``cost``) that are derived from the owning `ProviderSpec` instead of stored twice."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    ranks: dict[str, str]
    note: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _documents.check_name(value, "preset")

    @field_validator("ranks")
    @classmethod
    def _closed_rank_names(cls, value: dict[str, str]) -> dict[str, str]:
        for rank in value:
            if not _RANK_RE.match(rank):
                raise InvalidInput(f"'{rank}' is not a valid rank (economy, standard, premium)")
        return value


class Sampling(BaseModel):
    """The sampling a row declares; a field left ``None`` is never sent (docket supplies no
    default, so the endpoint's own applies)."""

    model_config = ConfigDict(populate_by_name=True)

    temperature: float | None = Field(None, ge=0, le=2)
    top_p: float | None = Field(None, alias="topP", gt=0, le=1)


class BudgetShares(BaseModel):
    """The read window and the tool-output cap as shares of the context window, each in (0, 1]
    or ``None`` for no share."""

    model_config = ConfigDict(populate_by_name=True)

    read_window: float | None = Field(None, alias="readWindow", gt=0, le=1)
    tool_output: float | None = Field(None, alias="toolOutput", gt=0, le=1)


ProfileName = Literal["hosted", "local"]
ToolSurface = Literal["full", "minimal"]
DescriptionMode = Literal["full", "compact"]
ToolChoiceMode = Literal["auto", "forced-on-close"]


@dataclass(frozen=True)
class ProfileBudgets:
    """The read window and the tool-output cap, in characters, that a profile's shares make for
    one model's context window; ``None`` where no share is declared or the window is unknown."""

    read_window_chars: int | None = None
    tool_output_chars: int | None = None


@dataclass(frozen=True)
class ModelProfile:
    """How the harness adapts to a model, as data (model-profiles.spec.md "Model profiles").
    ``tool_surface`` and ``budgets`` are resolved here and applied elsewhere; no field is ever
    derived from a model id."""

    name: ProfileName
    sampling: Sampling
    tool_surface: ToolSurface
    descriptions: DescriptionMode
    tool_choice: ToolChoiceMode
    shares: BudgetShares
    budgets: ProfileBudgets = ProfileBudgets()


BUILTIN_PROFILES: dict[str, ModelProfile] = {
    "hosted": ModelProfile("hosted", Sampling(), "full", "full", "auto", BudgetShares()),
    "local": ModelProfile(
        "local",
        Sampling(),
        "minimal",
        "compact",
        "forced-on-close",
        BudgetShares(readWindow=0.05, toolOutput=0.02),
    ),
}


def _budgets_of(shares: BudgetShares, context_window_tokens: int | None) -> ProfileBudgets:
    """``floor(window * share * bytes-per-token)`` for each declared share; nothing for an
    unknown window (never a guessed one)."""
    if context_window_tokens is None:
        return ProfileBudgets()
    chars = current_home().context_bytes_per_token * context_window_tokens

    def _chars(share: float | None) -> int | None:
        return None if share is None else int(chars * share)

    return ProfileBudgets(_chars(shares.read_window), _chars(shares.tool_output))


class ProviderSpec(BaseModel):
    """A `kind: provider` document -- see specs/functional/model-profiles.spec.md
    ("Provider catalog"). ``kind`` itself is the document envelope's concern
    (`load_provider_document`/`teams.config_docs`), not a field of the parsed model."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    dialect: Literal["openai-chat", "anthropic-messages"] = "openai-chat"
    base_url: str = Field(alias="baseUrl")
    auth: AuthSpec
    local: bool = False
    marketplace: bool = False
    credential_prefix: str = Field("", alias="credentialPrefix")
    prices_as_of: str = Field("", alias="pricesAsOf")
    models: list[ModelRow] = Field(default_factory=list)
    presets: list[Preset] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    profile: ProfileName | None = None
    sampling: Sampling | None = None
    tool_surface: ToolSurface | None = Field(None, alias="toolSurface")
    descriptions: DescriptionMode | None = None
    tool_choice: ToolChoiceMode | None = Field(None, alias="toolChoice")
    budgets: BudgetShares | None = None

    @field_validator("headers")
    @classmethod
    def _no_reserved_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _documents.reject_reserved_headers(value)

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
        return _documents.check_name(value, "provider")

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        return _documents.check_http_url(value)

    @field_validator("prices_as_of")
    @classmethod
    def _valid_prices_as_of(cls, value: str) -> str:
        if value and not _DATE_RE.match(value):
            raise InvalidInput(f"'{value}' is not a YYYY-MM-DD date")
        return value

    @field_validator("models")
    @classmethod
    def _unique_ids(cls, value: list[ModelRow]) -> list[ModelRow]:
        seen: set[str] = set()
        for row in value:
            if row.id in seen:
                raise InvalidInput(f"duplicate model id '{row.id}'")
            seen.add(row.id)
        return value

    @model_validator(mode="after")
    def _prices_as_of_required_with_a_price(self) -> ProviderSpec:
        if not self.prices_as_of and any(row.price is not None for row in self.models):
            raise InvalidInput("pricesAsOf is required when any model row carries a price")
        return self


def profile_of(spec: ProviderSpec, model_id: str = "") -> ModelProfile:
    """*spec*'s profile for *model_id*: the one it names, else ``local`` for a ``local: true`` row
    and ``hosted`` for any other, with each field the row declares laid over it and the budgets
    made from the model's resolved context window (none without a *model_id*)."""
    base = BUILTIN_PROFILES[spec.profile or ("local" if spec.local else "hosted")]
    shares = spec.budgets or base.shares
    window = resolve_limits(spec, model_id).context_window if model_id else None
    return ModelProfile(
        name=base.name,
        sampling=spec.sampling or base.sampling,
        tool_surface=spec.tool_surface or base.tool_surface,
        descriptions=spec.descriptions or base.descriptions,
        tool_choice=spec.tool_choice or base.tool_choice,
        shares=shares,
        budgets=_budgets_of(shares, window),
    )


def _validation_to_provider_error(path: Path | str, exc: ValidationError) -> ProviderError:
    """Refine pydantic's first error into a ``ProviderError`` naming the field and, for a
    closed-vocabulary failure (an unknown ``dialect``/``auth.type``), the valid values --
    the same refinement ``teams/config_docs.py``'s ``_refine_with_model`` does for a role."""
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

    if spec.auth.type in ("bearer", "header") and not spec.auth.credentials:
        raise ProviderError(
            p, "auth.credentials", f"{spec.auth.type} auth requires at least one credential name"
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
    directory = _templates.PROVIDER_TEMPLATES_DIR
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
    return _global_providers_from(read_json(current_home().providers_file))


def _global_providers_from(raw: object) -> dict[str, ProviderSpec]:
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
    """The merged provider catalog: a global document overrides the built-in of the same name."""
    return _merged_catalog(_load_global_providers())


def credential_sources() -> set[str]:
    """The credential names the secret store and the provider catalog add to the built-in two."""
    names = set(_secrets.secrets_keys())
    for spec in load_catalog().entries.values():
        names.update(spec.auth.credentials)
    return names


def _merged_catalog(global_entries: dict[str, ProviderSpec]) -> Catalog:
    entries: dict[str, ProviderSpec] = {}
    scopes: dict[str, str] = {}
    for name, spec in _load_builtin_providers().items():
        entries[name] = spec
        scopes[name] = "built-in"
    for name, spec in global_entries.items():
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


_RANK_SOURCE = "anthropic"
_REQUIRED_RANKS = ("economy", "standard")


def _anchors_of(spec: ProviderSpec | None) -> dict[str, str]:
    """The rank anchors (``economy``/``standard``/``premium`` -> ``provider/model``) carried by the
    rank-source provider's own preset, for the role defaults every other model table derives from.
    Raises ``DocumentError`` naming the first required anchor the document does not carry."""
    preset = None
    if spec is not None:
        preset = next((p for p in spec.presets if p.name == _RANK_SOURCE), None)
    for rank in _REQUIRED_RANKS:
        if preset is None or not preset.ranks.get(rank):
            raise DocumentError(
                current_home().providers_file,
                f"providers.{_RANK_SOURCE}.presets",
                f"rank anchor '{rank}' is missing: the {_RANK_SOURCE} provider needs a preset "
                f"named '{_RANK_SOURCE}' that ranks {' and '.join(_REQUIRED_RANKS)}",
                valid=_REQUIRED_RANKS,
            )
    assert preset is not None
    return {rank: f"{_RANK_SOURCE}/{model_id}" for rank, model_id in preset.ranks.items()}


def rank_anchors_of(catalog: Catalog) -> dict[str, str]:
    """``_anchors_of`` for the rank-source provider as *catalog* holds it."""
    return _anchors_of(catalog.get(_RANK_SOURCE))


def check_rank_anchors(spec: ProviderSpec) -> None:
    """Refuse a document that would leave the rank-source provider without its anchors."""
    if spec.name == _RANK_SOURCE:
        _anchors_of(_with_inherited_identity(spec))


def save_provider(spec: ProviderSpec) -> None:
    """Write *spec* into the global catalog (``Home.providers_file``), through
    ``platform/store.py`` -- the sole writer of docket-owned JSON."""
    spec = _with_inherited_identity(spec)

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        providers = current.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        providers[spec.name] = spec.model_dump(by_alias=True, exclude_none=True)
        current["providers"] = providers
        return current

    read_modify_write(current_home().providers_file, _update)


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

    read_modify_write(current_home().providers_file, _update)
    return removed


def resolve_credential(spec: ProviderSpec) -> tuple[str, str]:
    """Resolve *spec*'s credential value: ``(value, source)``, source one of ``"override"``
    (``DOCKET_LLM_API_KEY``), ``"env"``, ``"store"`` or ``"none"``, checked in that order per
    name in ``auth.credentials``."""
    override = _process.env_value("DOCKET_LLM_API_KEY")
    if override:
        return override, "override"
    if spec.auth.type == "none":
        return "", "none"
    for name in spec.auth.credentials:
        value = _process.env_value(name)
        if value:
            return value, "env"

    for name in spec.auth.credentials:
        value = _secrets.secret_value(name) or ""
        if value:
            return value, "store"
    return "", "none"


LimitSource = Literal["declared", "observed", "unknown"]


@dataclass(frozen=True)
class ResolvedLimits:
    """A model's context window and output cap, each with where it came from (declared in the
    catalog row, observed from the provider's ``/models``, or unknown -- never a default)."""

    context_window: int | None
    max_output: int | None
    context_window_source: LimitSource
    max_output_source: LimitSource
    observed_at: str

    @property
    def source(self) -> LimitSource:
        """One word for the row: ``declared`` if any limit is, else ``observed`` if any is."""
        sources = (self.context_window_source, self.max_output_source)
        for kind in ("declared", "observed"):
            if kind in sources:
                return kind
        return "unknown"


def _observed_entry(provider: str) -> dict[str, Any]:
    providers = read_json(current_home().provider_models_file).get("providers")
    entry = providers.get(provider) if isinstance(providers, dict) else None
    return entry if isinstance(entry, dict) else {}


def observed_limits(provider: str, model_id: str) -> ModelLimits | None:
    """What *provider*'s ``/models`` last published for *model_id*, or ``None`` when that model
    was never observed. The only reader of ``Home.provider_models_file``."""
    models = _observed_entry(provider).get("models")
    row = models.get(model_id) if isinstance(models, dict) else None
    if not isinstance(row, dict):
        return None

    def _limit(value: object) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
        )

    return ModelLimits(_limit(row.get("contextWindow")), _limit(row.get("maxTokens")))


def observed_at(provider: str) -> str:
    """The ``YYYY-MM-DD`` *provider* was last observed, or ``""`` when it never was."""
    value = _observed_entry(provider).get("observedAt")
    return value if isinstance(value, str) else ""


def resolve_limits(spec: ProviderSpec, model_id: str) -> ResolvedLimits:
    """*model_id*'s limits under *spec*, each limit declared > observed > unknown."""
    exact = next((row for row in spec.models if row.id == model_id), None)
    seen = observed_limits(spec.name, model_id)
    when = observed_at(spec.name) if seen is not None else ""

    def _pick(declared: int | None, found: int | None) -> tuple[int | None, LimitSource]:
        if declared is not None:
            return declared, "declared"
        if found is not None:
            return found, "observed"
        return None, "unknown"

    window, window_source = _pick(
        exact.context_window if exact else None, seen.context_window if seen else None
    )
    output, output_source = _pick(
        exact.max_tokens if exact else None, seen.max_output if seen else None
    )
    return ResolvedLimits(window, output, window_source, output_source, when)
