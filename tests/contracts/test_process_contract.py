"""The process port: the real adapter and ``FakeProcess`` answer the same way.

Run as ``[real, fake]``. The world under test owns the environment, PATH and process table
(the real host, or the fake's dicts); everything asserted here is what a caller may rely on.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.support.fakes import FakeProcess

from docket.kernel.ports import Process
from docket.platform import process as real_process

SUBJECT = "docket.kernel.ports"


@dataclass
class World:
    process: Process
    set_env: Callable[[str, str], None]
    clear_env: Callable[[str], None]
    set_path: Callable[[tuple[str, ...]], None]  # the binaries that resolve; none besides
    live_group: Callable[[], int]  # a process group that is alive
    reap: Callable[[int], None]  # collect the group's leader once it was killed
    dead_pid: Callable[[], int]


def _real_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    procs: dict[int, subprocess.Popen[bytes]] = {}

    def set_path(binaries: tuple[str, ...]) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name in binaries:
            stub = bin_dir / name
            stub.write_text("#!/bin/sh\n")
            stub.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))

    def live_group() -> int:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
        )
        procs[proc.pid] = proc
        return proc.pid

    def dead_pid() -> int:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    try:
        yield World(
            real_process,
            monkeypatch.setenv,
            lambda name: monkeypatch.delenv(name, raising=False),
            set_path,
            live_group,
            lambda pgid: procs[pgid].wait(timeout=5),
            dead_pid,
        )
    finally:
        for proc in procs.values():
            proc.kill()
            proc.wait()


def _fake_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    fake = FakeProcess()
    pids = iter(range(40000, 50000))

    def live_group() -> int:
        pid = next(pids)
        fake.alive.add(pid)
        return pid

    def set_path(binaries: tuple[str, ...]) -> None:
        fake.binaries = set(binaries)

    yield World(
        fake,
        lambda name, value: fake.env.__setitem__(name, value),
        lambda name: fake.env.pop(name, None) and None,
        set_path,
        live_group,
        lambda pgid: None,
        lambda: next(pids),
    )


@pytest.fixture(params=["real", "fake"])
def world(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[World]:
    yield from (_real_world if request.param == "real" else _fake_world)(tmp_path, monkeypatch)


def test_the_environment_switches_default_off_and_are_read_live(world: World) -> None:
    p = world.process
    for name in ("DOCKET_NO_TRACE", "DOCKET_NO_EXPORT", "DOCKET_SECRETS_BACKEND"):
        world.clear_env(name)
    assert (p.no_trace(), p.no_export(), p.secrets_backend_requested()) == (False, False, "file")
    world.set_env("DOCKET_NO_TRACE", "1")
    world.set_env("DOCKET_NO_EXPORT", "1")
    world.set_env("DOCKET_SECRETS_BACKEND", "keyring")
    assert (p.no_trace(), p.no_export(), p.secrets_backend_requested()) == (True, True, "keyring")
    world.set_env("DOCKET_NO_TRACE", "true")
    assert p.no_trace() is False


def test_an_environment_value_is_stripped_and_empty_when_unset(world: World) -> None:
    world.clear_env("DOCKET_CONTRACT_VALUE")
    assert world.process.env_value("DOCKET_CONTRACT_VALUE") == ""
    world.set_env("DOCKET_CONTRACT_VALUE", "  kept  ")
    assert world.process.env_value("DOCKET_CONTRACT_VALUE") == "kept"


def test_credential_values_come_from_named_variables_and_suffixes_and_skip_blanks(
    world: World,
) -> None:
    world.set_env("DOCKET_CONTRACT_NAMED", " one ")
    world.set_env("DOCKET_CONTRACT_BLANK", "   ")
    world.set_env("DOCKET_CONTRACT_X_ZZQ", "two")
    found = world.process.credential_env_values(
        ("DOCKET_CONTRACT_NAMED", "DOCKET_CONTRACT_BLANK"), ("_ZZQ",)
    )
    assert sorted(found) == ["one", "two"]


def test_a_binary_is_found_only_when_it_is_on_the_path(world: World) -> None:
    world.set_path(("notify-send",))
    assert world.process.which("notify-send") is True
    assert world.process.which("secret-tool") is False
    assert world.process.secret_tool_available() is False
    world.set_path(("secret-tool",))
    assert world.process.secret_tool_available() is True


def test_the_keyring_tool_missing_means_no_value_and_a_failed_store(world: World) -> None:
    world.set_path(())
    p = world.process
    assert p.secret_tool_lookup("svc", "KEY") is None
    assert p.secret_tool_store("svc", "KEY", "v") is False
    assert p.secret_tool_clear("svc", "KEY") is False


def test_a_process_is_alive_until_it_is_gone_and_a_bad_pid_never_is(world: World) -> None:
    p = world.process
    assert p.process_alive(0) is False
    assert p.process_alive(-5) is False
    assert p.process_alive(world.dead_pid()) is False
    pgid = world.live_group()
    assert p.process_alive(pgid) is True


def test_killing_a_group_reports_whether_it_was_alive(world: World) -> None:
    p = world.process
    assert p.kill_process_group(world.dead_pid(), grace_s=0.1) is False
    pgid = world.live_group()
    assert p.kill_process_group(pgid, grace_s=0.5) is True
    world.reap(pgid)
    assert p.process_alive(pgid) is False
