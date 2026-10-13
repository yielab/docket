"""The escape matrix: what a jailed command cannot do, on every backend this host has.

Every negative row asserts three things: a marker the jailed command wrote proves it ran, the
effect is absent after it, and the same attempt without the jail (or with the network open) has
the effect, so a row cannot pass because the command was missing or the path was unreachable
anyway. Nothing the rows touch sits under the temp dir, which the Landlock and Seatbelt jails
grant. See specs/functional/security-gates.spec.md, Validation.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import pod_provisioning as _pp
from docket.edges.adapters import system

SUBJECT = "docket.jail"

SECRET = "ESCAPE-MATRIX-SECRET-7f3a"
SEED_KEY = "ESCAPE_MATRIX_PARENT_SEED"
SEED_VALUE = "parent-environ-seed-91c2"
_CHECKOUT = Path(__file__).resolve().parents[2]


def _git_image_or_skip() -> str:
    tag = "docket-test-sbx"
    build = subprocess.run(
        ["docker", "build", "-q", "-t", tag, "-"],
        input="FROM alpine:3.20\nRUN apk add --no-cache git\n",
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build the git test image: {build.stderr.strip()[-200:]}")
    return tag


@pytest.fixture(
    params=[
        pytest.param(
            "landlock",
            marks=pytest.mark.skipif(
                not system.landlock_available(), reason="landlock is not available on this host"
            ),
        ),
        pytest.param(
            "docker",
            marks=pytest.mark.skipif(
                not system.docker_daemon_reachable(), reason="no docker daemon on this host"
            ),
        ),
        pytest.param(
            "seatbelt",
            marks=pytest.mark.skipif(
                not system.seatbelt_available(), reason="seatbelt is not available on this host"
            ),
        ),
    ]
)
def backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    name: str = request.param
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", name)
    if name == "docker":
        monkeypatch.setattr(_cfg, "SANDBOX_DOCKER_IMAGE", _git_image_or_skip())
    return name


@pytest.fixture
def arena(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A scratch directory outside every temp dir, so no grant covers it by accident."""
    base = _CHECKOUT / f".escape-matrix-{uuid.uuid4().hex[:10]}"
    base.mkdir()
    temps = {os.path.realpath(p) for p in (system.tempfile.gettempdir(), "/tmp", "/var/tmp")}
    real = os.path.realpath(base)
    if any(real == t or real.startswith(t + os.sep) for t in temps):
        shutil.rmtree(base)
        pytest.fail(f"the arena {real} is under a granted temp dir; rows would prove nothing")
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", base / "projects")
    try:
        yield base.resolve()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


_WRAPPER = (
    "import json, subprocess, sys\n"
    "env = json.loads(sys.argv[2])\n"
    "sys.exit(subprocess.run(json.loads(sys.argv[1]), env=env).returncode)\n"
)


def _run(
    backend: str,
    root: Path,
    command: str,
    *,
    jailed: bool = True,
    network: bool = True,
    extra_rw: tuple[Path, ...] = (),
    timeout: int = 90,
    expect_ran: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run *command* once, through ``system.jail_launch`` (the production builder) when *jailed*,
    under a wrapper parent that carries ``SEED_KEY`` in its environment. A marker written first
    proves the command ran; the call fails when it did not."""
    marker = root / f".ran-{uuid.uuid4().hex[:8]}"
    body = f"touch {marker}; {command}"
    if jailed:
        launch = system.jail_launch(
            (root,),
            body,
            backend,
            network=network,
            extra_rw=extra_rw,  # type: ignore[arg-type]
        )
        argv, env = launch.argv, launch.env
    else:
        argv, env = ["/bin/sh", "-c", body], dict(os.environ)
    parent_env = {**os.environ, SEED_KEY: SEED_VALUE}
    done = subprocess.run(
        [sys.executable, "-c", _WRAPPER, json.dumps(argv), json.dumps(env)],
        env=parent_env,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if expect_ran:
        assert marker.exists(), f"never ran (jailed={jailed}): {done.stderr.strip()[-300:]}"
        marker.unlink()
    return done


@pytest.fixture
def work(arena: Path) -> Path:
    root = arena / "work"
    root.mkdir()
    return root


@dataclass(frozen=True)
class TaskTree:
    main: Path
    wt: Path
    common: Path
    gitdir: Path
    task: dict[str, Any]


@pytest.fixture
def task_tree(arena: Path) -> TaskTree:
    """A repository and a task worktree made by docket's own provisioning, outside the temp dir."""
    main = arena / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "a.txt").write_text("a\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "init")
    record, reason = _pp.provision_task_worktree("proj-implementer-1", "proj", "t1", str(main))
    assert record, reason
    wt = Path(record["dir"]).resolve()
    common = Path(_git(wt, "rev-parse", "--git-common-dir"))
    common = (wt / common).resolve() if not common.is_absolute() else common.resolve()
    gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir")).resolve()
    return TaskTree(main, wt, common, gitdir, {"id": "t1", "worktree": record})


# -- positive rows: the jail is on, and git still works inside it ------------------------------


def test_a_write_inside_the_root_succeeds_and_the_command_ran(backend: str, work: Path) -> None:
    done = _run(backend, work, "echo inside > inside.txt")
    assert done.returncode == 0, done.stderr
    assert (work / "inside.txt").read_text().strip() == "inside"


def test_a_commit_inside_the_jailed_task_worktree_succeeds(
    backend: str, task_tree: TaskTree
) -> None:
    wt = task_tree.wt
    done = _run(
        backend,
        wt,
        "echo x > f.txt && git add f.txt && git commit -q -m jailed-commit && "
        "git branch side && git log -1 --format=%s",
    )
    assert done.returncode == 0, done.stderr
    assert "jailed-commit" in _git(wt, "log", "--format=%s", "-1")
    assert _git(wt, "rev-parse", "--verify", "side")


# -- negative rows ------------------------------------------------------------------------------


def test_a_seeded_secret_outside_the_roots_is_unreadable(backend: str, arena: Path) -> None:
    home = arena / "fakehome"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id").write_text(SECRET)
    root = arena / "work"
    root.mkdir()
    attack = f"cat {home}/.ssh/id"
    control = _run(backend, root, attack, jailed=False)
    assert SECRET in control.stdout
    done = _run(backend, root, attack)
    assert SECRET not in done.stdout + done.stderr
    assert done.returncode != 0


def test_a_write_outside_the_roots_is_refused(backend: str, arena: Path) -> None:
    root = arena / "work"
    root.mkdir()
    target = arena / "elsewhere" / "planted.txt"
    target.parent.mkdir()
    attack = f"mkdir -p {target.parent}; echo planted > {target}"
    control = _run(backend, root, attack, jailed=False)
    assert control.returncode == 0 and target.exists()
    target.unlink()
    done = _run(backend, root, attack)
    assert not target.exists()
    assert done.returncode != 0


def test_a_hook_cannot_be_planted_in_the_common_git_dir(backend: str, task_tree: TaskTree) -> None:
    wt, hook = task_tree.wt, task_tree.common / "hooks" / "pre-commit"
    attack = f"printf '#!/bin/sh\\ntouch {wt}/hook-ran\\n' > {hook}"
    done = _run(backend, wt, attack)
    assert not hook.exists(), "the jail planted a hook the operator's next commit would run"
    assert done.returncode != 0
    assert _run(backend, wt, attack, jailed=False).returncode == 0 and hook.exists()


def test_the_common_git_config_cannot_be_rewritten(backend: str, task_tree: TaskTree) -> None:
    wt, config = task_tree.wt, task_tree.common / "config"
    before = config.read_text()
    attack = f"printf '[core]\\n\\tfsmonitor = /bin/true\\n' >> {config}"
    done = _run(backend, wt, attack)
    assert config.read_text() == before, "the jail rewrote the shared git config"
    assert done.returncode != 0
    _run(backend, wt, attack, jailed=False)
    assert config.read_text() != before


def test_a_worktree_config_cannot_make_host_git_execute_code(
    backend: str, task_tree: TaskTree, arena: Path
) -> None:
    wt, gitdir = task_tree.wt, task_tree.gitdir
    ran = arena / "worktree-config-ran"
    script = wt / "fsmon.sh"
    script.write_text(f"#!/bin/sh\ntouch {ran}\n")
    script.chmod(0o755)
    _git(wt, "config", "extensions.worktreeConfig", "true")
    attack = f"printf '[core]\\n\\tfsmonitor = {script}\\n' > {gitdir}/config.worktree"
    _run(backend, wt, attack)
    task = task_tree.task
    _dispatch._task_worktree_dir(task)
    _dispatch._implementer_diff_probe("proj-implementer-1", "implementer", task)
    assert not ran.exists(), "host git ran a core.fsmonitor the jail wrote into config.worktree"
    (gitdir / "config.worktree").write_text(f"[core]\n\tfsmonitor = {script}\n")
    subprocess.run(["git", "-C", str(wt), "status"], capture_output=True, timeout=30)
    assert ran.exists(), "control: untrusted host git must run the planted fsmonitor"


def test_a_rewritten_dot_git_file_never_makes_dispatch_execute_anything(
    backend: str, task_tree: TaskTree, arena: Path
) -> None:
    wt = task_tree.wt
    ran = arena / "dotgit-ran"
    evil, script = wt / ".evil.git", wt / ".evil.sh"
    attack = (
        f"git init -q --bare {evil} && git -C {evil} config core.bare false && "
        f"printf '#!/bin/sh\\ntouch {ran}\\n' > {script} && chmod +x {script} && "
        f"printf '[core]\\n\\tfsmonitor = {script}\\n' >> {evil}/config && "
        f"printf 'gitdir: {evil}\\n' > {wt}/.git"
    )
    task = task_tree.task
    _dispatch._task_worktree_dir(task)
    _run(backend, wt, attack)
    dotgit = (wt / ".git").read_text()
    rewritten = str(evil) in dotgit
    if backend == "docker" or backend == "seatbelt":
        assert not rewritten, "the .git pointer file must be read-only in this backend"
    _dispatch._task_worktree_dir(task)
    _files, _ref, evidence = _dispatch._implementer_diff_probe(
        "proj-implementer-1", "implementer", task
    )
    assert not ran.exists(), "dispatch's host-side git executed what the jail wrote"
    assert evidence is not None
    assert [str(p) for p in system.git_dirs(wt)] == [
        str(task_tree.gitdir),
        str(task_tree.common),
    ], "the next jail would mount the agent's gitdir"
    if rewritten:
        subprocess.run(["git", "-C", str(wt), "status"], capture_output=True, timeout=30)
        assert ran.exists(), "control: an untrusting git must run the planted fsmonitor"


def _serve(host: str) -> tuple[socket.socket, list[bytes]]:
    server = socket.socket()
    server.bind((host, 0))
    server.listen(4)
    server.settimeout(10)
    got: list[bytes] = []

    def accept() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except (OSError, TimeoutError):
                return
            with conn:
                conn.settimeout(2)
                with contextlib.suppress(OSError):
                    got.append(conn.recv(64))

    threading.Thread(target=accept, daemon=True).start()
    return server, got


def _listener_address(backend: str) -> tuple[str, str]:
    """``(bind address, address the jailed command dials)``."""
    if backend != "docker":
        return "127.0.0.1", "127.0.0.1"
    gateway = subprocess.run(
        ["docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not gateway:
        pytest.skip("cannot find the docker bridge gateway to dial the host listener")
    return "0.0.0.0", gateway


def test_a_connect_is_refused_under_network_none(backend: str, work: Path) -> None:
    bind, dial = _listener_address(backend)
    server, got = _serve(bind)
    port = server.getsockname()[1]
    if backend == "docker":
        attack = f"printf hello | nc -w 2 {dial} {port}"
    else:
        attack = (
            f"python3 -c \"import socket; s = socket.create_connection(('{dial}', {port}), 2); "
            "s.sendall(b'hello')\""
        )
    try:
        _run(backend, work, attack, network=True)
        for _ in range(50):
            if got:
                break
            threading.Event().wait(0.1)
        assert got == [b"hello"], "control: the same command must reach the listener when open"
        got.clear()
        done = _run(backend, work, attack, network=False)
        threading.Event().wait(1)
        assert got == [], "a jailed command reached a host listener under network none"
        assert done.returncode != 0
    finally:
        server.close()


@pytest.mark.skipif(sys.platform != "linux", reason="/proc is Linux-only")
def test_the_parent_process_environment_is_unreadable(backend: str, work: Path) -> None:
    attack = "cat /proc/[0-9]*/environ" if backend == "docker" else "cat /proc/$PPID/environ"
    control = _run(backend, work, attack, jailed=False)
    if backend != "docker":
        assert SEED_VALUE in control.stdout
    done = _run(backend, work, attack)
    assert SEED_VALUE not in done.stdout + done.stderr


def test_a_verify_command_cannot_write_outside_the_worktree(
    backend: str, task_tree: TaskTree, arena: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wt = task_tree.wt
    target = arena / "verify-escape.txt"
    jail = system.JailPolicy(network=True)
    monkeypatch.setattr(_dispatch._dr, "resolve_command_jail", lambda project, label: (jail, None))
    cmd = f"touch inside-verify && echo escaped > {target}"
    passed, output = _dispatch._run_in_envelope("proj", "verify", cmd, str(wt), 60)
    assert (wt / "inside-verify").exists(), f"the verify command never ran: {output}"
    assert not target.exists(), "a verifyCmd wrote outside its worktree"
    assert passed is False
    monkeypatch.setattr(_dispatch._dr, "resolve_command_jail", lambda project, label: (None, None))
    host_passed, _ = _dispatch._run_in_envelope("proj", "verify", cmd, str(wt), 60)
    assert host_passed is True and target.exists()


def test_a_rewritten_commondir_never_makes_dispatch_execute_anything(
    backend: str, task_tree: TaskTree, arena: Path
) -> None:
    wt, gitdir = task_tree.wt, task_tree.gitdir
    ran = arena / "commondir-ran"
    evil, script = wt / ".evil-common", wt / ".evil-common.sh"
    attack = (
        f"git init -q --bare {evil} && git -C {evil} config core.bare false && "
        f"printf '#!/bin/sh\\ntouch {ran}\\n' > {script} && chmod +x {script} && "
        f"printf '[core]\\n\\tfsmonitor = {script}\\n' >> {evil}/config && "
        f"printf '{evil}\\n' > {gitdir}/commondir"
    )
    _dispatch._task_worktree_dir(task_tree.task)
    _run(backend, wt, attack)
    rewritten = (gitdir / "commondir").read_text().strip() == str(evil)
    _dispatch._implementer_diff_probe("proj-implementer-1", "implementer", task_tree.task)
    assert not ran.exists(), "dispatch's host-side git followed a commondir the jail rewrote"
    if rewritten:
        subprocess.run(["git", "-C", str(wt), "status"], capture_output=True, timeout=30)
        assert ran.exists(), "control: an untrusting git must run the planted fsmonitor"


def test_a_main_checkout_root_is_refused_on_landlock_and_guarded_elsewhere(
    backend: str, task_tree: TaskTree
) -> None:
    main = task_tree.main
    hook = main / ".git" / "hooks" / "pre-commit"
    config = main / ".git" / "config"
    before = config.read_text()
    attack = f"echo x > {hook}; echo '[core]' >> {config}"
    if backend == "landlock":
        done = _run(backend, main, attack, expect_ran=False)
        assert done.returncode == 125 and ".git directory" in done.stderr
        assert not list(main.glob(".ran-*")), "the refused jail ran the command"
        assert not hook.exists() and config.read_text() == before
        return
    _run(backend, main, attack)
    assert not hook.exists() and config.read_text() == before
    commit = _run(
        backend, main, "echo y > y.txt && git add y.txt && git commit -q -m from-main-jail"
    )
    assert commit.returncode == 0, commit.stderr
