"""``records/*.yaml`` of a directory ``docket pod update`` applies: each file is validated as a
``kind: records`` document, checked against the pod's records file and copied byte-for-byte into the
pod overlay's ``records/``, where its table is created or extended. Export copies the documents back
and never a row (specs/functional/pod-records.spec.md "The document")."""

from __future__ import annotations

from pathlib import Path

from docket.kernel.home import current_home
from docket.kernel.records import RecordsError, RecordSet
from docket.platform import mkdir_private
from docket.teams import records as _records
from docket.teams.apply.model import ApplyAction, ApplyItem, PodApplyError, _RecordsWrite


def plan_records(directory: Path, project: str) -> tuple[list[ApplyItem], list[_RecordsWrite]]:
    """Plan ``records/*`` into *project*'s own ``records/`` by bytes, checking each set against the
    pod's records file. An invalid file, a set declared twice, or a document that omits, retypes or
    re-keys what the table already declares raises ``PodApplyError``; nothing is created."""
    declared: dict[str, tuple[Path, bytes, RecordSet]] = {}
    for path in _records.records_files(directory):
        try:
            record_set = _records.load_records_document(path)
        except _records.RecordsDocError as exc:
            raise PodApplyError(str(exc)) from exc
        if record_set.name in declared:
            raise PodApplyError(f"records/{path.name}: set {record_set.name!r} is declared twice")
        declared[record_set.name] = (path, path.read_bytes(), record_set)
    items: list[ApplyItem] = []
    writes: list[_RecordsWrite] = []
    dest_dir = _records.pod_records_dir(project)
    for name, (path, source, record_set) in declared.items():
        try:
            outcome = _records.check_set(project, record_set)
        except RecordsError as exc:
            raise PodApplyError(f"records/{path.name}: {exc}") from exc
        dest = dest_dir / path.name
        same = dest.is_file() and dest.read_bytes() == source
        note = ""
        action: ApplyAction = "skip"
        if outcome.created:
            action, note = "add", "creates the table"
        elif outcome.added:
            action, note = "replace", "adds column " + ", ".join(outcome.added)
        elif not same:
            action = "replace" if dest.is_file() else "add"
        if action != "skip":
            writes.append(_RecordsWrite(name=path.name, source=source, record_set=record_set))
        items.append(ApplyItem(kind="records", name=name, action=action, note=note))
    return items, writes


def write_records(project: str, writes: tuple[_RecordsWrite, ...]) -> None:
    """Write each planned records file into *project*'s overlay, private, then create or extend
    its table."""
    if not writes:
        return
    folder = _records.pod_records_dir(project)
    mkdir_private(folder)
    for write in writes:
        dest = folder / write.name
        dest.write_bytes(write.source)
        dest.chmod(0o600)
        _records.ensure_set(project, write.record_set)


def export_records(project: str, directory: Path) -> None:
    """Copy *project*'s own records documents byte-for-byte as ``records/<name>``; never a row."""
    files = _records.records_files(current_home().pod_config_dir(project))
    if not files:
        return
    (directory / "records").mkdir(parents=True, exist_ok=True)
    for f in files:
        (directory / "records" / f.name).write_bytes(f.read_bytes())
