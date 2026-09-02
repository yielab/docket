"""Behavioral contract for corrupt-primary recovery at the JSON-store chokepoint."""

from __future__ import annotations

import json
import stat
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import app
from docket.edges import store

_CORRUPT_PRIMARY = b"{broken"


def _backup(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _quarantine(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".corrupt")


def _tmp(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".tmp")


def _seed_two_generations(path: Path, older: dict[str, Any], newer: dict[str, Any]) -> bytes:
    store.write_json(path, older)
    store.write_json(path, newer)
    backup_bytes = _backup(path).read_bytes()
    assert json.loads(backup_bytes) == older
    return backup_bytes


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("parent_exists", [True, False])
def test_missing_primary_keeps_empty_default_without_restoring_backup(
    tmp_path: Path, parent_exists: bool
) -> None:
    parent = tmp_path / "registry"
    path = parent / "state.json"
    backup = _backup(path)
    if parent_exists:
        parent.mkdir()
        backup.write_bytes(b'{"generation":"orphaned-backup"}\n')
        backup_before = backup.read_bytes()

    assert store.read_json(path) == {}

    assert not path.exists()
    if parent_exists:
        assert backup.read_bytes() == backup_before
    else:
        assert not parent.exists()


@pytest.mark.parametrize(
    "backup_bytes",
    [b'{"generation":"stale"}\n', b"{malformed backup"],
    ids=["stale-valid-backup", "malformed-backup"],
)
def test_valid_primary_wins_without_mutating_any_data_bytes(
    tmp_path: Path, backup_bytes: bytes
) -> None:
    path = tmp_path / "state.json"
    current = {"generation": "current", "items": [1, 2]}
    _seed_two_generations(path, {"generation": "old"}, current)
    _backup(path).write_bytes(backup_bytes)
    primary_before = path.read_bytes()
    backup_before = _backup(path).read_bytes()

    assert store.read_json(path) == current

    assert path.read_bytes() == primary_before
    assert _backup(path).read_bytes() == backup_before
    assert not _quarantine(path).exists()
    assert not _tmp(path).exists()


def test_public_read_recovers_backup_and_quarantines_exact_primary_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    recovered = {"generation": "previous", "items": ["complete"]}
    backup_before = _seed_two_generations(
        path, recovered, {"generation": "current", "items": ["newer"]}
    )
    path.write_bytes(_CORRUPT_PRIMARY)

    assert store.read_json(path) == recovered

    assert json.loads(path.read_bytes()) == recovered
    assert _mode(path) == 0o600
    assert _backup(path).read_bytes() == backup_before
    assert _quarantine(path).read_bytes() == _CORRUPT_PRIMARY
    assert _mode(_quarantine(path)) == 0o600
    assert list(tmp_path.glob("state.json.corrupt*")) == [_quarantine(path)]
    assert not _tmp(path).exists()


def test_restore_write_failure_keeps_recovery_inputs_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    recovered = {"generation": "previous", "items": ["complete"]}
    backup_before = _seed_two_generations(path, recovered, {"generation": "current"})
    path.write_bytes(_CORRUPT_PRIMARY)
    real_replace = store.os.replace

    def _fail_primary_restore(src: Any, dst: Any) -> None:
        if Path(dst) == path:
            raise OSError("primary restore blocked")
        real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", _fail_primary_restore)

    with pytest.raises(OSError, match="primary restore blocked"):
        store.read_json(path)

    assert path.read_bytes() == _CORRUPT_PRIMARY
    assert _backup(path).read_bytes() == backup_before
    assert _quarantine(path).read_bytes() == _CORRUPT_PRIMARY
    assert not _tmp(path).exists()
    assert not _quarantine(path).with_suffix(".corrupt.tmp").exists()


def test_runs_list_cli_recovers_the_prior_complete_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "docket-runs.json"
    prior = {
        "runs": [
            {
                "id": "run-prior",
                "project": "demo",
                "source": "cli",
                "state": "succeeded",
                "taskIds": ["task-1"],
                "error": "",
                "created": "2026-09-02T10:00:00Z",
            }
        ]
    }
    newer = {"runs": [*prior["runs"], {"id": "run-newer", "created": "2026-09-02T11:00:00Z"}]}
    _seed_two_generations(path, prior, newer)
    path.write_bytes(_CORRUPT_PRIMARY)
    monkeypatch.setattr(_cfg, "RUNS_FILE", path, raising=True)

    result = CliRunner().invoke(app, ["runs", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == prior
    assert json.loads(path.read_bytes()) == prior
    assert _quarantine(path).read_bytes() == _CORRUPT_PRIMARY


@pytest.mark.parametrize("backup_state", ["missing", "malformed"])
def test_unusable_backup_raises_typed_actionable_error_without_mutation(
    tmp_path: Path, backup_state: str
) -> None:
    path = tmp_path / "state.json"
    _seed_two_generations(path, {"generation": "previous"}, {"generation": "current"})
    path.write_bytes(_CORRUPT_PRIMARY)
    if backup_state == "missing":
        _backup(path).unlink()
    else:
        _backup(path).write_bytes(b"{broken backup")

    primary_before = path.read_bytes()
    primary_mode_before = _mode(path)
    backup_existed_before = _backup(path).exists()
    backup_before = _backup(path).read_bytes() if backup_existed_before else None
    backup_mode_before = _mode(_backup(path)) if backup_existed_before else None
    recovery_error = getattr(store, "StoreRecoveryError", RuntimeError)

    with pytest.raises(recovery_error) as exc_info:
        store.read_json(path)

    assert type(exc_info.value).__name__ == "StoreRecoveryError"
    message = str(exc_info.value)
    assert path.name in message
    assert _backup(path).name in message
    assert backup_state in message
    assert path.read_bytes() == primary_before
    assert _mode(path) == primary_mode_before
    assert _backup(path).exists() is backup_existed_before
    if backup_existed_before:
        assert _backup(path).read_bytes() == backup_before
        assert _mode(_backup(path)) == backup_mode_before
    assert not _quarantine(path).exists()
    assert not _tmp(path).exists()


def _run_at_barrier(actions: list[Callable[[], None]], timeout: float = 3.0) -> list[BaseException]:
    barrier = threading.Barrier(len(actions))
    errors: list[BaseException] = []

    def _wrapped(action: Callable[[], None]) -> None:
        try:
            barrier.wait(timeout=timeout)
            action()
        except BaseException as exc:  # retain thread failures for the parent assertion
            errors.append(exc)

    threads = [threading.Thread(target=_wrapped, args=(action,), daemon=True) for action in actions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    assert all(not thread.is_alive() for thread in threads), "store lock did not make progress"
    return errors


def _read_into(path: Path, results: list[dict[str, Any]]) -> None:
    results.append(store.read_json(path))


def _mutate_into(path: Path, updated: dict[str, Any], results: list[dict[str, Any]]) -> None:
    results.append(store.read_modify_write(path, lambda _doc: updated))


def test_concurrent_readers_share_one_recovery_for_twenty_repetitions(
    tmp_path: Path,
) -> None:
    recovered = {"generation": "previous", "items": ["complete"]}

    for repetition in range(20):
        path = tmp_path / str(repetition) / "state.json"
        path.parent.mkdir()
        backup_before = _seed_two_generations(path, recovered, {"generation": "current"})
        path.write_bytes(_CORRUPT_PRIMARY)
        results: list[dict[str, Any]] = []

        read = partial(_read_into, path, results)
        errors = _run_at_barrier([read, read])

        assert errors == [], f"repetition {repetition}: {errors!r}"
        assert results == [recovered, recovered]
        assert json.loads(path.read_bytes()) == recovered
        assert _backup(path).read_bytes() == backup_before
        assert _quarantine(path).read_bytes() == _CORRUPT_PRIMARY
        assert list(path.parent.glob("state.json.corrupt*")) == [_quarantine(path)]
        assert not _tmp(path).exists()


def test_recovery_and_locked_mutation_serialize_without_lock_reentry(
    tmp_path: Path,
) -> None:
    recovered = {"generation": "previous", "items": ["complete"]}
    updated = {**recovered, "writer": "complete"}

    for repetition in range(20):
        path = tmp_path / str(repetition) / "state.json"
        path.parent.mkdir()
        _seed_two_generations(path, recovered, {"generation": "current"})
        path.write_bytes(_CORRUPT_PRIMARY)
        read_results: list[dict[str, Any]] = []
        write_results: list[dict[str, Any]] = []

        errors = _run_at_barrier(
            [
                partial(_read_into, path, read_results),
                partial(_mutate_into, path, updated, write_results),
            ]
        )

        assert errors == [], f"repetition {repetition}: {errors!r}"
        assert write_results == [updated]
        assert read_results[0] in (recovered, updated)
        assert json.loads(path.read_bytes()) == updated
        assert json.loads(_backup(path).read_bytes()) == recovered
        assert _quarantine(path).read_bytes() == _CORRUPT_PRIMARY
        assert list(path.parent.glob("state.json.corrupt*")) == [_quarantine(path)]
        assert not _tmp(path).exists()
