"""The configuration document envelope: one entry point, ``load_document``, that reads a role,
pipeline, policy, or pod-manifest file, resolves its ``kind:``, and dispatches to the parser
that already owns that kind (``core.archetypes.from_wire``, ``core.pipeline.load_pipeline``,
``core.policy.validate_policy``, ``core.pod_apply``'s manifest key set). See
specs/functional/config-format.spec.md."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.core import archetypes as _archetypes
from docket.core import pipeline as _pipeline
from docket.core import pod_apply as _pod_apply
from docket.core import policy as _policy

KINDS: tuple[str, ...] = ("role", "pipeline", "policy", "pod")

_LOCATION_KIND: dict[str, str] = {"roles": "role", "policies": "policy"}


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

    if effective_kind == "role":
        doc = _load_role(p)
    elif effective_kind == "pipeline":
        _validate_pipeline(p, text)
    elif effective_kind == "policy":
        _validate_policy(p)
    elif effective_kind == "pod":
        _validate_pod(p, doc)

    name = str(doc.get("name", p.stem))
    return Document(kind=effective_kind, name=name, path=p, doc=doc, deprecated=deprecated)


def discover_config_paths(directory: str | Path) -> list[Path]:
    """Every ``roles/*.yaml|yml|json``, ``policies/*.yaml|yml|json``, ``pipeline.yaml``/
    ``.yml``, and ``pod.yaml``/``.yml`` directly under *directory*, in that order."""
    base = Path(directory)
    paths: list[Path] = []
    for sub in ("roles", "policies"):
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
