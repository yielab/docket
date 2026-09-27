"""Agent Skills (``skills/<name>/SKILL.md``), the standard's own progressive disclosure.

A skill is a directory: ``SKILL.md`` frontmatter names it and describes it in one sentence,
an optional body and optional ``scripts/``/``references/``/``assets/`` are read on demand. Three
scopes, nearest wins by name (ADR 0013 §3 rule 8): a codebase's own ``.docket/skills/``, this
pod's own ``config/skills/`` (a recipe's ``skills/`` applied there, exported back), and the
operator's ``~/.docket/skills/`` (``config.SKILLS_DIR``). ``core/identity.py`` composes the
discovered index into the system prompt; the ``skill`` built-in tool
(``core/tools.py``) reads a named skill's body on demand, through the same chokepoint as every
other tool. This module never imports ``edges/`` -- discovery and parsing are pure reads over
the filesystem, no policy, no dispatch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docket.config as _cfg
from docket.core.audit import audit_log

SkillScope = Literal["codebase", "pod", "global", ""]

_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_MAX_DESCRIPTION_LENGTH = 1024


class SkillError(ValueError):
    """*path*'s ``SKILL.md`` violates the Agent Skills shape; ``field`` names the offending
    key. Raised only by ``parse_skill_file``; ``discover_skills`` catches it, skips the
    skill, and audits once -- never raised into a turn."""

    def __init__(self, path: Path, field: str, message: str) -> None:
        self.path = path
        self.field = field
        self.message = message
        super().__init__(f"{path}: {field}: {message}")


@dataclass(frozen=True)
class SkillMeta:
    """One discovered skill: its frontmatter and where its files live. ``scope`` is set by
    ``discover_skills`` (empty when a ``SkillMeta`` is built directly by ``parse_skill_file``
    with no scope given, e.g. in a unit test)."""

    name: str
    description: str
    directory: Path
    scope: SkillScope = ""


def _extract_frontmatter(text: str) -> str | None:
    """The YAML between the first two ``---`` lines, or ``None`` when *text* does not open
    with one."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index])
    return None


def parse_skill_file(path: Path, *, scope: SkillScope = "") -> SkillMeta:
    """Parse *path* (``SKILL.md``) frontmatter into a ``SkillMeta``: ``name`` required, 1-64
    chars of ``[a-z0-9-]``, matching the directory; ``description`` required, <=1024 chars.
    Other keys are accepted and ignored. Raises ``SkillError`` naming *path* and the field."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillError(path, "file", f"cannot read: {exc}") from exc

    frontmatter = _extract_frontmatter(text)
    if frontmatter is None:
        raise SkillError(path, "frontmatter", "missing opening/closing '---' block")

    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SkillError(path, "frontmatter", "PyYAML not installed") from exc
    try:
        doc = _yaml.safe_load(frontmatter)
    except Exception as exc:  # PyYAML's own error hierarchy varies by version
        raise SkillError(path, "frontmatter", f"invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise SkillError(path, "frontmatter", "must be a YAML mapping")

    name = doc.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SkillError(path, "name", "required, 1-64 chars of [a-z0-9-]")
    if name != path.parent.name:
        raise SkillError(path, "name", f"must equal its directory name {path.parent.name!r}")

    description = doc.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > _MAX_DESCRIPTION_LENGTH
    ):
        raise SkillError(path, "description", "required, 1-1024 chars")

    return SkillMeta(name=name, description=description, directory=path.parent, scope=scope)


def discover_skills(project: str, codebase_root: Path | str | None) -> dict[str, SkillMeta]:
    """Every skill visible to *project* at *codebase_root*, nearest scope wins by name:
    codebase ``.docket/skills/``, this pod's ``config/skills/``, then ``config.SKILLS_DIR``.
    An invalid or bodiless skill is skipped (audited once as ``skills.invalid``), never raised."""
    found: dict[str, SkillMeta] = {}
    scopes: list[tuple[Path, SkillScope]] = []
    if codebase_root is not None:
        scopes.append((Path(codebase_root) / ".docket" / "skills", "codebase"))
    if project:
        scopes.append((_cfg.pod_config_dir(project) / "skills", "pod"))
    scopes.append((_cfg.SKILLS_DIR, "global"))

    for directory, scope in scopes:
        if not directory.is_dir():
            continue
        for skill_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
            if skill_dir.name in found:
                continue  # a nearer scope already claimed this name
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                meta = parse_skill_file(skill_file, scope=scope)
            except SkillError as exc:
                audit_log("skills.invalid", str(exc))
                continue
            found[meta.name] = meta
    return found
