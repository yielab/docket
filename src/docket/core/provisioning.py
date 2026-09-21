"""Provisioning UX helpers for ``docket add``.

Small, pure helpers the interactive/declarative add flow uses to pick sensible
defaults: the codebase path, the suggested project name, the id slug, and the
detected stack. The *memory/runtime-contract* side of provisioning (seeding
``WORKFLOW_AUTO.md`` / ``MEMORY.md`` / daily logs) lives in ``core/memory.py``;
the workspace builders in ``cli/_pod.py`` and ``cli/_agents.py`` call that
directly.
"""

from __future__ import annotations

import re as _re
from pathlib import Path


def slugify(name: str) -> str:
    """Lowercase, hyphenated agent-id slug (shared by every add path)."""
    return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class ProjectIdError(ValueError):
    """A project/pod id failed ``validate_project_id``. ``core/`` raises, never prints --
    see specs/validation/input-validation.spec.md §1."""


#: Exactly the set `slugify` can ever emit: lowercase alphanumeric segments
#: joined by single hyphens, no leading/trailing/consecutive hyphen.
_PROJECT_ID_RE = _re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROJECT_ID_MAX_LEN = 64


def validate_project_id(project: str) -> str:
    """Validate a project/pod id: non-empty, at most 64 characters, matching
    ``^[a-z0-9]+(?:-[a-z0-9]+)*$`` (exactly what ``slugify`` can produce). Raises
    ``ProjectIdError`` naming the rule, or returns *project* unchanged."""
    if not project or len(project) > _PROJECT_ID_MAX_LEN or not _PROJECT_ID_RE.match(project):
        raise ProjectIdError(
            "project id must be non-empty, at most 64 characters, and match "
            f"^[a-z0-9]+(?:-[a-z0-9]+)*$ (got: {project[:40]!r})"
        )
    return project


def default_codebase() -> Path:
    """The codebase path to offer by default: the directory ``docket add`` ran in.

    Agents are almost always provisioned from inside the repo they will own, so
    the current working directory is the right first guess.
    """
    return Path.cwd()


def suggest_project_name(codebase: Path | str) -> str:
    """Project display name suggested from the codebase directory name.

    ``/home/ox/Sites/ai-site-generator`` -> ``ai-site-generator``.
    """
    return Path(codebase).expanduser().resolve().name or "project"


#: (marker file, stack label) pairs, checked in order.
_STACK_MARKERS: tuple[tuple[str, str], ...] = (
    ("package.json", "Node.js"),
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("composer.json", "PHP"),
    ("go.mod", "Go"),
    ("Cargo.toml", "Rust"),
)


def detect_stack(codebase: Path | str) -> str:
    """Best-effort stack detection from marker files in the codebase root."""
    root = Path(codebase).expanduser()
    if root.is_dir():
        for marker, label in _STACK_MARKERS:
            if (root / marker).is_file():
                return label
    return ""
