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
