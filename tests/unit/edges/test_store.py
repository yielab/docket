"""`edges/store.py` -- the single writer of docket-owned JSON: a planted symlink on the
temporary or backup name must never redirect a write outside the owned path."""

from __future__ import annotations

import json
import os
from pathlib import Path

from docket.edges import store

SUBJECT = "docket.edges.store"


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
