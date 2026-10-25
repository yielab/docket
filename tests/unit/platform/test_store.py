"""`platform/store.py` -- the single writer of docket-owned JSON: a planted symlink on the
temporary or backup name must never redirect a write outside the owned path."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from docket.kernel.home import current_home
from docket.kernel.operator_contract import Escalation, Resolution, new_escalation_id
from docket.platform import store

SUBJECT = "docket.platform.store"


def test_a_symlinked_tmp_name_is_replaced_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    target = tmp_path / "docket-models.json"
    (tmp_path / "docket-models.json.tmp").symlink_to(outside)
    store.write_json(target, {"a": 1})
    assert outside.read_text() == "untouched"
    assert not target.is_symlink()
    assert json.loads(target.read_text()) == {"a": 1}
    assert oct(os.stat(target).st_mode & 0o777) == "0o600"


def test_a_symlinked_backup_name_is_replaced_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    target = tmp_path / "fleet.json"
    target.write_text('{"old": true}')
    (tmp_path / "fleet.json.bak").symlink_to(outside)
    store.write_json(target, {"new": True})
    assert outside.read_text() == "untouched"
    bak = tmp_path / "fleet.json.bak"
    assert not bak.is_symlink()
    assert json.loads(bak.read_text()) == {"old": True}


def test_a_backup_is_0600_even_when_the_original_is_world_readable(tmp_path: Path) -> None:
    old = os.umask(0o022)
    try:
        target = tmp_path / "fleet.json"
        target.write_text('{"old": true}')
        os.chmod(target, 0o644)
        store.write_json(target, {"new": True})
    finally:
        os.umask(old)
    assert oct(os.stat(tmp_path / "fleet.json.bak").st_mode & 0o777) == "0o600"


def test_mkdir_private_makes_new_directories_0700_and_leaves_existing_ones(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir(mode=0o755)
    existing.chmod(0o755)
    old_umask = os.umask(0)
    try:
        store.mkdir_private(existing / "a" / "b")
    finally:
        os.umask(old_umask)
    assert oct(os.stat(existing / "a").st_mode & 0o777) == "0o700"
    assert oct(os.stat(existing / "a" / "b").st_mode & 0o777) == "0o700"
    assert oct(os.stat(existing).st_mode & 0o777) == "0o755"


def _escalation(**fields: object) -> Escalation:
    base: dict[str, object] = {
        "id": new_escalation_id(),
        "task": "task-1",
        "pod": "demo",
        "step": "implementer",
        "role": "implementer",
        "kind": "approval",
        "causedBy": "call-1",
        "prompt": "run rm",
        "askedAt": "2026-10-25T10:00:00+00:00",
        "onExpiry": "deny",
        "legacy": {"token": "apr-1"},
    }
    return Escalation.model_validate({**base, **fields})


def test_an_escalation_round_trips_with_the_next_seq_and_mode_0600() -> None:
    first = _escalation(
        options=[{"id": "deny", "label": "Deny", "description": "Refuse."}],
        requestedSchema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    stored = store.write_escalation(first)

    assert stored.seq == 1
    assert store.read_escalation(first.id) == stored
    path = current_home().escalations_dir / f"{first.id}.json"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(path.parent).st_mode & 0o777) == "0o700"
    assert json.loads(path.read_text())["causedBy"] == "call-1"


def test_seq_is_monotonic_across_writes_and_kept_on_a_rewrite() -> None:
    a = store.write_escalation(_escalation())
    b = store.write_escalation(_escalation())
    assert (a.seq, b.seq) == (1, 2)
    again = store.write_escalation(a.model_copy(update={"state": "expired"}))
    assert again.seq == 1
    assert store.next_escalation_seq() == 3


def test_list_escalations_filters_by_state_and_exact_since_seq() -> None:
    first = store.write_escalation(_escalation())
    second = store.write_escalation(_escalation())
    third = store.write_escalation(_escalation(state="expired"))

    assert [e.id for e in store.list_escalations()] == [first.id, second.id, third.id]
    assert [e.id for e in store.list_escalations(state="pending")] == [first.id, second.id]
    assert [e.id for e in store.list_escalations(since_seq=first.seq)] == [second.id, third.id]
    assert store.list_escalations(since_seq=third.seq) == []
    assert [e.id for e in store.list_escalations(state="expired", since_seq=0)] == [third.id]


def test_list_escalations_skips_the_counter_strays_and_invalid_records() -> None:
    good = store.write_escalation(_escalation())
    folder = current_home().escalations_dir
    (folder / "esc-000000000000.json").write_text('{"nope": 1}')
    (folder / "notes.txt").write_text("x")

    assert [e.id for e in store.list_escalations()] == [good.id]


def test_read_escalation_refuses_a_path_shaped_id_and_an_absent_record() -> None:
    assert store.read_escalation("../approvals/x") is None
    assert store.read_escalation("esc-0123456789ab") is None
    with pytest.raises(ValueError, match="escalation id"):
        store.write_escalation(_escalation(id="esc-../../x"))


def test_settle_escalation_moves_only_the_pending_record_naming_the_value() -> None:
    mine = store.write_escalation(_escalation(legacy={"token": "apr-a"}))
    other = store.write_escalation(_escalation(legacy={"token": "apr-b"}))

    assert store.settle_escalation("token", "apr-a", "expired") is True
    assert store.settle_escalation("token", "apr-a", "expired") is False
    assert store.settle_escalation("token", "apr-missing", "expired") is False
    assert store.read_escalation(mine.id).state == "expired"  # type: ignore[union-attr]
    assert store.read_escalation(other.id).state == "pending"  # type: ignore[union-attr]


def _resolved(**fields: object) -> Escalation:
    resolution = Resolution(
        option_id="redis", by="alice", channel="http", at="2026-10-25T10:00:00Z"
    )
    return _escalation(state="resolved", resolution=resolution, **fields)


def test_mark_escalation_applied_stamps_a_resolved_record_exactly_once() -> None:
    record = store.write_escalation(_resolved())

    assert store.mark_escalation_applied(record.id, "2026-10-25T10:05:00Z") is True
    assert store.mark_escalation_applied(record.id, "2026-10-25T10:06:00Z") is False

    stored = store.read_escalation(record.id)
    assert stored is not None and stored.resolution is not None
    assert stored.resolution.applied_at == "2026-10-25T10:05:00Z"
    assert stored.resolution.option_id == "redis" and stored.state == "resolved"


@pytest.mark.parametrize("state", ["pending", "expired", "decided"])
def test_mark_escalation_applied_leaves_any_other_state_alone(state: str) -> None:
    record = store.write_escalation(_resolved().model_copy(update={"state": state}))

    assert store.mark_escalation_applied(record.id, "2026-10-25T10:05:00Z") is False

    stored = store.read_escalation(record.id)
    assert stored is not None and stored.resolution is not None
    assert stored.resolution.applied_at is None


def test_mark_escalation_applied_ignores_an_absent_record() -> None:
    assert store.mark_escalation_applied("esc-0123456789ab", "2026-10-25T10:05:00Z") is False


def _settled(**fields: object) -> Escalation:
    return _escalation(state="expired", **fields)


def test_the_pending_scan_opens_no_settled_file(monkeypatch: pytest.MonkeyPatch) -> None:
    live = store.write_escalation(_escalation())
    done = [store.write_escalation(_settled()) for _ in range(5)]
    assert len(list((current_home().escalations_dir / "settled").glob("esc-*.json"))) == 5
    opened: list[Path] = []
    real_read = Path.read_bytes

    def _spy(self: Path) -> bytes:
        opened.append(self)
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", _spy)

    assert [e.id for e in store.list_escalations(state="pending")] == [live.id]
    assert not [p for p in opened if p.parent.name == "settled"]
    assert [e.id for e in store.list_escalations()] == [live.id, *[e.id for e in done]]
    assert store.read_escalation(done[0].id) == done[0]


def test_a_settled_record_leaves_the_pending_directory_and_keeps_its_seq() -> None:
    folder = current_home().escalations_dir
    mine = store.write_escalation(_escalation(legacy={"token": "apr-a"}))
    resolved = store.write_escalation(_escalation(legacy={"token": "apr-b"}))

    assert store.settle_escalation("token", "apr-a", "expired") is True
    resolution = Resolution(
        option_id="grant", by="alice", channel="http", at="2026-10-25T10:00:00Z"
    )
    stored = store.resolve_escalation(resolved.id, resolution)

    assert stored is not None and stored.state == "resolved"
    assert not (folder / f"{mine.id}.json").exists()
    assert not (folder / f"{resolved.id}.json").exists()
    settled = store.read_escalation(mine.id)
    assert settled is not None and (settled.state, settled.seq) == ("expired", mine.seq)
    assert store.resolve_escalation(resolved.id, resolution) is None
    assert store.mark_escalation_applied(resolved.id, "2026-10-25T10:05:00Z") is True
    path = folder / "settled" / f"{resolved.id}.json"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(path.parent).st_mode & 0o777) == "0o700"


def _age(escalation_id: str, days: int) -> None:
    path = current_home().escalations_dir / "settled" / f"{escalation_id}.json"
    old = path.stat().st_mtime - days * 86400
    os.utime(path, (old, old))


def test_retention_deletes_old_settled_records_and_keeps_live_work() -> None:
    old = store.write_escalation(_settled())
    recent = store.write_escalation(_settled())
    unapplied = store.write_escalation(_resolved())
    live = store.write_escalation(_escalation())
    for record in (old, unapplied):
        _age(record.id, 90)

    assert store.prune_settled_escalations(dry_run=True) == 1
    assert store.read_escalation(old.id) is not None
    assert store.prune_settled_escalations() == 1

    assert store.read_escalation(old.id) is None
    kept = {recent.id, unapplied.id, live.id}
    assert {e.id for e in store.list_escalations()} == kept
    assert store.write_escalation(_escalation()).seq == live.seq + 1


def test_retention_applies_to_an_applied_resolution() -> None:
    record = store.write_escalation(_resolved())
    assert store.mark_escalation_applied(record.id, "2026-10-25T10:05:00Z") is True
    _age(record.id, 90)

    assert store.prune_settled_escalations() == 1
    assert store.read_escalation(record.id) is None


def test_rewriting_a_record_leaves_it_in_one_directory_only() -> None:
    folder = current_home().escalations_dir
    record = store.write_escalation(_escalation())
    settled = store.write_escalation(record.model_copy(update={"state": "expired"}))
    assert [p.parent.name for p in folder.rglob(f"{record.id}.json")] == ["settled"]

    store.write_escalation(settled.model_copy(update={"state": "pending"}))
    assert [p.parent for p in folder.rglob(f"{record.id}.json")] == [folder]
