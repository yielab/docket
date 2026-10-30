"""``applied.lock``: what the last ``docket pod update <directory>`` applied, by hash.

One item per file the directory brought (role, prompt, policy, plugin, skill, pipeline, MCP
server, the manifest), each ``{kind, name, version, scope, path, applied, sha256}``: ``path`` is
the source file, ``applied`` its copy in the pod overlay (empty for an item with none), and
``sha256`` the digest of its bytes. The pod's ``configDigest`` is the sha256 of the lock file's
bytes, so drift is read from one source: the lock computed again from the still-present
directory, and each applied overlay file against its item. See config-format.spec.md, "Scopes,
references and the lockfile".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import docket.kernel.templates as _templates
from docket.kernel.home import current_home
from docket.platform import mkdir_private, read_json, write_json
from docket.teams import config_docs as _config_docs
from docket.teams import prompts as _prompts
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _roles
from docket.teams.apply.recipes import _directory_files, _skill_digest

LOCK_NAME = "applied.lock"
LEGACY_ROLES_FILE = "roles.json"

SCOPE_REPOSITORY = "repository"
SCOPE_SHIPPED = "shipped"
SCOPE_OPERATOR = "operator"


@dataclass(frozen=True)
class LockItem:
    kind: str
    name: str
    version: str
    scope: str
    path: str
    applied: str
    sha256: str


def lock_path(project: str) -> Path:
    return current_home().pod_config_dir(project) / LOCK_NAME


def scope_of(directory: Path) -> str:
    """Where *directory* came from: ``repository`` for a ``.docket`` directory, ``shipped`` for a
    shipped recipe, else ``operator`` (a directory or recipe the operator named)."""
    resolved = directory.resolve()
    if ".docket" in resolved.parts:
        return SCOPE_REPOSITORY
    if resolved.is_relative_to(_templates.RECIPES_DIR.resolve()):
        return SCOPE_SHIPPED
    return SCOPE_OPERATOR


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tolerant(read: Callable[[], Any], default: Any) -> Any:
    try:
        return read()
    except Exception:  # a file plan_apply refuses is still a file the lock names
        return default


def _file_item(scope: str, kind: str, directory: Path, path: Path, version: str = "") -> LockItem:
    """One item for the file *path*, its overlay copy at the same place under *directory*."""
    return LockItem(
        kind,
        path.stem,
        version,
        scope,
        str(path),
        path.relative_to(directory).as_posix(),
        _tolerant(lambda: _sha(path.read_bytes()), ""),
    )


def _role_item(scope: str, path: Path) -> LockItem:
    doc = _tolerant(lambda: _roles.parse_yaml_file(str(path)), {})
    files: dict[str, bytes] = _tolerant(lambda: _roles.role_overlay_files(path), {})
    applied = next(iter(files), "")
    return LockItem(
        "role",
        str(doc.get("name") or path.stem),
        str(doc.get("version", 1)),
        scope,
        str(path),
        f"roles/{applied}" if applied else "",
        _sha(b"".join(files.values())) if files else "",
    )


def _prompt_version(path: Path) -> str:
    return str(_tolerant(lambda: _prompts.load_prompt_file(path).version, ""))


def _prompt_tests_of(path: Path, directory: Path) -> Path | None:
    try:
        return _config_docs.prompt_tests_file(path, directory)
    except _prompts.PromptError:  # plan_apply refuses it; the lock still names the prompt
        return None


def _glob(directory: Path, *patterns: str) -> list[Path]:
    return sorted(p for pattern in patterns for p in directory.glob(pattern))


def source_items(directory: Path) -> tuple[LockItem, ...]:
    """The lock *directory* would write, sorted by kind then name: a pure read of the files
    ``plan_apply`` reads. A file that does not validate is still named."""
    directory = directory.resolve()
    scope = scope_of(directory)
    items: list[LockItem] = [_role_item(scope, p) for p in _roles.role_files(directory / "roles")]
    for path in _config_docs.prompt_files(directory):
        items.append(_file_item(scope, "prompt", directory, path, _prompt_version(path)))
        tests = _prompt_tests_of(path, directory)
        if tests is not None and not any(i.path == str(tests) for i in items):
            items.append(_file_item(scope, "prompt-tests", directory, tests))
    for kind, sub, patterns in (
        ("policy", "policies", ("*.yaml", "*.yml", "*.json")),
        ("plugin", "plugins", ("*.py",)),
        ("pipeline", "pipelines", ("*.yaml", "*.yml")),
        ("routine", "routines", ("*.yaml", "*.yml")),
    ):
        items.extend(
            _file_item(scope, kind, directory, p) for p in _glob(directory / sub, *patterns)
        )
    for path in _glob(directory / "mcp-servers", "*.yaml", "*.yml", "*.json"):
        item = _file_item(scope, "mcp-server", directory, path)
        items.append(replace(item, applied=""))  # a server is stored in mcp-servers.json
    for stem, kind in (("pipeline", "pipeline"), ("pod", "pod")):
        top = next(
            (p for p in (directory / f"{stem}.yaml", directory / f"{stem}.yml") if p.is_file()),
            None,
        )
        if top is not None:
            items.append(
                replace(_file_item(scope, kind, directory, top), name=top.name, applied="")
            )
    skills = directory / "skills"
    for skill in sorted(p for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []:
        if (skill / "SKILL.md").is_file():
            sha = _skill_digest(_directory_files(skill)).hex()
            items.append(
                LockItem("skill", skill.name, "", scope, str(skill), f"skills/{skill.name}", sha)
            )
    return tuple(sorted(items, key=lambda i: (i.kind, i.name, i.path)))


def render(items: tuple[LockItem, ...]) -> str:
    """The lock file's exact text: ``write_json``'s serialisation of ``{"items": [...]}``."""
    return json.dumps({"items": [asdict(item) for item in items]}, indent=2) + "\n"


def digest_of(items: tuple[LockItem, ...]) -> str:
    return _sha(render(items).encode("utf-8"))


def source_digest(directory: Path) -> str:
    """The ``configDigest`` applying *directory* records."""
    return digest_of(source_items(directory))


def write_lock(project: str, items: tuple[LockItem, ...]) -> str:
    """Write *project*'s lock through the store and return its digest."""
    path = lock_path(project)
    mkdir_private(path.parent)
    write_json(path, {"items": [asdict(item) for item in items]})
    return digest_of(items)


def read_lock(project: str) -> tuple[LockItem, ...] | None:
    """*project*'s lock, or ``None`` when it has none or it is unreadable."""
    path = lock_path(project)
    if not path.is_file():
        return None
    try:
        return tuple(LockItem(**item) for item in read_json(path)["items"])
    except (KeyError, TypeError, ValueError):
        return None


def _applied_digest(item: LockItem, overlay: Path) -> str:
    target = overlay / item.applied
    if item.kind == "skill":
        return _skill_digest(_directory_files(target)).hex() if target.is_dir() else ""
    if item.kind == "role":
        try:
            files = _roles.role_overlay_files(target)
        except _role_schema.ArchetypeError:
            return ""
        return _sha(b"".join(files.values()))
    return _sha(target.read_bytes()) if target.is_file() else ""


def overlay_drifted(project: str) -> bool:
    """Whether an applied overlay file no longer hashes to its lock item's ``sha256`` (or is
    gone). ``False`` for a pod with no lock."""
    items = read_lock(project)
    if items is None:
        return False
    overlay = current_home().pod_config_dir(project)
    return any(item.applied and _applied_digest(item, overlay) != item.sha256 for item in items)


def needs_update(project: str) -> str:
    """What `docket pod show` tells a pod applied before the lock: ``""`` when it has none."""
    if (current_home().pod_config_dir(project) / LEGACY_ROLES_FILE).is_file():
        return (
            f"{LEGACY_ROLES_FILE} is no longer read: run `docket pod update <directory>` "
            "to apply this pod's roles again"
        )
    return ""


def drift(project: str, source: str, recorded: str) -> str:
    """``yes``/``no``/``""`` as `docket pod show` reports it: the lock recomputed from *source*
    (when that directory still exists) against *recorded*, and the overlay against the lock."""
    if not source:
        return ""
    source_dir = Path(source)
    differs = overlay_drifted(project)
    if source_dir.is_dir():
        differs = differs or source_digest(source_dir) != recorded
    elif read_lock(project) is None:
        return ""
    return "yes" if differs else "no"
