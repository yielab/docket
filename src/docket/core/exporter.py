"""Exporter catalog: the observability destinations docket knows, as `kind: exporter`
documents (ADR 0014 §4) -- a deliberate copy of `core/provider.py`'s shape (name, dialect,
endpoint, named credentials, never a value) with the model/price/preset fields dropped and
destination-shaped ones added: `resource`/`aliases`, `events`, `privacy`/`share` (what a
document shares beyond structure -- ADR 0015 §1), and `enabled` (a present credential never activates an
exporter by itself). Two scopes, nearest-wins by name: built-in and global
(`config.EXPORTERS_FILE`, the operator's own).

This module owns the document, the catalog, and pure classification; the wire encoding and
CLI surface live elsewhere.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

import docket.config as _cfg
from docket.core import privacy as _privacy
from docket.core.trace import EVENT_TYPES
from docket.edges import store as _store

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CREDENTIAL_VALUE_RE = re.compile(r"^[A-Za-z0-9/_\-+.]{20,}$")
_RESERVED_HEADERS = frozenset({"authorization", "content-type", "accept"})

ExporterState = Literal["enabled", "needs credential", "disabled", "unreachable"]


class ExporterError(Exception):
    """*file*: *field*: *message* (valid: ...) -- an exporter document failed to load or a
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


def _validate_credential_names(value: list[str]) -> list[str]:
    for name in value:
        if _CREDENTIAL_NAME_RE.match(name):
            continue
        if _CREDENTIAL_VALUE_RE.match(name):
            raise ValueError(
                f"'{name}' looks like a credential VALUE, not a name -- "
                "auth.credentials names a stored secret, it never carries one"
            )
        raise ValueError(f"'{name}' is not a valid credential name (^[A-Z][A-Z0-9_]*$)")
    return value


_AUTH_ARITY: dict[str, int] = {"none": 0, "bearer": 1, "header": 1, "basic": 2}


class ExporterAuth(BaseModel):
    """How a request authenticates -- names only, never a value. ``header`` names the request
    header a ``type: header`` credential rides on, required exactly when ``type`` is
    ``"header"``. ``basic`` is exactly two ordered names: username, then password."""

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["bearer", "header", "basic", "none"]
    header: str = ""
    credentials: list[str] = Field(default_factory=list)

    @field_validator("credentials")
    @classmethod
    def _valid_names(cls, value: list[str]) -> list[str]:
        return _validate_credential_names(value)

    @model_validator(mode="after")
    def _header_required_for_header_auth(self) -> ExporterAuth:
        if self.type == "header" and not self.header:
            raise ValueError("auth.header is required when auth.type is 'header'")
        return self

    @model_validator(mode="after")
    def _credential_arity(self) -> ExporterAuth:
        expected = _AUTH_ARITY[self.type]
        if len(self.credentials) != expected:
            noun = "credential name" if expected == 1 else "credential names"
            raise ValueError(
                f"auth.type '{self.type}' requires exactly {expected} {noun}, "
                f"got {len(self.credentials)}"
            )
        return self


class ExporterSpec(BaseModel):
    """A `kind: exporter` document -- see observability-export.spec.md ("Exporter documents").
    Unlike a role/pipeline/policy/pod short form, this model IS the canonical, only parsed
    shape; there is no separate wire format underneath it."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["exporter"]
    name: str
    dialect: Literal["otlp-http"] = "otlp-http"
    endpoint: str
    auth: ExporterAuth = Field(default_factory=lambda: ExporterAuth(type="none"))
    headers: dict[str, str] = Field(default_factory=dict)
    resource: dict[str, str] = Field(default_factory=lambda: {"service.name": "docket"})
    aliases: dict[str, str] = Field(default_factory=dict)
    events: Literal["default", "all"] | list[str] = "default"
    privacy: Literal["minimal", "actions", "conversation", "full"] | None = None
    share: list[str] | None = None
    content_max_chars: int = Field(4000, alias="contentMaxChars", gt=0, le=100_000)
    enabled: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _resolve_privacy(self) -> ExporterSpec:
        try:
            _privacy.resolve(self.privacy, self.share)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @property
    def privacy_label(self) -> str:
        """The resolved privacy level name -- `"minimal"` when neither `privacy` nor `share`
        is set."""
        label, _classes = _privacy.resolve(self.privacy, self.share)
        return label

    @property
    def privacy_classes(self) -> frozenset[str]:
        """The resolved set of content classes this exporter's document grants beyond bare
        structure -- the empty set when neither `privacy` nor `share` is set."""
        _label, classes = _privacy.resolve(self.privacy, self.share)
        return classes

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"'{value}' is not a valid exporter name (^[a-z0-9][a-z0-9-]*$)")
        return value

    @field_validator("endpoint")
    @classmethod
    def _valid_endpoint(cls, value: str) -> str:
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError(f"'{value}' must be an http:// or https:// URL")
        return value

    @field_validator("headers")
    @classmethod
    def _no_reserved_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if key.strip().lower() in _RESERVED_HEADERS:
                raise ValueError(
                    f"'{key}' is a reserved header name "
                    "(authorization, content-type, accept are sent by docket itself)"
                )
        return value

    @field_validator("events")
    @classmethod
    def _valid_events(cls, value: Literal["default", "all"] | list[str]) -> Any:
        if isinstance(value, list):
            for event in value:
                if event not in EVENT_TYPES:
                    raise ValueError(f"'{event}' is not a known trace event type")
        return value


def _validation_to_exporter_error(path: Path | str, exc: ValidationError) -> ExporterError:
    """Refine pydantic's first error into an ``ExporterError`` naming the field and, for a
    closed-vocabulary failure (an unknown ``dialect``/``auth.type``), the valid values -- the
    same refinement ``core/provider.py``'s ``_validation_to_provider_error`` does."""
    first = exc.errors()[0]
    field_name = ".".join(str(p) for p in first["loc"]) if first["loc"] else ""
    valid: tuple[str, ...] = ()
    expected = (first.get("ctx") or {}).get("expected")
    if isinstance(expected, str):
        valid = tuple(
            v.strip("'\" ") for v in re.split(r"\s+or\s+|,\s*", expected) if v.strip("'\" ")
        )
    return ExporterError(path, field_name, first["msg"], valid)


def load_exporter_document(path: str | Path) -> ExporterSpec:
    """Read *path* as a `kind: exporter` document. Raises ``ExporterError`` naming the file,
    field and message on any failure -- bad YAML, missing ``kind``/``name``, an unknown
    ``dialect``/``auth.type``, or a credential-arity/credential-shaped-value mismatch."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExporterError(p, "file", f"cannot read file: {exc}") from exc

    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ExporterError(p, "file", "PyYAML not installed -- run: pip install pyyaml") from None
    try:
        raw = _yaml.safe_load(text)
    except Exception as exc:
        raise ExporterError(p, "file", f"YAML parse error: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ExporterError(p, "file", f"document must be a mapping (got {type(raw).__name__})")

    kind = raw.get("kind")
    if kind != "exporter":
        raise ExporterError(p, "kind", f"expected 'exporter', got {kind!r}", valid=("exporter",))
    if not raw.get("name"):
        raise ExporterError(p, "name", "an exporter document requires 'name'")

    try:
        return ExporterSpec.model_validate(raw)
    except ValidationError as exc:
        raise _validation_to_exporter_error(p, exc) from exc


@dataclass(frozen=True)
class Catalog:
    """The merged exporter catalog: the operator's own (global) entries override a built-in of
    the same name, nearest-wins -- the same rule as the provider catalog."""

    entries: dict[str, ExporterSpec]
    scopes: dict[str, str]  # name -> "built-in" | "global"

    def get(self, name: str) -> ExporterSpec | None:
        return self.entries.get(name)

    def source_of(self, name: str) -> str:
        """``"built-in"`` or ``"global"``, or ``""`` when *name* is not in the catalog."""
        return self.scopes.get(name, "")


def _load_builtin_exporters() -> dict[str, ExporterSpec]:
    directory = _cfg.EXPORTER_TEMPLATES_DIR
    entries: dict[str, ExporterSpec] = {}
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.yaml")):
        try:
            spec = load_exporter_document(path)
        except ExporterError:
            continue
        entries[spec.name] = spec
    return entries


def _with_inherited_identity(spec: ExporterSpec) -> ExporterSpec:
    """Fill every field *spec* left unset (``model_fields_set``, so an explicit clear still
    wins) from the built-in of the same name -- unlike the provider catalog's narrower field
    list, a global exporter override inherits *every* field it does not set."""
    builtin = _load_builtin_exporters().get(spec.name)
    if builtin is None:
        return spec
    missing = [f for f in spec.model_fields if f not in spec.model_fields_set]
    if not missing:
        return spec
    return spec.model_copy(update={f: getattr(builtin, f) for f in missing})


def _merge_with_builtin_raw(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Fill every key *raw* omits from the built-in document of the same *name*, before
    ``ExporterSpec`` ever parses it -- a partial on-disk override would otherwise fail the
    model's required ``endpoint``/``kind`` fields."""
    builtin = _load_builtin_exporters().get(name)
    if builtin is None:
        return raw
    merged = builtin.model_dump(by_alias=True, exclude_none=True)
    merged.update(raw)
    return merged


def _load_global_exporters() -> dict[str, ExporterSpec]:
    raw = _store.read_json(_cfg.EXPORTERS_FILE)
    exporters = raw.get("exporters") if isinstance(raw, dict) else None
    entries: dict[str, ExporterSpec] = {}
    if not isinstance(exporters, dict):
        return entries
    for name, block in exporters.items():
        if not isinstance(block, dict):
            continue
        merged = _merge_with_builtin_raw(str(name), block)
        merged.setdefault("name", str(name))
        try:
            entries[str(name)] = ExporterSpec.model_validate(merged)
        except ValidationError:
            continue
    return entries


def load_catalog() -> Catalog:
    """The merged exporter catalog: every built-in under ``config.EXPORTER_TEMPLATES_DIR``,
    overridden by the operator's own global entries in ``config.EXPORTERS_FILE``, nearest-wins
    by name."""
    entries: dict[str, ExporterSpec] = {}
    scopes: dict[str, str] = {}
    for name, spec in _load_builtin_exporters().items():
        entries[name] = spec
        scopes[name] = "built-in"
    for name, spec in _load_global_exporters().items():
        entries[name] = spec
        scopes[name] = "global"
    return Catalog(entries=entries, scopes=scopes)


def save_exporter(spec: ExporterSpec) -> None:
    """Write *spec* into the global catalog (``config.EXPORTERS_FILE``), through
    ``edges/store.py`` -- the sole writer of docket-owned JSON."""
    spec = _with_inherited_identity(spec)

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        exporters = current.get("exporters")
        if not isinstance(exporters, dict):
            exporters = {}
        exporters[spec.name] = spec.model_dump(by_alias=True, exclude_none=True)
        current["exporters"] = exporters
        return current

    _store.read_modify_write(_cfg.EXPORTERS_FILE, _update)


def delete_exporter(name: str) -> None:
    """Remove *name* from the global catalog. A built-in with no global override has nothing to
    remove -- ``ExporterError`` names the built-in scope rather than silently no-op'ing."""
    removed = False

    def _update(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        exporters = current.get("exporters")
        if not isinstance(exporters, dict) or name not in exporters:
            return None
        del exporters[name]
        current["exporters"] = exporters
        removed = True
        return current

    _store.read_modify_write(_cfg.EXPORTERS_FILE, _update)
    if removed:
        return

    scope = load_catalog().source_of(name)
    if scope == "built-in":
        raise ExporterError(
            _cfg.EXPORTERS_FILE,
            "name",
            f"'{name}' is a built-in exporter with no global override -- nothing to remove",
        )
    raise ExporterError(_cfg.EXPORTERS_FILE, "name", f"'{name}' is not in the exporter catalog")


def enable_exporter(name: str, overrides: dict[str, Any] | None = None) -> ExporterSpec:
    """Turn *name* on in the global catalog: writes only ``{kind, name, enabled: true,
    <overrides>}``, the minimal patch a nearest-wins read fills in from the built-in of the
    same name at load time. Refuses a name absent from the catalog."""
    if load_catalog().get(name) is None:
        raise ExporterError(_cfg.EXPORTERS_FILE, "name", f"'{name}' is not in the exporter catalog")

    clean = {k: v for k, v in (overrides or {}).items() if k not in ("kind", "name", "enabled")}

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        exporters = current.get("exporters")
        if not isinstance(exporters, dict):
            exporters = {}
        entry = dict(exporters.get(name) or {})
        entry.update(clean)
        entry["kind"] = "exporter"
        entry["name"] = name
        entry["enabled"] = True
        exporters[name] = entry
        current["exporters"] = exporters
        return current

    _store.read_modify_write(_cfg.EXPORTERS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    _audit.audit_log(
        "exporter.enabled",
        f"name={spec.name} privacy={spec.privacy_label} endpoint={spec.endpoint}",
    )
    return spec


def disable_exporter(name: str) -> ExporterSpec:
    """Turn *name* off in the global catalog -- flips ``enabled`` to false, keeping any other
    stored overrides untouched. Credentials in the secret store are never touched. Refuses a
    name absent from the catalog."""
    if load_catalog().get(name) is None:
        raise ExporterError(_cfg.EXPORTERS_FILE, "name", f"'{name}' is not in the exporter catalog")

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        exporters = current.get("exporters")
        if not isinstance(exporters, dict):
            exporters = {}
        entry = dict(exporters.get(name) or {})
        entry["kind"] = "exporter"
        entry["name"] = name
        entry["enabled"] = False
        exporters[name] = entry
        current["exporters"] = exporters
        return current

    _store.read_modify_write(_cfg.EXPORTERS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    _audit.audit_log(
        "exporter.disabled",
        f"name={spec.name} privacy={spec.privacy_label} endpoint={spec.endpoint}",
    )
    return spec


def is_widening(old: frozenset[str], new: frozenset[str]) -> bool:
    """True when *new* grants a content class *old* does not -- an equal or narrower set of
    classes returns ``False``. Pure; used by the CLI to decide whether a privacy change needs
    confirmation."""
    return not new <= old


def set_privacy(
    name: str,
    privacy: str | None = None,
    share: list[str] | None = None,
    content_max_chars: int | None = None,
) -> ExporterSpec:
    """Change *name*'s privacy fields, writing only the changed key(s) (setting ``privacy``
    clears ``share`` and vice versa). Refuses an unknown name or bad value; audits
    ``exporter.privacy`` with the old/new label and the endpoint's host, never content."""
    current = load_catalog().get(name)
    if current is None:
        raise ExporterError(_cfg.EXPORTERS_FILE, "name", f"'{name}' is not in the exporter catalog")

    old_label = current.privacy_label
    if privacy is None and share is None and content_max_chars is None:
        return current

    if privacy is not None or share is not None:
        try:
            new_label, _new_classes = _privacy.resolve(privacy, share)
        except ValueError as exc:
            raise ExporterError(_cfg.EXPORTERS_FILE, "privacy", str(exc)) from exc
    else:
        new_label = old_label

    overrides: dict[str, Any] = {}
    if privacy is not None:
        overrides["privacy"] = privacy
        overrides["share"] = None
    elif share is not None:
        overrides["share"] = list(share)
        overrides["privacy"] = None
    if content_max_chars is not None:
        overrides["contentMaxChars"] = content_max_chars

    def _update(current_doc: dict[str, Any]) -> dict[str, Any]:
        exporters = current_doc.get("exporters")
        if not isinstance(exporters, dict):
            exporters = {}
        entry = dict(exporters.get(name) or {})
        entry.update(overrides)
        entry["kind"] = "exporter"
        entry["name"] = name
        exporters[name] = entry
        current_doc["exporters"] = exporters
        return current_doc

    _store.read_modify_write(_cfg.EXPORTERS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    host = urlsplit(spec.endpoint).hostname or spec.endpoint
    _audit.audit_log(
        "exporter.privacy", f"name={spec.name} from={old_label} to={new_label} host={host}"
    )
    return spec


def resolve_credentials(spec: ExporterSpec) -> tuple[list[str], str]:
    """Resolve every name in ``spec.auth.credentials`` (env first, then the secret store).
    Returns ``(values, source)``: an unresolved name yields ``""``; *source* is
    ``"env"``/``"store"``/``"mixed"``/``"none"``."""
    if not spec.auth.credentials:
        return [], "none"

    from docket.core import secrets as _secrets

    values: list[str] = []
    sources: set[str] = set()
    for name in spec.auth.credentials:
        env_value = os.environ.get(name, "").strip()
        if env_value:
            values.append(env_value)
            sources.add("env")
            continue
        store_value = _secrets.secret_value(name) or ""
        if store_value:
            values.append(store_value)
            sources.add("store")
            continue
        values.append("")
        sources.add("none")

    resolved_sources = sources - {"none"}
    if not resolved_sources:
        return values, "none"
    if len(resolved_sources) == 1:
        return values, next(iter(resolved_sources))
    return values, "mixed"


def activation_state(
    spec: ExporterSpec, health: dict[str, Any] | None
) -> tuple[ExporterState, list[str]]:
    """Pure classification of *spec*'s activation state (ADR 0014 §4). A present credential
    never activates an exporter by itself -- ``enabled`` is checked first. *health* is the
    exporter's own record from ``read_health()``, or ``None``."""
    if not spec.enabled:
        return "disabled", []

    values, _source = resolve_credentials(spec)
    missing = [name for name, value in zip(spec.auth.credentials, values, strict=True) if not value]
    if missing:
        return "needs credential", missing

    if health:
        last_ok = str(health.get("lastOk") or "")
        last_error_at = str(health.get("lastErrorAt") or "")
        if last_error_at and (not last_ok or last_error_at > last_ok):
            return "unreachable", []

    return "enabled", []


def read_health() -> dict[str, dict[str, Any]]:
    """Every exporter's health record (``config.EXPORTERS_HEALTH_FILE``), keyed by name -- a
    read-only view, through ``edges/store.py`` like every other docket-owned JSON read."""
    raw = _store.read_json(_cfg.EXPORTERS_HEALTH_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(name): block for name, block in raw.items() if isinstance(block, dict)}


@dataclass(frozen=True)
class ProbeResult:
    """A raw, unclassified probe of an exporter's endpoint. ``status`` is ``None`` only for a
    transport failure (DNS, refused, timeout). A plain dataclass, not `edges/adapters/llm.py`'s
    provider ``ProbeResult`` -- this module imports nothing from ``edges/``."""

    status: int | None
    error: str = ""


@dataclass(frozen=True)
class ExporterVerification:
    """A classified probe of an exporter's endpoint (the same table
    ``core/provider.py::verify_endpoint`` uses): a transport failure is the only unreachable
    outcome; every HTTP status registers, with a warning naming what is not a clean 2xx."""

    reachable: bool
    status: int | None
    credential_present: bool
    credential_name: str
    warning: str


def verify_endpoint(spec: ExporterSpec, probe: ProbeResult) -> ExporterVerification:
    """Classify *probe* of *spec*'s endpoint. Pure -- no I/O; the caller does the probe."""
    values, _source = resolve_credentials(spec)
    credential_present = any(bool(v) for v in values)
    credential_name = spec.auth.credentials[0] if spec.auth.credentials else ""

    if probe.status is None:
        return ExporterVerification(
            reachable=False,
            status=None,
            credential_present=credential_present,
            credential_name=credential_name,
            warning=probe.error,
        )

    warning = ""
    if 200 <= probe.status < 300:
        pass
    elif probe.status in (401, 403):
        who = credential_name or "a credential"
        warning = (
            f"{who} was rejected (HTTP {probe.status})"
            if credential_present
            else f"{who} is missing (HTTP {probe.status})"
        )
    else:
        warning = f"endpoint returned HTTP {probe.status}"

    return ExporterVerification(
        reachable=True,
        status=probe.status,
        credential_present=credential_present,
        credential_name=credential_name,
        warning=warning,
    )


def export_exporter(name: str) -> str:
    """Render *name*'s resolved catalog entry as a ``kind: exporter`` document -- the inverse of
    ``load_exporter_document``. Never carries a credential value: this module only ever stores
    credential *names*."""
    spec = load_catalog().get(name)
    if spec is None:
        raise ExporterError(_cfg.EXPORTERS_FILE, "name", f"'{name}' is not in the exporter catalog")

    try:
        import yaml as _yaml
    except ImportError:
        raise ExporterError(
            _cfg.EXPORTERS_FILE, "file", "PyYAML not installed -- run: pip install pyyaml"
        ) from None

    payload = {
        "kind": "exporter",
        **spec.model_dump(by_alias=True, exclude_defaults=True, exclude_none=True),
    }
    return str(_yaml.safe_dump(payload, sort_keys=False))
