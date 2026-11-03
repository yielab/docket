"""The one place the network line is worded: cut only when isolation is on."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.kernel.home import Home, use_home
from docket.teams import fleet as _fleet
from docket.teams import network_posture as _np

SUBJECT = "docket.teams.network_posture"


def test_none_with_isolation_on_says_the_jail_cuts_it() -> None:
    posture = _np.network_posture("none", "default", jailed=True)
    assert posture.enforced is True
    assert posture.line == "none (default); jailed tool calls have no network"
    assert posture.short == "none"


def test_none_with_isolation_off_says_egress_is_open() -> None:
    posture = _np.network_posture("none", "default", jailed=False)
    assert posture.enforced is False
    assert "not enforced: isolation off" in posture.line
    assert "egress is open" in posture.line
    assert "no network" not in posture.line
    assert posture.short == "none (not enforced: isolation off)"


def test_open_is_never_enforced() -> None:
    for on in (True, False):
        posture = _np.network_posture("open", "global", jailed=on)
        assert posture.enforced is False
        assert posture.short == "open"


def test_a_pod_grant_is_worded_as_one() -> None:
    posture = _np.network_posture("open", "pod-grant", jailed=True)
    assert posture.enforced is False
    assert posture.line == "open (pod grant)"
    assert posture.short == "open (pod grant)"


def test_global_posture_reads_the_fleet_record(tmp_path: Path) -> None:
    home = tmp_path / ".docket"
    home.mkdir()
    with use_home(Home(home)):
        fresh = _np.global_posture()
        assert (fresh.mode, fresh.scope, fresh.enforced) == ("none", "default", False)
        _fleet.set_network_mode("none")
        _fleet.set_sandbox_isolation()
        recorded = _np.global_posture()
        assert (recorded.scope, recorded.enforced) == ("global", True)


def _posture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str, isolation: bool, backend: str
) -> _np.NetworkPosture:
    """The fleet posture of a home that records *mode* and *isolation* on a machine whose only
    sandbox backend is *backend*."""
    home = tmp_path / ".docket"
    home.mkdir()
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", backend)
    with use_home(Home(home)):
        _fleet.set_network_mode(mode)
        if isolation:
            _fleet.set_sandbox_isolation()
        else:
            _fleet.disable_sandbox_isolation()
        return _np.global_posture()


def test_none_is_enforced_with_isolation_on_and_a_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posture = _posture(tmp_path, monkeypatch, mode="none", isolation=True, backend="landlock")
    assert posture.enforced is True


def test_none_is_not_enforced_with_isolation_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posture = _posture(tmp_path, monkeypatch, mode="none", isolation=False, backend="landlock")
    assert posture.enforced is False


def test_none_is_not_enforced_when_isolation_is_on_but_no_backend_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posture = _posture(tmp_path, monkeypatch, mode="none", isolation=True, backend="none")
    assert posture.enforced is False
    assert "no network" not in posture.line


def test_open_is_not_enforced_with_isolation_on_and_a_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posture = _posture(tmp_path, monkeypatch, mode="open", isolation=True, backend="landlock")
    assert posture.enforced is False
