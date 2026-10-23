"""The Landlock jail on a real kernel: filesystem rights and network, judged by the child's own result.

Skips cleanly when the kernel has no Landlock. The jail is the real ``python -m docket.jail``
entry run in a subprocess; nothing is stubbed. See specs/functional/security-gates.spec.md item 10.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.sandbox import landlock

SUBJECT = "docket.sandbox.jail"

pytestmark = pytest.mark.skipif(not landlock.landlock_available(), reason="Landlock not available")


def _env(rw: Path) -> dict[str, str]:
    """TMPDIR points into the root so the shared /tmp, where pytest lives, is not granted."""
    return {**os.environ, "TMPDIR": str(rw)}


def _jail(rw: Path, net: str, code: str, *extra: str) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        "-m",
        "docket.sandbox.jail",
        "--rw",
        str(rw),
        *extra,
        "--net",
        net,
        "--",
    ]
    argv += ["python3", "-c", code]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=rw, env=_env(rw))


@pytest.fixture
def listener() -> Iterator[int]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                server.accept()[0].close()
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    server.close()


def test_a_write_inside_the_root_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    done = _jail(root, "none", f"open({str(root / 'ok.txt')!r}, 'w').write('x'); print('wrote')")
    assert (done.returncode, done.stdout.strip()) == (0, "wrote"), done.stderr
    assert (root / "ok.txt").read_text() == "x"


def test_a_write_outside_the_root_is_denied(tmp_path: Path) -> None:
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    done = _jail(root, "none", f"open({str(other / 'no.txt')!r}, 'w')")
    assert done.returncode != 0
    assert "PermissionError" in done.stderr
    assert not (other / "no.txt").exists()


def test_a_file_outside_every_read_root_is_unreadable(tmp_path: Path) -> None:
    root, home = tmp_path / "root", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    secret = home / "secret.txt"
    secret.write_text("hunter2")
    done = _jail(root, "none", f"print(open({str(secret)!r}).read())")
    assert done.returncode != 0
    assert "PermissionError" in done.stderr
    assert "hunter2" not in done.stdout


def test_network_none_blocks_a_tcp_connect(tmp_path: Path, listener: int) -> None:
    code = f"import socket; socket.create_connection(('127.0.0.1', {listener}), timeout=5)"
    done = _jail(tmp_path, "none", code)
    assert done.returncode != 0
    assert "PermissionError" in done.stderr or "Operation not permitted" in done.stderr


def test_network_open_connects(tmp_path: Path, listener: int) -> None:
    code = (
        f"import socket; socket.create_connection(('127.0.0.1', {listener}), timeout=5); "
        "print('connected')"
    )
    done = _jail(tmp_path, "open", code)
    assert (done.returncode, done.stdout.strip()) == (0, "connected"), done.stderr


def test_the_argv_builder_output_runs_the_command_in_the_jail(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    argv = landlock.landlock_argv((root,), "echo hi > in.txt; echo no > ../out.txt", network=False)
    done = subprocess.run(
        argv, capture_output=True, text=True, timeout=60, cwd=root, env=_env(root)
    )
    assert (root / "in.txt").read_text() == "hi\n"
    assert not (tmp_path / "out.txt").exists()
    assert done.returncode != 0


def test_run_bash_reports_and_applies_the_landlock_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docket.agent.tools.builtins import toolbox

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
    out = toolbox.run_bash(
        (root,),
        "echo hi > in.txt; echo no > ../out.txt",
        env={"TMPDIR": str(root)},
        sandbox="auto",
    )
    assert "[sandbox: landlock]" in out.error
    assert (root / "in.txt").exists()
    assert not (tmp_path / "out.txt").exists()


def test_a_file_outside_the_grants_cannot_run_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 126 in a jail names the grant that fixes it; with the grant the same call runs."""
    from docket.agent.tools.builtins import toolbox

    root, tools = tmp_path / "root", tmp_path / "tools"
    root.mkdir()
    tools.mkdir()
    script = tools / "tool.sh"
    script.write_text("#!/bin/sh\necho ran\n")
    script.chmod(0o755)
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
    env = {"TMPDIR": str(root)}
    denied = toolbox.run_bash((root,), str(script), env=env, sandbox="auto")
    assert denied.error.startswith("command exited 126; the jail could not execute it")
    assert "docket setup sandbox read add" in denied.error
    granted = toolbox.run_bash((root,), str(script), env=env, sandbox="auto", read_only=(tools,))
    assert granted.ok and granted.content.startswith("ran")
