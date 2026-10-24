"""Shared pytest fixtures for the docket Python suite.

There is no external daemon or compatibility layer to isolate around. The autouse fixture
below isolates Docket's own state instead (fleet.json, the `DOCKET_HOME`-derived registries,
docket-owned secrets) by running each test in a ``use_home`` block.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from docket import bootstrap
from docket.kernel.home import Home, reset_default, use_home
from docket.kernel.ports import git_port, jail_port, process_port, tracer_port
from docket.observability.adapters.local_tracer import LocalTracer
from docket.platform import git as _git_adapter
from docket.platform import process as _process_adapter
from docket.sandbox.launch import Launcher
from tests.support.fakes import (
    FakeGit,
    FakeJail,
    FakeProcess,
    RealExcept,
    launcher_with,
)
from tests.support.git import GitHost

# The real git, process and jail adapters are the default of every test; a test that wants a
# fake asks for the ``fake_git``, ``fake_process`` or ``fake_jail`` fixture below.
bootstrap.bind_adapters()

_LANE_DURATION_CEILING_S = {"unit": 2.0, "guards": 2.0, "integration": 10.0}


def _lane_of(nodeid: str) -> str | None:
    parts = Path(nodeid.split("::", 1)[0]).parts
    if "tests" in parts:
        idx = parts.index("tests")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> object:
    """Fail the report when a test exceeds its lane's duration ceiling."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or report.failed:
        return
    lane = _lane_of(item.nodeid)
    ceiling = _LANE_DURATION_CEILING_S.get(lane) if lane else None
    if ceiling is not None and call.duration > ceiling:
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} took {call.duration:.2f}s, over the {ceiling:.0f}s {lane}/ ceiling"
        )


@pytest.fixture(autouse=True)
def _plain_typer_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer decides at import whether to force colour, from ``GITHUB_ACTIONS``/``FORCE_COLOR``,
    and Rich reads ``FORCE_COLOR`` itself, so on a CI runner usage errors and help arrive boxed
    in ANSI and no substring matches."""
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", None)
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture(autouse=True)
def _keep_pytest_dumpable() -> Iterator[None]:
    """An in-process turn must not make the pytest process non-dumpable for every later test;
    the real flag is exercised in a subprocess (``test_process_non_dumpable.py``)."""
    with process_port.use(RealExcept(_process_adapter, make_non_dumpable=lambda: None)):
        yield


@pytest.fixture
def real_git_except() -> Iterator[Callable[..., None]]:
    """``real_git_except(git_worktree_add=f)`` binds the real git adapter with those calls
    replaced, for the rest of the test."""
    with ExitStack() as stack:

        def bind(**overrides: Callable[..., Any]) -> None:
            stack.enter_context(git_port.use(RealExcept(_git_adapter, **overrides)))

        yield bind


@pytest.fixture
def real_tracer_except() -> Iterator[Callable[..., None]]:
    """``real_tracer_except(trace_event=f)`` binds the real tracer with those calls replaced, for
    the rest of the test."""
    with ExitStack() as stack:

        def bind(**overrides: Callable[..., Any]) -> None:
            stack.enter_context(tracer_port.use(RealExcept(LocalTracer(), **overrides)))

        yield bind


@pytest.fixture
def git_host(monkeypatch: pytest.MonkeyPatch) -> GitHost:
    """The operating system under ``platform.git``: git on PATH or not, and what running it answers."""
    return GitHost(monkeypatch)


@pytest.fixture
def fake_git() -> Iterator[FakeGit]:
    fake = FakeGit()
    with git_port.use(fake):
        yield fake


@pytest.fixture
def fake_process() -> Iterator[FakeProcess]:
    fake = FakeProcess()
    with process_port.use(fake):
        yield fake


@pytest.fixture
def fake_jail() -> Iterator[FakeJail]:
    fake = FakeJail()
    with jail_port.use(fake):
        yield fake


@pytest.fixture
def bind_launcher() -> Iterator[Callable[..., Launcher]]:
    """``bind_launcher(landlock=True, docker=False)`` binds the real jail adapter on a host whose
    backend probes answer so, for the rest of the test."""
    with ExitStack() as stack:

        def bind(**probes: bool) -> Launcher:
            launcher = launcher_with(**probes)
            stack.enter_context(jail_port.use(launcher))
            return launcher

        yield bind


@pytest.fixture(autouse=True)
def _isolate_docket_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every test in a home of its own under ``tmp_path``.

    **Measured, not assumed:** with only ``FLEET_FILE`` isolated, a full ``uv run pytest``
    wrote real approval records, trace JSONL, ``docket-conversations.json`` and
    ``port-allocations.json`` into the developer's actual ``~/.docket`` (verified by
    snapshotting the directory either side of a run). ``audit.log`` has no environment kill
    switch either, and some paths have no override at all, so a test cannot opt out of the real
    path even deliberately; that is what makes this an autouse default rather than each test's
    responsibility.

    A test wanting a specific location wraps its body in ``use_home(Home(path))``, which
    replaces this default for the block. The fleet file stays beside the home, at the leaf it
    has always had here.
    """
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = Home(
        tmp_path / "_autouse_docket_home", fleet_file_override=tmp_path / "_autouse_fleet.json"
    )
    # A thread started without this context, or a child process, falls back to the process
    # default; it is this test's home too, never the developer's ~/.docket nor an earlier test's.
    monkeypatch.setenv("DOCKET_HOME", str(home.root))
    reset_default()
    with use_home(home):
        yield
    reset_default()
