"""Channel catalog: the notification/conversation/decision destinations docket knows, as
`kind: channel` documents (ADR 0016 §7) -- a deliberate copy of `core/exporter.py`'s shape
with the model/price/preset fields dropped and destination-shaped ones added: `capabilities`
(bounded by each dialect's declared maximum), `on` (which event types reach it), `content`
(how much a delivery carries -- `minimal < actions < conversation`, never the export-only
`full`), `actors` (who may converse or decide through it), and `secret` (a credential name,
never a value). Two scopes, nearest-wins by name: built-in and global
(`config.CHANNELS_FILE`).

This module owns the document, the catalog, and validation; actual delivery lives elsewhere --
a channel document only declares what it is allowed to send and to whom.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

import docket.config as _cfg
from docket.core.operator_contract import EVENT_KINDS
from docket.edges import store as _store

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CREDENTIAL_VALUE_RE = re.compile(r"^[A-Za-z0-9/_\-+.]{20,}$")

# The `on:` vocabulary: every ADR 0016 §7 event type suffix, plus the `needs_you` shorthand
# that stands for every "something needs a human" transition at once.
ON_KINDS: tuple[str, ...] = (*EVENT_KINDS, "needs_you")

# Each dialect's maximum declarable capability set (ADR 0016 §7's table). `console` and
# `telegram` may decide; every other v1 dialect may only notify.
DIALECT_MAX: dict[str, frozenset[str]] = {
    "console": frozenset({"notify", "converse", "decide"}),
    "desktop": frozenset({"notify"}),
    "webhook": frozenset({"notify"}),
    "command": frozenset({"notify"}),
    "ntfy": frozenset({"notify"}),
    "email": frozenset({"notify"}),
    "telegram": frozenset({"notify", "converse", "decide"}),
}

_CONTENT_RANK: dict[str, int] = {"minimal": 0, "actions": 1, "conversation": 2}

# Dialects whose `deliver` sends nothing: the console is already the inbox, so a catalog where
# it is the only enabled channel reaches nobody who is not looking at that terminal.
SILENT_DIALECTS: frozenset[str] = frozenset({"console"})

_UNREACHED_WARNING = (
    "Only console is on, and console sends nothing.\n"
    "  A parked task waits unseen until you run docket inbox.\n"
    "  Before running unattended, enable a channel:\n"
    "    docket setup notify enable desktop                   # this machine\n"
    "    docket setup notify enable ntfy --set topic=<topic>  # your phone"
)


def unreached_warning(delivering: Sequence[str]) -> str | None:
    """The one text every surface prints when nothing delivers beyond the console (doctor,
    `serve --dispatch`, `init`, the post-dispatch flush); ``None`` once something does."""
    return None if delivering else _UNREACHED_WARNING


def _format_loc(loc: tuple[Any, ...]) -> str:
    """Render a pydantic error ``loc`` tuple as a dotted path with bracket list indices
    (``capabilities[1]``, not ``capabilities.1``) -- the one difference from
    `core/exporter.py`'s plain dot-joined refinement."""
    parts: list[str] = []
    for piece in loc:
        if isinstance(piece, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{piece}]"
            else:
                parts.append(f"[{piece}]")
        else:
            parts.append(str(piece))
    return ".".join(parts)


class ChannelError(Exception):
    """*file*: *field*: *message* (valid: ...) -- a channel document failed to load or a
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


class ChannelSpec(BaseModel):
    """A `kind: channel` document -- see operator-loop.spec.md ("Notifications"). This model
    IS the canonical, only parsed shape; there is no separate short form underneath it."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["channel"]
    name: str
    description: str = ""
    dialect: Literal["console", "desktop", "webhook", "command", "ntfy", "email", "telegram"]
    enabled: bool = False
    capabilities: list[Literal["notify", "converse", "decide"]] = Field(default_factory=list)
    on: list[str] = Field(default_factory=list)
    content: Literal["minimal", "actions", "conversation"] = "minimal"
    actors: list[str] = Field(default_factory=list)
    config: dict[str, str] = Field(default_factory=dict)
    secret: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _fix_yaml_bareword_on_key(cls, data: Any) -> Any:
        """PyYAML resolves an unquoted ``on:`` key to the boolean ``True`` (YAML 1.1's
        bareword-boolean quirk), not the string key this field is -- remap it back before
        pydantic ever sees it."""
        if isinstance(data, dict) and True in data and "on" not in data:
            data = dict(data)
            data["on"] = data.pop(True)
        return data

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(f"'{value}' is not a valid channel name (^[a-z0-9][a-z0-9-]*$)")
        return value

    @field_validator("capabilities")
    @classmethod
    def _capabilities_within_dialect_max(cls, value: list[str], info: ValidationInfo) -> list[str]:
        dialect = info.data.get("dialect")
        if dialect is None:
            return value
        allowed = DIALECT_MAX.get(dialect, frozenset())
        for idx, cap in enumerate(value):
            if cap not in allowed:
                maximum = ", ".join(sorted(allowed)) or "none"
                raise ValueError(
                    f"capabilities[{idx}]: '{cap}' exceeds the maximum for dialect "
                    f"{dialect!r} ({maximum})"
                )
        return value

    @field_validator("on")
    @classmethod
    def _valid_on(cls, value: list[str]) -> list[str]:
        for idx, entry in enumerate(value):
            if entry not in ON_KINDS:
                raise ValueError(f"on[{idx}]: '{entry}' is not a known event type or shorthand")
        return value

    @model_validator(mode="after")
    def _actors_required_when_enabled(self) -> ChannelSpec:
        """A dormant document may declare `decide`/`converse` with no `actors` yet. Once
        `enabled` is true, either requires a non-empty `actors` list, except `console` (the
        operator's own terminal, trusted without an allow-list)."""
        if not self.enabled or self.dialect == "console" or self.actors:
            return self
        for needed in ("decide", "converse"):
            if needed in self.capabilities:
                raise ValueError(
                    f"capabilities include '{needed}', which requires a non-empty 'actors' "
                    f"list when enabled (dialect {self.dialect!r})"
                )
        return self

    @field_validator("secret")
    @classmethod
    def _valid_secret_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if _CREDENTIAL_NAME_RE.match(value):
            return value
        if _CREDENTIAL_VALUE_RE.match(value):
            raise ValueError(
                f"'{value}' looks like a credential VALUE, not a name -- "
                "'secret' names a stored secret, it never carries one"
            )
        raise ValueError(f"'{value}' is not a valid credential name (^[A-Z][A-Z0-9_]*$)")


def _validation_to_channel_error(path: Path | str, exc: ValidationError) -> ChannelError:
    """Refine pydantic's first error into a ``ChannelError`` naming the field (bracketed list
    indices included) and, for a closed-vocabulary failure, the valid values -- the same
    refinement `core/exporter.py`'s `_validation_to_exporter_error` does."""
    first = exc.errors()[0]
    field_name = _format_loc(first["loc"]) if first["loc"] else ""
    valid: tuple[str, ...] = ()
    expected = (first.get("ctx") or {}).get("expected")
    if isinstance(expected, str):
        valid = tuple(
            v.strip("'\" ") for v in re.split(r"\s+or\s+|,\s*", expected) if v.strip("'\" ")
        )
    return ChannelError(path, field_name, first["msg"], valid)


def load_channel_document(path: str | Path) -> ChannelSpec:
    """Read *path* as a `kind: channel` document. Raises ``ChannelError`` naming the file,
    field and message on any failure -- bad YAML, missing ``kind``/``name``, an unknown
    ``dialect``, a capability past its dialect's maximum, or a missing ``actors`` list."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChannelError(p, "file", f"cannot read file: {exc}") from exc

    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ChannelError(p, "file", "PyYAML not installed -- run: pip install pyyaml") from None
    try:
        raw = _yaml.safe_load(text)
    except Exception as exc:
        raise ChannelError(p, "file", f"YAML parse error: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ChannelError(p, "file", f"document must be a mapping (got {type(raw).__name__})")

    kind = raw.get("kind")
    if kind != "channel":
        raise ChannelError(p, "kind", f"expected 'channel', got {kind!r}", valid=("channel",))
    if not raw.get("name"):
        raise ChannelError(p, "name", "a channel document requires 'name'")

    try:
        return ChannelSpec.model_validate(raw)
    except ValidationError as exc:
        raise _validation_to_channel_error(p, exc) from exc


@dataclass(frozen=True)
class Catalog:
    """The merged channel catalog: the operator's own (global) entries override a built-in of
    the same name, nearest-wins -- the same rule as the exporter/provider catalogs."""

    entries: dict[str, ChannelSpec]
    scopes: dict[str, str]  # name -> "built-in" | "global"

    def get(self, name: str) -> ChannelSpec | None:
        return self.entries.get(name)

    def source_of(self, name: str) -> str:
        """``"built-in"`` or ``"global"``, or ``""`` when *name* is not in the catalog."""
        return self.scopes.get(name, "")

    def delivering(self) -> list[str]:
        """Names of the enabled `notify` channels whose dialect sends somewhere, sorted."""
        return sorted(
            name
            for name, spec in self.entries.items()
            if spec.enabled
            and "notify" in spec.capabilities
            and spec.dialect not in SILENT_DIALECTS
        )


def _load_builtin_channels() -> dict[str, ChannelSpec]:
    directory = _cfg.CHANNEL_TEMPLATES_DIR
    entries: dict[str, ChannelSpec] = {}
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.yaml")):
        try:
            spec = load_channel_document(path)
        except ChannelError:
            continue
        entries[spec.name] = spec
    return entries


def _with_inherited_identity(spec: ChannelSpec) -> ChannelSpec:
    """Fill every field *spec* left unset (``model_fields_set``, so an explicit clear still
    wins) from the built-in of the same name -- a global channel override inherits every field
    it does not set, the same rule `core/exporter.py`'s `_with_inherited_identity` applies."""
    builtin = _load_builtin_channels().get(spec.name)
    if builtin is None:
        return spec
    missing = [f for f in spec.model_fields if f not in spec.model_fields_set]
    if not missing:
        return spec
    return spec.model_copy(update={f: getattr(builtin, f) for f in missing})


def _merge_with_builtin_raw(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Fill every key *raw* omits from the built-in document of the same *name*, before
    ``ChannelSpec`` ever parses it -- a partial on-disk override would otherwise fail the
    model's required ``dialect``/``kind`` fields."""
    builtin = _load_builtin_channels().get(name)
    if builtin is None:
        return raw
    merged = builtin.model_dump(by_alias=True, exclude_none=True)
    merged.update(raw)
    return merged


def _load_global_channels() -> dict[str, ChannelSpec]:
    raw = _store.read_json(_cfg.CHANNELS_FILE)
    channels = raw.get("channels") if isinstance(raw, dict) else None
    entries: dict[str, ChannelSpec] = {}
    if not isinstance(channels, dict):
        return entries
    for name, block in channels.items():
        if not isinstance(block, dict):
            continue
        merged = _merge_with_builtin_raw(str(name), block)
        merged.setdefault("name", str(name))
        try:
            entries[str(name)] = ChannelSpec.model_validate(merged)
        except ValidationError:
            continue
    return entries


def load_catalog() -> Catalog:
    """The merged channel catalog: every built-in under ``config.CHANNEL_TEMPLATES_DIR``,
    overridden by the operator's own global entries in ``config.CHANNELS_FILE``, nearest-wins
    by name."""
    entries: dict[str, ChannelSpec] = {}
    scopes: dict[str, str] = {}
    for name, spec in _load_builtin_channels().items():
        entries[name] = spec
        scopes[name] = "built-in"
    for name, spec in _load_global_channels().items():
        entries[name] = spec
        scopes[name] = "global"
    return Catalog(entries=entries, scopes=scopes)


def save_channel(spec: ChannelSpec) -> None:
    """Write *spec* into the global catalog (``config.CHANNELS_FILE``), through
    ``edges/store.py`` -- the sole writer of docket-owned JSON."""
    spec = _with_inherited_identity(spec)

    def _update(current: dict[str, Any]) -> dict[str, Any]:
        channels = current.get("channels")
        if not isinstance(channels, dict):
            channels = {}
        channels[spec.name] = spec.model_dump(by_alias=True, exclude_none=True)
        current["channels"] = channels
        return current

    _store.read_modify_write(_cfg.CHANNELS_FILE, _update)


def delete_channel(name: str) -> None:
    """Remove *name* from the global catalog. A built-in with no global override has nothing
    to remove -- ``ChannelError`` names the built-in scope rather than silently no-op'ing."""
    removed = False

    def _update(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        channels = current.get("channels")
        if not isinstance(channels, dict) or name not in channels:
            return None
        del channels[name]
        current["channels"] = channels
        removed = True
        return current

    _store.read_modify_write(_cfg.CHANNELS_FILE, _update)
    if removed:
        return

    scope = load_catalog().source_of(name)
    if scope == "built-in":
        raise ChannelError(
            _cfg.CHANNELS_FILE,
            "name",
            f"'{name}' is a built-in channel with no global override -- nothing to remove",
        )
    raise ChannelError(_cfg.CHANNELS_FILE, "name", f"'{name}' is not in the channel catalog")


def _enable_refusal(spec: ChannelSpec) -> str:
    """The empty-precondition check `enable_channel` applies before ever writing: the two
    named refusals (ADR 0016 §7's built-ins), never a network probe -- delivery is out of
    scope for this module."""
    if spec.dialect == "ntfy" and not spec.config.get("topic"):
        return "channel 'ntfy' needs a topic -- pass --set topic=<topic>"
    if spec.dialect == "telegram" and not spec.actors:
        return "channel 'telegram' needs at least one actor -- pass --set actors=<id>"
    return ""


def enable_channel(name: str, overrides: dict[str, Any] | None = None) -> ChannelSpec:
    """Turn *name* on in the global catalog: writes only ``{kind, name, enabled: true,
    <overrides>}``. Refuses a name absent from the catalog, and refuses without writing a
    resulting document that fails `_enable_refusal`."""
    current = load_catalog().get(name)
    if current is None:
        raise ChannelError(_cfg.CHANNELS_FILE, "name", f"'{name}' is not in the channel catalog")

    clean = {k: v for k, v in (overrides or {}).items() if k not in ("kind", "name", "enabled")}
    prospective = current.model_copy(update=clean) if clean else current
    refusal = _enable_refusal(prospective)
    if refusal:
        raise ChannelError(_cfg.CHANNELS_FILE, "enable", refusal)

    def _update(doc: dict[str, Any]) -> dict[str, Any]:
        channels = doc.get("channels")
        if not isinstance(channels, dict):
            channels = {}
        entry = dict(channels.get(name) or {})
        entry.update(clean)
        entry["kind"] = "channel"
        entry["name"] = name
        entry["enabled"] = True
        channels[name] = entry
        doc["channels"] = channels
        return doc

    _store.read_modify_write(_cfg.CHANNELS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    _audit.audit_log(
        "channel.enable", f"name={spec.name} dialect={spec.dialect} content={spec.content}"
    )
    return spec


def disable_channel(name: str) -> ChannelSpec:
    """Turn *name* off in the global catalog -- flips ``enabled`` to false, keeping any other
    stored overrides untouched. A stored `secret` name is never touched. Refuses a name absent
    from the catalog."""
    if load_catalog().get(name) is None:
        raise ChannelError(_cfg.CHANNELS_FILE, "name", f"'{name}' is not in the channel catalog")

    def _update(doc: dict[str, Any]) -> dict[str, Any]:
        channels = doc.get("channels")
        if not isinstance(channels, dict):
            channels = {}
        entry = dict(channels.get(name) or {})
        entry["kind"] = "channel"
        entry["name"] = name
        entry["enabled"] = False
        channels[name] = entry
        doc["channels"] = channels
        return doc

    _store.read_modify_write(_cfg.CHANNELS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    _audit.audit_log("channel.disable", f"name={spec.name} dialect={spec.dialect}")
    return spec


def is_widening(old: str, new: str) -> bool:
    """True when *new* is a richer content level than *old* on the closed order
    ``minimal < actions < conversation``. Pure; used by the CLI to decide whether a content
    change needs confirmation."""
    return _CONTENT_RANK[new] > _CONTENT_RANK[old]


def set_content(name: str, level: str) -> ChannelSpec:
    """Change *name*'s ``content`` level, writing only that key. Refuses an unknown name or an
    unknown level; audits ``channel.content`` with the old and new level, never the content
    itself."""
    current = load_catalog().get(name)
    if current is None:
        raise ChannelError(_cfg.CHANNELS_FILE, "name", f"'{name}' is not in the channel catalog")
    if level not in _CONTENT_RANK:
        raise ChannelError(
            _cfg.CHANNELS_FILE,
            "content",
            f"'{level}' is not a known content level",
            valid=tuple(_CONTENT_RANK),
        )

    old_level = current.content

    def _update(doc: dict[str, Any]) -> dict[str, Any]:
        channels = doc.get("channels")
        if not isinstance(channels, dict):
            channels = {}
        entry = dict(channels.get(name) or {})
        entry["content"] = level
        entry["kind"] = "channel"
        entry["name"] = name
        channels[name] = entry
        doc["channels"] = channels
        return doc

    _store.read_modify_write(_cfg.CHANNELS_FILE, _update)
    spec = load_catalog().get(name)
    assert spec is not None  # just written above

    from docket.core import audit as _audit

    _audit.audit_log("channel.content", f"name={spec.name} from={old_level} to={level}")
    return spec


def export_channel(name: str) -> str:
    """Render *name*'s resolved catalog entry as a ``kind: channel`` document -- the inverse
    of ``load_channel_document``. Never carries a credential value: this module only ever
    stores a credential *name* in ``secret``."""
    spec = load_catalog().get(name)
    if spec is None:
        raise ChannelError(_cfg.CHANNELS_FILE, "name", f"'{name}' is not in the channel catalog")

    try:
        import yaml as _yaml
    except ImportError:
        raise ChannelError(
            _cfg.CHANNELS_FILE, "file", "PyYAML not installed -- run: pip install pyyaml"
        ) from None

    payload = {
        "kind": "channel",
        **spec.model_dump(by_alias=True, exclude_defaults=True, exclude_none=True),
    }
    return str(_yaml.safe_dump(payload, sort_keys=False))
