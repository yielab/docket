"""The fix a missing `fetch` names is the command that opens it for the pod's workspace kind
(agent-loop.spec.md requirement 113)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.agent.tools.capability_gap import gap_for
from docket.hops.application import builtin_tools as _builtin_tools
from docket.hops.application import driver_support as _driver_support
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import pod_provisioning as _pp

SUBJECT = "docket.hops.application.driver_support"

_FOLDER_JAIL_OFF = "run `docket setup sandbox on`"
_FOLDER_NO_BACKEND = "run `docket setup sandbox backend docker`"
_REPOSITORY = "run `docket pod set fetchDomains <host> --pod demo`"


def _fetch_fix(role: str) -> str | None:
    base = _builtin_tools.builtin_registry("demo")
    offer = _driver_support.pod_offer(base, "demo", role, "full")
    gap = gap_for("fetch", (), role, offer)
    return None if gap is None else gap.fix


def test_a_folder_pod_with_the_jail_off_says_to_turn_the_jail_on(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")

        assert _fetch_fix("researcher") == _FOLDER_JAIL_OFF


def test_a_folder_pod_with_isolation_on_and_no_backend_names_the_backend(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        bind_launcher(landlock=False, docker=False)
        _fleet.set_sandbox_isolation()

        assert _fetch_fix("researcher") == _FOLDER_NO_BACKEND


def test_a_repository_pod_keeps_the_fetch_domains_command(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("demo", ("lead",), codebase="/src/demo")

        assert _fetch_fix("lead") == _REPOSITORY


def test_a_role_that_denies_fetch_gets_no_gap(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")

        assert _fetch_fix("writer") is None
