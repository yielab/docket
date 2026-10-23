"""``kernel.home`` -- paths follow the root, and the current Home is set per block and per
context, never per process."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel.home import Home, current_home, reset_default, use_home

SUBJECT = "docket.kernel.home"


@pytest.fixture(autouse=True)
def _fresh_default() -> Iterator[None]:
    reset_default()
    yield
    reset_default()


def test_every_unset_path_follows_the_root(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    assert home.audit_log == tmp_path / "audit.log"
    assert home.traces_dir == tmp_path / "traces"
    assert home.meta_path("a") == tmp_path / "workspaces" / "projects" / "a" / ".docket-meta.json"
    assert home.pod_scratch_dir("p") == tmp_path / "workspaces" / "pods" / "p" / ".scratch"


def test_an_override_wins_over_the_root(tmp_path: Path) -> None:
    home = Home(root=tmp_path, traces_dir_override=tmp_path / "elsewhere")
    assert home.traces_dir == tmp_path / "elsewhere"
    assert home.sessions_dir == tmp_path / "sessions"


def test_a_home_is_hashable(tmp_path: Path) -> None:
    assert hash(Home(root=tmp_path)) == hash(Home(root=tmp_path))


def test_retries_per_role_fall_back_to_the_default() -> None:
    home = Home.from_environ({"DISPATCH_RETRIES_DEFAULT": "4", "DISPATCH_RETRIES_LEAD": "0"})
    assert home.dispatch_retries_per_role == {
        "lead": 0,
        "implementer": 4,
        "reviewer": 4,
        "tester": 4,
    }


def test_two_homes_nest_and_restore(tmp_path: Path) -> None:
    a, b = Home(root=tmp_path / "a"), Home(root=tmp_path / "b")
    with use_home(a):
        assert current_home() is a
        with use_home(b):
            assert current_home() is b
        assert current_home() is a
    assert current_home() not in (a, b)


def test_a_thread_sees_the_home_only_through_a_copied_context(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    seen: dict[str, Home] = {}

    def record(key: str) -> None:
        seen[key] = current_home()

    with use_home(home):
        plain = threading.Thread(target=record, args=("plain",))
        ctx = contextvars.copy_context()
        copied = threading.Thread(target=ctx.run, args=(record, "copied"))
        for t in (plain, copied):
            t.start()
            t.join()
    assert seen["copied"] is home
    assert seen["plain"] is not home


def test_the_default_reads_the_environment_once_until_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_HOME", str(tmp_path / "first"))
    assert current_home().root == tmp_path / "first"
    monkeypatch.setenv("DOCKET_HOME", str(tmp_path / "second"))
    assert current_home().root == tmp_path / "first"
    reset_default()
    assert current_home().root == tmp_path / "second"
