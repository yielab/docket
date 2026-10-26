"""The jail port: the real ``Launcher`` and ``FakeJail`` answer the same way.

Run as ``[real, fake]``. The real launcher is built on a host with no usable backend and one
credential name; run_command needs a real shell and a real classifier, so it is covered where
those are (``tests/integration``), not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.fakes import FakeJail, launcher_with

from docket.kernel.errors import InvalidInput
from docket.kernel.ports import Jail

SUBJECT = "docket.kernel.ports"

_SECRET = "DOCKET_CONTRACT_SECRET"


@pytest.fixture(params=["real", "fake"])
def jail(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Jail:
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
    monkeypatch.setenv(_SECRET, "hidden")
    monkeypatch.setenv("DOCKET_CONTRACT_KEEP", "kept")
    if request.param == "real":
        return launcher_with(landlock=False, seatbelt=False, docker=False, credentials={_SECRET})
    return FakeJail(credentials={_SECRET})


def test_a_host_with_no_usable_backend_reports_none_and_no_docker(jail: Jail) -> None:
    availability = jail.sandbox_availability("auto")
    assert availability.backend == "none"
    assert availability.docker is False
    assert jail.docker_daemon_reachable() is False


def test_the_credential_names_are_the_built_in_two_and_the_source(jail: Jail) -> None:
    assert jail.credential_names() >= {"DOCKET_LLM_API_KEY", "TELEGRAM_BOT_TOKEN", _SECRET}


def test_a_task_environment_drops_credentials_and_lets_the_overlay_win(
    jail: Jail, tmp_path: Path
) -> None:
    env = jail.task_environment({"DOCKET_CONTRACT_KEEP": "overlaid", "EXTRA": "1"})
    assert _SECRET not in env
    assert env["DOCKET_CONTRACT_KEEP"] == "overlaid" and env["EXTRA"] == "1"
    assert jail.task_environment()["DOCKET_CONTRACT_KEEP"] == "kept"
    cached = jail.task_environment(cache_dir=tmp_path)
    assert cached["HOME"] == cached["XDG_CACHE_HOME"] == str(tmp_path)


def test_the_temp_variables_point_at_the_temp_dir(jail: Jail, tmp_path: Path) -> None:
    assert jail.tmp_environment(tmp_path) == {
        "TMPDIR": str(tmp_path),
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
    }


def test_the_private_temp_dir_lives_under_the_cache_dir(jail: Jail, tmp_path: Path) -> None:
    tmp = jail.jail_tmp_dir((tmp_path / "work",), tmp_path / "cache")
    assert tmp == (tmp_path / "cache" / "tmp").resolve()
    assert tmp.is_dir()


def test_there_is_no_launch_under_the_none_backend(jail: Jail, tmp_path: Path) -> None:
    with pytest.raises(InvalidInput):
        jail.jail_launch((tmp_path,), "true", "none")


def test_a_path_that_is_not_a_checkout_has_no_git_dirs(jail: Jail, tmp_path: Path) -> None:
    assert jail.worktree_git_dirs(str(tmp_path)) is None
