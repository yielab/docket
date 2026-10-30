"""``routines/*.yaml`` of a directory ``docket pod update`` applies: each file is validated as a
``kind: routine`` document and copied byte-for-byte into the pod overlay's ``routines/``, where
``tasks.application.routines`` resolves it. Export copies them back. A routine only enqueues
tasks, so it is an add, never a run-on-this-machine item (pod-dispatch.spec.md "Routines")."""

from __future__ import annotations

from pathlib import Path

from docket.kernel.home import current_home
from docket.platform import mkdir_private
from docket.teams import config_docs as _config_docs
from docket.teams.apply.model import ApplyAction, ApplyItem, PodApplyError, _RoutineWrite


def routine_files(directory: Path) -> list[Path]:
    """``routines/*.yaml|yml`` directly under *directory*, sorted by name."""
    folder = directory / "routines"
    return sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]) if folder.is_dir() else []


def plan_routines(directory: Path, project: str) -> tuple[list[ApplyItem], list[_RoutineWrite]]:
    """Plan each routine file into *project*'s ``config/routines/`` by bytes. A file that is not
    a valid routine, or a second one naming the same routine, raises PodApplyError."""
    items: list[ApplyItem] = []
    writes: list[_RoutineWrite] = []
    dest_dir = current_home().pod_config_dir(project) / "routines"
    seen: set[str] = set()
    for path in routine_files(directory):
        rel = f"routines/{path.name}"
        try:
            document = _config_docs.load_document(path, kind="routine")
        except _config_docs.ConfigDocError as exc:
            raise PodApplyError(f"{rel}: {exc.message}") from exc
        if document.name in seen:
            raise PodApplyError(f"{rel}: two files name routine {document.name!r}")
        seen.add(document.name)
        source = path.read_bytes()
        dest = dest_dir / path.name
        if dest.is_file() and dest.read_bytes() == source:
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_RoutineWrite(name=path.name, source=source))
        items.append(ApplyItem(kind="routine", name=rel, action=action))
    return items, writes


def write_routines(project: str, writes: tuple[_RoutineWrite, ...]) -> None:
    """Write each planned routine file into *project*'s overlay, private."""
    if not writes:
        return
    folder = current_home().pod_config_dir(project) / "routines"
    mkdir_private(folder)
    for write in writes:
        dest = folder / write.name
        dest.write_bytes(write.source)
        dest.chmod(0o600)


def export_routines(project: str, directory: Path) -> None:
    """Copy *project*'s own routine files byte-for-byte as ``routines/<name>``."""
    files = routine_files(current_home().pod_config_dir(project))
    if not files:
        return
    (directory / "routines").mkdir(parents=True, exist_ok=True)
    for f in files:
        (directory / "routines" / f.name).write_bytes(f.read_bytes())
