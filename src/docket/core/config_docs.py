"""The configuration document envelope: one entry point, ``load_document``, that reads a role,
pipeline, policy, or pod-manifest file, resolves its ``kind:``, and dispatches to the parser
that already owns that kind (``core.archetypes.from_wire``, ``core.pipeline.load_pipeline``,
``core.policy.validate_policy``, ``core.pod_apply``'s manifest key set). See
specs/functional/config-format.spec.md."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docket.core import archetypes as _archetypes
from docket.core import channel as _channel
from docket.core import exporter as _exporter
from docket.core import mcp_tools as _mcp_tools
from docket.core import pipeline as _pipeline
from docket.core import pod_apply as _pod_apply
from docket.core import policy as _policy
from docket.core import provider as _provider

KINDS: tuple[str, ...] = (
    "role",
    "pipeline",
    "policy",
    "pod",
    "provider",
    "exporter",
    "channel",
    "mcp-server",
)

_LOCATION_KIND: dict[str, str] = {
    "roles": "role",
    "policies": "policy",
    "mcp-servers": "mcp-server",
}


# ── Short-form models ─────────────────────────────────────────────────────────
#
# These describe exactly the short forms `core.archetypes.normalize_role`,
# `core.pipeline.normalize_pipeline`, and `core.policy.normalize_policy` accept, for JSON
# Schema generation (`scripts/gen_config_schemas.py`) and to give `load_document`'s error a
# field name and valid-values list when a short-form document fails its kind's real parser.
# The normalisers remain the only loaders; nothing here ever parses a document directly.


class RoleDocument(BaseModel):
    """The short-form role document -- see role-archetypes.spec.md ("Wire format")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["role"]
    name: str
    description: str | None = None
    model: Literal["cheap", "strong"] | None = None
    cannot: list[str] | None = None
    verdict: list[str] | None = None
    verify: bool | None = None
    approval: bool | None = None
    instructions: str | None = None
    scope: str | None = None
    version: int | None = None
    tokenBudget: int | None = None
    toolProfile: str | None = None
    hopInstruction: str | None = None


class PipelineDocument(BaseModel):
    """The short-form pipeline document -- see pipeline-format.spec.md ("Short form"). Each
    `steps` entry's own sugar keys are validated by `core.pipeline.normalize_pipeline`, not
    here."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pipeline"]
    name: str
    description: str | None = None
    variables: dict[str, Any] | None = None
    steps: list[dict[str, Any]]


class PolicyWhen(BaseModel):
    """A policy's structured predicate -- see security-gates.spec.md ("Policy format v1").
    `plugin`/`with` describe the predicate-plugin escape hatch (ADR 0010 §4); the runtime
    engine's own support for them is a separate, later card."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool: str | None = None
    path: str | None = None
    matches: str | None = None
    branch: str | None = None
    anyOf: list[PolicyWhen] | None = None
    plugin: str | None = None
    with_: dict[str, Any] | None = Field(None, alias="with")


PolicyWhen.model_rebuild()


class PolicyDocument(BaseModel):
    """The short-form policy document -- see security-gates.spec.md ("Policy format v1")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["policy"]
    name: str
    description: str | None = None
    appliesTo: list[str] | str | None = None
    on: Literal["input", "toolCall", "output"] | None = None
    when: PolicyWhen | None = None
    then: Literal["allow", "warn", "ask", "block", "redact"]
    message: str | None = None


class PodDocument(BaseModel):
    """The short-form pod manifest -- see pod-blueprints.spec.md ("Pod manifests: apply")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pod"]
    name: str
    description: str | None = None
    members: list[str] | None = None
    settings: dict[str, Any] | None = None
    pipeline: str | None = None
    exporters: list[str] | None = None


_MODEL_FOR_KIND: dict[str, type[BaseModel]] = {
    "role": RoleDocument,
    "pipeline": PipelineDocument,
    "policy": PolicyDocument,
    "pod": PodDocument,
    "exporter": _exporter.ExporterSpec,
    "channel": _channel.ChannelSpec,
    "mcp-server": _mcp_tools.McpServerDocument,
}


_ROLE_SHORT_KEYS: tuple[str, ...] = (
    "cannot",
    "verdict",
    "verify",
    "approval",
    "instructions",
    "model",
)
_POLICY_SHORT_KEYS: tuple[str, ...] = ("appliesTo", "on", "when", "then")


def _is_short_form(kind: str, doc: dict[str, Any]) -> bool:
    """Whether *doc* is unambiguously short form -- a canonical document sharing the same
    envelope must never hit the short-form model's ``extra="forbid"``, which would reject
    every canonical-only field it does not know instead of surfacing the real error."""
    if kind == "role":
        return any(k in doc for k in _ROLE_SHORT_KEYS)
    if kind == "pipeline":
        return "kind" in doc
    if kind == "policy":
        return any(k in doc for k in _POLICY_SHORT_KEYS)
    return kind == "pod"


def _refine_with_model(
    path: Path, kind: str, doc: dict[str, Any], fallback: Exception
) -> ConfigDocError:
    """When *doc* is short form and also fails its kind's model, prefer the model's field name
    and valid values over *fallback*'s plain message; otherwise fall back to it unchanged."""
    model = _MODEL_FOR_KIND.get(kind)
    if model is None or not _is_short_form(kind, doc):
        return ConfigDocError(path, str(fallback))
    try:
        model.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) if first["loc"] else ""
        valid: tuple[str, ...] = ()
        expected = (first.get("ctx") or {}).get("expected")
        if isinstance(expected, str):
            valid = tuple(
                v.strip("'\" ") for v in re.split(r"\s+or\s+|,\s*", expected) if v.strip("'\" ")
            )
        return ConfigDocError(path, first["msg"], field=field, valid=valid)
    return ConfigDocError(path, str(fallback))


@dataclass(frozen=True)
class Document:
    """One loaded, dispatch-validated configuration file."""

    kind: str
    name: str
    path: Path
    doc: dict[str, Any]
    deprecated: bool


class ConfigDocError(ValueError):
    """*path* (at *line*, in *field*) failed to load or validate. ``valid``/``suggestion`` are
    only populated for a closed-vocabulary failure (an unknown ``kind``)."""

    def __init__(
        self,
        path: Path | str,
        message: str,
        *,
        line: int = 0,
        field: str = "",
        valid: tuple[str, ...] = (),
        suggestion: str = "",
    ) -> None:
        self.path = Path(path)
        self.line = line
        self.field = field
        self.message = message
        self.valid = tuple(valid)
        self.suggestion = suggestion
        super().__init__(str(self))

    def __str__(self) -> str:
        head = f"{self.path}:{self.line}"
        if self.field:
            head = f"{head} {self.field}:"
        rendered = f"{head} {self.message}"
        if self.valid:
            rendered = f"{rendered} (valid: {', '.join(self.valid)}"
            if self.suggestion:
                rendered = f'{rendered}; did you mean "{self.suggestion}"?'
            rendered = f"{rendered})"
        return rendered


def _line_for_key(text: str, key: str) -> int:
    """The 1-indexed source line of a top-level mapping *key*, or ``0`` when it cannot be
    found (PyYAML missing, the document composes to something other than a mapping, or no
    top-level key matches)."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        return 0
    try:
        node = _yaml.compose(text)
    except Exception:
        return 0
    pairs = getattr(node, "value", None)
    if not isinstance(pairs, list):
        return 0
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            continue
        key_node, _value_node = pair
        if getattr(key_node, "value", None) == key:
            mark = getattr(key_node, "start_mark", None)
            return int(mark.line) + 1 if mark is not None else 0
    return 0


def _suggest(value: str) -> str:
    matches = difflib.get_close_matches(value, KINDS, n=1)
    return matches[0] if matches else ""


def _infer_kind_from_location(path: Path) -> str | None:
    parent = _LOCATION_KIND.get(path.parent.name)
    if parent is not None:
        return parent
    if path.stem == "pipeline":
        return "pipeline"
    if path.stem == "pod":
        return "pod"
    return None


def _load_role(path: Path) -> dict[str, Any]:
    """The canonical wire dict for a role file: the short form is normalised first
    (``core.archetypes.load_role_file``), then validated exactly as ``roles add`` does."""
    try:
        doc = _archetypes.load_role_file(str(path))
        _archetypes.from_wire(str(doc.get("name", "")), doc)
    except _archetypes.ArchetypeError as exc:
        raise ConfigDocError(path, str(exc)) from exc
    return doc


def _validate_pipeline(path: Path, text: str) -> None:
    result = _pipeline.load_pipeline(text)
    if not result.ok:
        raise ConfigDocError(path, "; ".join(result.errors))


def _validate_policy(path: Path) -> None:
    error = _policy.validate_policy(path)
    if error:
        raise ConfigDocError(path, error)


def _validate_pod(path: Path, doc: dict[str, Any]) -> None:
    unknown = set(doc) - _pod_apply._MANIFEST_KEYS
    if unknown:
        raise ConfigDocError(path, f"unknown key(s): {', '.join(sorted(unknown))}")


def _validate_provider(path: Path) -> None:
    try:
        _provider.load_provider_document(path)
    except _provider.ProviderError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _validate_exporter(path: Path) -> None:
    try:
        _exporter.load_exporter_document(path)
    except _exporter.ExporterError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _validate_channel(path: Path) -> None:
    try:
        _channel.load_channel_document(path)
    except _channel.ChannelError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _validate_mcp_server(path: Path) -> None:
    try:
        _mcp_tools.load_mcp_server_document(path)
    except _mcp_tools.McpServerDocError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def load_document(path: str | Path, *, kind: str | None = None) -> Document:
    """Read *path*, resolve its kind, and dispatch to the parser that owns it. *kind* is used
    only when the document has no top-level ``kind:`` key and its location does not resolve
    one -- see the "Files without kind:" requirement in config-format.spec.md."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigDocError(p, f"cannot read file: {exc}") from exc

    try:
        import yaml as _yaml
    except ImportError:
        raise ConfigDocError(p, "PyYAML not installed -- run: pip install pyyaml") from None
    try:
        raw = _yaml.safe_load(text)
    except Exception as exc:
        raise ConfigDocError(p, f"YAML parse error: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigDocError(p, f"document must be a mapping (got {type(raw).__name__})")
    doc: dict[str, Any] = raw

    declared = doc.get("kind")
    deprecated = False
    if declared is None:
        resolved = _infer_kind_from_location(p) or kind
        if resolved is None:
            raise ConfigDocError(
                p,
                "no 'kind:' key, and its location does not indicate one",
                field="kind",
                valid=KINDS,
            )
        effective_kind = resolved
        deprecated = True
    else:
        if declared not in KINDS:
            raise ConfigDocError(
                p,
                f"unknown kind {declared!r}",
                field="kind",
                line=_line_for_key(text, "kind"),
                valid=KINDS,
                suggestion=_suggest(str(declared)),
            )
        effective_kind = declared

    try:
        if effective_kind == "role":
            doc = _load_role(p)
        elif effective_kind == "pipeline":
            _validate_pipeline(p, text)
        elif effective_kind == "policy":
            _validate_policy(p)
        elif effective_kind == "pod":
            _validate_pod(p, doc)
        elif effective_kind == "provider":
            _validate_provider(p)
        elif effective_kind == "exporter":
            _validate_exporter(p)
        elif effective_kind == "channel":
            _validate_channel(p)
        elif effective_kind == "mcp-server":
            _validate_mcp_server(p)
    except ConfigDocError as exc:
        raise _refine_with_model(p, effective_kind, doc, exc) from exc

    name = str(doc.get("name", p.stem))
    return Document(kind=effective_kind, name=name, path=p, doc=doc, deprecated=deprecated)


def discover_config_paths(directory: str | Path) -> list[Path]:
    """Every ``roles/*``, ``policies/*``, ``mcp-servers/*`` (``.yaml|yml|json``), ``pipeline.yaml``/
    ``.yml``, and ``pod.yaml``/``.yml`` directly under *directory*, in that order."""
    base = Path(directory)
    paths: list[Path] = []
    for sub in ("roles", "policies", "mcp-servers"):
        sub_dir = base / sub
        if not sub_dir.is_dir():
            continue
        for pattern in ("*.yaml", "*.yml", "*.json"):
            paths.extend(sorted(sub_dir.glob(pattern)))
    for stem in ("pipeline", "pod"):
        for ext in ("yaml", "yml"):
            candidate = base / f"{stem}.{ext}"
            if candidate.is_file():
                paths.append(candidate)
                break
    return paths


def validate_directory(directory: str | Path) -> list[ConfigDocError]:
    """Every ``ConfigDocError`` raised while loading each document ``discover_config_paths``
    finds under *directory*, in discovery order."""
    errors: list[ConfigDocError] = []
    for path in discover_config_paths(directory):
        try:
            load_document(path)
        except ConfigDocError as exc:
            errors.append(exc)
    return errors
