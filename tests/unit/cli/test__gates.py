"""`docket gates` -- a bare `isolate` is a read, never a write."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _gates

SUBJECT = "docket.cli._gates"


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _fresh_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    repoint_docket_home(monkeypatch, home)
    return home


def test_bare_isolate_writes_nothing_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _fresh_home(tmp_path, monkeypatch)
    fleet_before, audit_before = _bytes(_cfg.FLEET_FILE), _bytes(_cfg.AUDIT_LOG)

    assert _gates.run_gates("isolate") == 2

    assert _bytes(_cfg.FLEET_FILE) == fleet_before
    assert _bytes(_cfg.AUDIT_LOG) == audit_before
    assert not (home / "audit.log").exists()


def test_an_unknown_isolate_word_writes_nothing_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)
    fleet_before, audit_before = _bytes(_cfg.FLEET_FILE), _bytes(_cfg.AUDIT_LOG)

    assert _gates.run_gates("isolate", want="bogus") == 2

    assert _bytes(_cfg.FLEET_FILE) == fleet_before
    assert _bytes(_cfg.AUDIT_LOG) == audit_before
