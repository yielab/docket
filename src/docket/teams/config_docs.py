"""The configuration document envelope: one entry point, ``load_document``, that reads a role,
pipeline, policy, or pod-manifest file, resolves its ``kind:``, and dispatches to the parser
that already owns that kind (``teams.roles.from_wire``, ``pipeline.domain.spec.load_pipeline``,
``governance.policy.validate_policy``, ``teams.apply.plan``'s manifest key set). See
specs/functional/config-format.spec.md."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docket.governance import policy as _policy
from docket.kernel.errors import CanonicalFormRefused, DocumentError, InvalidInput
from docket.models import catalog as _provider
from docket.observability import exporter as _exporter
from docket.pipeline.domain import spec as _pipeline
from docket.teams import autonomy as _autonomy
from docket.teams import config_docs as _config_docs
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import model_selection as _models_policy
from docket.teams import prompts as _prompts
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _archetypes
from docket.teams.ports import channel_documents as _channel_documents

KINDS: tuple[str, ...] = (
    "role",
    "pipeline",
    "policy",
    "pod",
    "provider",
    "exporter",
    "channel",
    "mcp-server",
    "autonomy",
    "prompt",
)

_LOCATION_KIND: dict[str, str] = {
    "roles": "role",
    "policies": "policy",
    "mcp-servers": "mcp-server",
    "pipelines": "pipeline",
}


# ── Short-form models ─────────────────────────────────────────────────────────
#
# These describe exactly the short forms `teams.roles.normalize_role`,
# `pipeline.domain.spec.normalize_pipeline`, and `governance.policy.normalize_policy` accept, for JSON
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
    floor: list[str] | None = None
    tools: list[str] | None = None
    maxToolCalls: int | None = None


class PipelineDocument(BaseModel):
    """The short-form pipeline document -- see pipeline-format.spec.md ("Short form"). Each
    `steps` entry's own sugar keys are validated by `pipeline.domain.spec.normalize_pipeline`, not
    here."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pipeline"]
    name: str
    description: str | None = None
    variables: dict[str, Any] | None = None
    steps: list[dict[Any, Any]]  # a bare YAML `on:` key loads as True


class PolicyCommand(BaseModel):
    """A policy's ``when.command`` predicate -- see security-gates.spec.md ("Policy format v1")."""

    model_config = ConfigDict(extra="forbid")

    program: list[str] | str | None = None
    verb: list[str] | str | None = None
    args: list[str] | str | None = None
    writes: list[str] | str | None = None


class PolicyWhen(BaseModel):
    """A policy's structured predicate -- see security-gates.spec.md ("Policy format v1").
    `plugin`/`with` describe the predicate-plugin escape hatch (ADR 0010 §4); the runtime
    engine's own support for them is a separate, later card."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool: str | None = None
    path: str | None = None
    matches: str | None = None
    branch: str | None = None
    command: PolicyCommand | None = None
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
    prepare: str | None = None
    protects: list[str] | None = None


_MODEL_FOR_KIND: dict[str, type[BaseModel]] = {
    "role": RoleDocument,
    "pipeline": PipelineDocument,
    "policy": PolicyDocument,
    "pod": PodDocument,
    "exporter": _exporter.ExporterSpec,
    "mcp-server": _mcp_servers.McpServerDocument,
    "prompt": _prompts.PromptDocument,
}


# The kinds whose failure is refined by their short-form model; `exporter` and `mcp-server` keep
# the plain message of their own parser (their models exist for schema generation only).
_REFINED_KINDS: frozenset[str] = frozenset({"role", "pipeline", "policy", "pod"})


def _refine_with_model(
    path: Path, kind: str, doc: dict[str, Any], fallback: Exception
) -> ConfigDocError:
    """When *doc* also fails its kind's model, prefer the model's field name and valid values
    over *fallback*'s plain message; otherwise fall back to it unchanged."""
    if isinstance(fallback, CanonicalFormRefused):
        return (
            ConfigDocError(path, str(fallback))
            if not isinstance(fallback, ConfigDocError)
            else fallback
        )
    if isinstance(fallback, ConfigDocError):
        plain = fallback  # already names the path; wrapping it again would print it twice
    else:
        plain = ConfigDocError(path, str(fallback))
    model = _MODEL_FOR_KIND.get(kind) if kind in _REFINED_KINDS else None
    if model is None:
        return plain
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
    return plain


@dataclass(frozen=True)
class Document:
    """One loaded, dispatch-validated configuration file."""

    kind: str
    name: str
    path: Path
    doc: dict[str, Any]


class ConfigDocError(InvalidInput):
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
        self.valid = tuple(valid)
        self.suggestion = suggestion
        super().__init__(message)
        Exception.__init__(self, str(self))

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


class CanonicalFormError(ConfigDocError, CanonicalFormRefused):
    """*path* is written in the canonical shape of its kind instead of the one short form."""


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
    (``teams.roles.load_role_file``), then validated exactly as ``pod update`` does, and
    both prose templates are rendered once against sample variables so a ``${typo}`` is
    refused here and not at provisioning."""
    try:
        doc = _archetypes.load_role_file(str(path))
    except _role_schema.ArchetypeError as exc:
        raise ConfigDocError(path, str(exc)) from exc
    errors = _archetypes.validate_archetype_dict(str(doc.get("name", "")), doc)
    if errors:
        raise ConfigDocError(path, "; ".join(errors))
    return doc


def _validate_pipeline(path: Path, text: str) -> None:
    result = _pipeline.load_pipeline(text)
    if not result.ok:
        error = CanonicalFormError if result.canonical else ConfigDocError
        raise error(path, "; ".join(result.errors))


def _validate_policy(path: Path) -> None:
    error = _policy.validate_policy(path)
    if error:
        raise ConfigDocError(path, error)


def _validate_pod(path: Path, doc: dict[str, Any]) -> None:
    unknown = set(doc) - _config_docs._MANIFEST_KEYS
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
        _channel_documents.load_channel_document(path)
    except DocumentError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _validate_autonomy(path: Path) -> None:
    try:
        _autonomy.load_autonomy_document(path)
    except _autonomy.AutonomyError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _validate_mcp_server(path: Path) -> None:
    try:
        _mcp_servers.load_mcp_server_document(path)
    except _mcp_servers.McpServerDocError as exc:
        raise ConfigDocError(path, str(exc)) from exc


def _load_prompt_document(path: Path) -> Document:
    """A ``.md`` file is a ``prompt``: parsed by ``teams.prompts``, never as YAML."""
    try:
        prompt = _prompts.load_prompt_file(path)
    except _prompts.PromptError as exc:
        raise ConfigDocError(path, exc.message, line=exc.line, field=exc.field) from exc
    return Document(kind="prompt", name=prompt.name, path=path, doc=prompt.front_matter)


def load_document(path: str | Path, *, kind: str | None = None) -> Document:
    """Read *path*, resolve its kind, and dispatch to the parser that owns it. *kind* is used
    only when the document has no top-level ``kind:`` key and its location does not resolve
    one -- see the "Files without kind:" requirement in config-format.spec.md."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigDocError(p, f"cannot read file: {exc}") from exc

    if p.suffix == ".md":
        return _load_prompt_document(p)

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

    if effective_kind == "prompt":
        raise ConfigDocError(
            p,
            "a prompt is a Markdown file: front matter, then the text",
            field="kind",
            line=_line_for_key(text, "kind"),
        )

    if effective_kind == "role":
        refusal = _archetypes.canonical_key_refusal(doc)
    elif effective_kind == "policy":
        refusal = _policy.canonical_key_refusal(doc)
    else:
        refusal = ""
    if refusal:
        raise CanonicalFormError(p, refusal)

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
        elif effective_kind == "autonomy":
            _validate_autonomy(p)
    except ConfigDocError as exc:
        raise _refine_with_model(p, effective_kind, {"kind": effective_kind, **doc}, exc) from exc

    name = str(doc.get("name", p.stem))
    return Document(kind=effective_kind, name=name, path=p, doc=doc)


def prompt_files(directory: str | Path) -> list[Path]:
    """Every ``prompts/*.md`` and ``prompts/<layer>/*.md`` directly under *directory*."""
    prompts_dir = Path(directory) / "prompts"
    return [*sorted(prompts_dir.glob("*.md")), *sorted(prompts_dir.glob("*/*.md"))]


def discover_config_paths(directory: str | Path) -> list[Path]:
    """Every ``roles/*``, ``policies/*``, ``mcp-servers/*`` (``.yaml|yml|json``), ``pipelines/*``
    (``.yaml|yml``), ``prompts/*.md`` and ``prompts/<layer>/*.md``, ``pipeline.yaml``/``.yml``, and
    ``pod.yaml``/``.yml`` directly under *directory*, in that order."""
    base = Path(directory)
    paths: list[Path] = []
    for sub in ("roles", "policies", "mcp-servers", "pipelines"):
        sub_dir = base / sub
        if not sub_dir.is_dir():
            continue
        patterns = ("*.yaml", "*.yml") if sub == "pipelines" else ("*.yaml", "*.yml", "*.json")
        for pattern in patterns:
            paths.extend(sorted(sub_dir.glob(pattern)))
    paths.extend(prompt_files(base))
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


@dataclass(frozen=True)
class PathResult:
    """One file's outcome from :func:`validate_path`: its document, or the error that refused it."""

    path: Path
    document: Document | None
    error: ConfigDocError | None


def _step_model_error(document: Document) -> ConfigDocError | None:
    """A pipeline step whose own ``model`` names a provider absent from the catalog."""
    spec = _pipeline.load_pipeline(document.path.read_text(encoding="utf-8")).spec
    if spec is None:
        return None
    for step in spec.steps:
        for unit in step.parallel or [step]:
            if not unit.model:
                continue
            try:
                _models_policy.resolve_step_model(unit.model)
            except ValueError as exc:
                return ConfigDocError(document.path, f"step {unit.id!r}: {exc}")
    return None


def _validate_one(path: Path, kind: str | None) -> PathResult:
    try:
        document = load_document(path, kind=kind)
    except ConfigDocError as exc:
        return PathResult(path, None, exc)
    if document.kind == "pipeline":
        error = _step_model_error(document)
        if error is not None:
            return PathResult(path, None, error)
    return PathResult(path, document, None)


def validate_path(target: str | Path, *, kind: str | None = None) -> list[PathResult]:
    """Validate one ``kind:`` document, or every document ``discover_config_paths`` finds under
    a directory, with the validator each kind owns. *kind* is the fallback for a document with
    no ``kind:`` key and no location that names one. Invalid files come first."""
    base = Path(target)
    paths = [base] if base.is_file() else discover_config_paths(base)
    results = [_validate_one(path, kind) for path in paths]
    results.sort(key=lambda r: r.error is None)
    return results


_MANIFEST_KEYS = frozenset(
    {
        "members",
        "settings",
        "pipeline",
        "kind",
        "name",
        "description",
        "exporters",
        "prepare",
        "protects",
    }
)
