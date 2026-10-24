"""Threads carry the context they were built in."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.support import home as _support_home

from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import new_thread, start_thread, submit

SUBJECT = "docket.kernel.threads"

_fresh_default = _support_home.fresh_default


def _root_seen_by(starter: object, home: Home) -> Path:
    seen: list[Path] = []

    def work() -> None:
        seen.append(current_home().root)

    with use_home(home):
        t = starter(work)  # type: ignore[operator]
    t.join(5)
    return seen[0]


def _started(t: threading.Thread) -> threading.Thread:
    t.start()
    return t


def test_a_bare_thread_falls_back_to_the_default_home(tmp_path: Path) -> None:
    root = _root_seen_by(
        lambda fn: _started(threading.Thread(target=fn, daemon=True)), Home(root=tmp_path / "a")
    )
    assert root != tmp_path / "a"


def test_start_thread_sees_the_home_it_was_started_under(tmp_path: Path) -> None:
    assert _root_seen_by(start_thread, Home(root=tmp_path / "a")) == tmp_path / "a"


def test_new_thread_copies_the_context_when_built_not_when_started(tmp_path: Path) -> None:
    seen: list[Path] = []
    with use_home(Home(root=tmp_path / "a")):
        t = new_thread(lambda: seen.append(current_home().root))
    t.start()
    t.join(5)
    assert seen == [tmp_path / "a"]


def test_submit_runs_the_callable_in_the_context_at_the_call(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as pool, use_home(Home(root=tmp_path / "a")):
        root = submit(pool, lambda: current_home().root).result(5)
    assert root == tmp_path / "a"


def test_two_homes_do_not_leak_into_each_other_across_threads(tmp_path: Path) -> None:
    a = _root_seen_by(start_thread, Home(root=tmp_path / "a"))
    b = _root_seen_by(start_thread, Home(root=tmp_path / "b"))
    assert (a, b) == (tmp_path / "a", tmp_path / "b")
