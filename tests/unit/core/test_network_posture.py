"""The one place the network line is worded: cut only when isolation is on."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.core import fleet as _fleet
from docket.core import network_posture as _np

SUBJECT = "docket.core.network_posture"


def test_none_with_isolation_on_says_the_jail_cuts_it() -> None:
    posture = _np.network_posture("none", "default", isolation_on=True)
    assert posture.enforced is True
    assert posture.line == "none (default); jailed tool calls have no network"
    assert posture.short == "none"


def test_none_with_isolation_off_says_egress_is_open() -> None:
    posture = _np.network_posture("none", "default", isolation_on=False)
    assert posture.enforced is False
    assert "not enforced: isolation off" in posture.line
    assert "egress is open" in posture.line
    assert "no network" not in posture.line
    assert posture.short == "none (not enforced: isolation off)"


def test_open_is_never_enforced() -> None:
    for on in (True, False):
        posture = _np.network_posture("open", "global", isolation_on=on)
        assert posture.enforced is False
        assert posture.short == "open"


def test_global_posture_reads_the_fleet_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / ".docket"
    home.mkdir()
    repoint_docket_home(monkeypatch, home)
    fresh = _np.global_posture()
    assert (fresh.mode, fresh.scope, fresh.enforced) == ("none", "default", False)
    _fleet.set_network_mode("none")
    _fleet.set_sandbox_isolation()
    recorded = _np.global_posture()
    assert (recorded.scope, recorded.enforced) == ("global", True)
