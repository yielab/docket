"""The one place the network line is worded: cut only when isolation is on."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.sandbox.launch import Launcher
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


def test_global_posture_reads_the_fleet_record(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    bind_launcher(landlock=True)
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
    tmp_path: Path,
    bind_launcher: Callable[..., Launcher],
    *,
    mode: str,
    isolation: bool,
    backend: str,
) -> _np.NetworkPosture:
    """The fleet posture of a home that records *mode* and *isolation* on a machine whose only
    sandbox backend is *backend*."""
    home = tmp_path / ".docket"
    home.mkdir()
    bind_launcher(landlock=backend == "landlock", seatbelt=False, docker=False)
    with use_home(Home(home)):
        _fleet.set_network_mode(mode)
        if isolation:
            _fleet.set_sandbox_isolation()
        else:
            _fleet.disable_sandbox_isolation()
        return _np.global_posture()


def test_none_is_enforced_with_isolation_on_and_a_backend(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    posture = _posture(tmp_path, bind_launcher, mode="none", isolation=True, backend="landlock")
    assert posture.enforced is True


def test_none_is_not_enforced_with_isolation_off(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    posture = _posture(tmp_path, bind_launcher, mode="none", isolation=False, backend="landlock")
    assert posture.enforced is False


def test_none_is_not_enforced_when_isolation_is_on_but_no_backend_exists(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    posture = _posture(tmp_path, bind_launcher, mode="none", isolation=True, backend="none")
    assert posture.enforced is False
    assert "no network" not in posture.line


def test_open_is_not_enforced_with_isolation_on_and_a_backend(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    posture = _posture(tmp_path, bind_launcher, mode="open", isolation=True, backend="landlock")
    assert posture.enforced is False


def _reach(
    tmp_path: Path,
    bind_launcher: Callable[..., Launcher],
    *,
    kind: str,
    isolation: bool = True,
    backend: bool = True,
    hosts: str = "",
    grant: bool = False,
) -> _np.FetchReach:
    """The reach of pod ``p`` of workspace *kind*, on a home with *isolation* recorded and a
    landlock probe answering *backend*, declaring *hosts* (``*`` only with *grant*)."""
    home = tmp_path / ".docket"
    home.mkdir()
    bind_launcher(landlock=backend, seatbelt=False, docker=False)
    with use_home(Home(home)):
        if isolation:
            _fleet.set_sandbox_isolation()
        meta: dict[str, object] = {"kind": "project", "scope": "project", "workspaceKind": kind}
        if hosts:
            meta["fetchDomains"] = hosts
        if grant:
            meta["fetchGrant"] = {"at": "2026-11-04", "by": "test"}
        path = current_home().meta_path("p-lead")
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(path, meta)
        return _np.fetch_reach("p")


def test_a_folder_pod_under_the_jail_with_no_list_is_open(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    reach = _reach(tmp_path, bind_launcher, kind="workdir")
    assert (reach.mode, reach.hosts, reach.fix) == ("open", ("*",), "")
    assert reach.reason == "a folder team under the jail reads any public host"


def test_a_folder_pod_without_the_jail_is_none_and_the_fix_turns_the_jail_on(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    off = _reach(tmp_path, bind_launcher, kind="workdir", isolation=False)
    assert (off.mode, off.hosts, off.fix) == ("none", (), "docket setup sandbox on")


def test_a_folder_pod_with_isolation_on_and_no_backend_points_at_the_backend(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    reach = _reach(tmp_path, bind_launcher, kind="workdir", backend=False)
    assert (reach.mode, reach.fix) == ("none", "docket setup sandbox backend docker")


def test_a_repository_pod_is_none_and_the_fix_declares_a_host(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    reach = _reach(tmp_path, bind_launcher, kind="codebase")
    assert (reach.mode, reach.hosts) == ("none", ())
    assert reach.fix == "docket pod set fetchDomains <host> --pod p"


def test_a_declared_list_is_listed_for_either_kind(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    reach = _reach(tmp_path, bind_launcher, kind="workdir", hosts="docs.python.org")
    assert (reach.mode, reach.hosts, reach.fix) == ("listed", ("docs.python.org",), "")


def test_the_widen_grant_is_listed_and_says_any_host(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    reach = _reach(tmp_path, bind_launcher, kind="codebase", isolation=False, hosts="*", grant=True)
    assert (reach.mode, reach.hosts) == ("listed", ("*",))
    assert "any public host" in reach.reason
