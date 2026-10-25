"""Fixtures of the live-smoke tests: a fake operator home that holds, or lacks, a remote key."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.support.smoke_script import CANARY_KEY, REMOTE_KEY_ENV


def _use_operator_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> Path:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delitem(os.environ, REMOTE_KEY_ENV, raising=False)
    return home


@pytest.fixture
def operator_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake operator home whose secrets file holds the canary key; the environment holds none."""
    home = _use_operator_home(monkeypatch, tmp_path / "operator")
    (home / ".docket").mkdir(parents=True)
    (home / ".docket" / "secrets.json").write_text(
        json.dumps({REMOTE_KEY_ENV: CANARY_KEY}), encoding="utf-8"
    )
    return home


@pytest.fixture
def keyless_operator_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake operator home with no secrets file and no key in the environment."""
    return _use_operator_home(monkeypatch, tmp_path / "keyless")
