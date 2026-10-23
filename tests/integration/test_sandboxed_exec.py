"""Sandboxed execution for bash-class tools.

The tool-call gate decides whether a command may run at all; this decides what it can reach once
it does -- the gate is not a sandbox. Pins, in order of importance: detection is real, not assumed
(`system.sandbox_availability()` never claims a backend that is not actually usable); `sandbox="off"`
(the default) is the original, unchanged `run_bash`; reporting is honest, always saying what
actually happened including "none, because X"; and when a real backend is present the jail is
real -- additive to `resolve_within`, never a replacement, and a timed-out sandboxed command
leaves no orphan. Tests needing a real backend skip with an explicit reason on a host with
neither -- the skip is the contract in action, not a coverage gap. See
specs/functional/security-gates.spec.md Requirements 1-6.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import pods as _support_pods
from tests.support.git import git_2 as _git
from tests.support.git import pgrep_count as _pgrep_count

from docket.agent.llm import ToolCall
from docket.agent.tools.builtin_tools import builtin_registry
from docket.agent.tools.builtins import toolbox
from docket.agent.tools.registry import ToolContext, dispatch_tool
from docket.kernel.home import current_home, use_home
from docket.kernel.ports import jail as _jail_port
from docket.sandbox import docker as sandbox_docker
from docket.sandbox import landlock as sandbox_landlock
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet

_isolate_gates = _support_home.isolate_gates
workspace = _support_pods.workspace

SUBJECT = "docket.agent.tools.registry"

DOCKER_UP = sandbox_docker.docker_daemon_reachable()
LANDLOCK_UP = sandbox_landlock.landlock_available()

needs_docker = pytest.mark.skipif(
    not DOCKER_UP, reason="docker not installed or its daemon is not reachable on this host"
)
needs_landlock = pytest.mark.skipif(
    not LANDLOCK_UP, reason="landlock is not available on this host"
)


# ── detection: real, not assumed ─────────────────────────────────────────────


class TestSandboxAvailabilityDetection:
    def test_env_override_wins_over_real_probes(
        self, monkeypatch: pytest.MonkeyPatch, bind_launcher: Callable[..., Launcher]
    ) -> None:
        bind_launcher(landlock=True, docker=True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        availability = _jail_port.sandbox_availability("docker")
        assert availability.backend == "none"
        # The override forces the *choice*; it does not fake the underlying probes.
        assert availability.docker is True
        assert availability.landlock is True

    def test_landlock_is_used_when_docker_is_also_up_and_not_chosen(
        self, monkeypatch: pytest.MonkeyPatch, bind_launcher: Callable[..., Launcher]
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        bind_launcher(landlock=True, docker=True)
        assert _jail_port.sandbox_availability("auto").backend == "landlock"

    def test_docker_is_used_when_chosen(
        self, monkeypatch: pytest.MonkeyPatch, bind_launcher: Callable[..., Launcher]
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        bind_launcher(landlock=True, docker=True)
        assert _jail_port.sandbox_availability("docker").backend == "docker"

    def test_none_when_nothing_usable_and_docker_is_not_probed_unless_chosen(
        self, monkeypatch: pytest.MonkeyPatch, bind_launcher: Callable[..., Launcher]
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        bind_launcher(landlock=False, seatbelt=False, docker=True)
        availability = _jail_port.sandbox_availability("auto")
        assert availability.backend == "none"
        assert availability.docker is False

    def test_docker_binary_present_but_daemon_down_is_still_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The binary-only check (`docker_available`) is not the bar —
        `docker_daemon_reachable` must actually talk to the daemon."""
        monkeypatch.setattr(sandbox_docker, "docker_available", lambda: True)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, returncode=1),
        )
        assert sandbox_docker.docker_daemon_reachable() is False


# ── argv construction: mechanism, no execution ──────────────────────────────


class TestArgvShape:
    def test_landlock_grants_each_root_read_write(self, workspace: Path, tmp_path: Path) -> None:
        second = tmp_path / "codebase"
        second.mkdir()
        argv = sandbox_landlock.landlock_argv((workspace, second), "echo hi")
        rw = [argv[i + 1] for i, a in enumerate(argv) if a == "--rw"]
        assert rw == [str(workspace.resolve()), str(second.resolve())]
        assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]

    def test_a_git_worktree_root_mounts_its_git_dirs_without_hooks_or_config_writable(
        self, tmp_path: Path
    ) -> None:
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        _git(tmp_path, "init", "-q", str(main))
        _git(main, "commit", "-q", "--allow-empty", "-m", "init")
        _git(main, "worktree", "add", "-q", str(wt))
        gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir")).resolve()
        common = (main / ".git").resolve()
        assert gitdir != common
        landlock = sandbox_landlock.landlock_argv((wt,), "true")
        grants = [landlock[i + 1] for i, a in enumerate(landlock) if a == "--rw"]
        assert grants == [
            str(wt.resolve()),
            str(common / "objects"),
            str(gitdir),
        ]
        assert [landlock[i + 1] for i, a in enumerate(landlock) if a == "--ro"] == [str(common)]
        assert str(common) not in grants and str(common / "hooks") not in grants
        docker = sandbox_docker.docker_run_argv("c", (wt,), "true", None)
        mounts = [docker[i + 1] for i, a in enumerate(docker) if a == "-v"]
        assert f"{gitdir}:{gitdir}" in mounts and f"{common}:{common}" in mounts

    def test_git_hooks_and_config_are_overlaid_read_only(self, tmp_path: Path) -> None:
        main = tmp_path / "main"
        wt = tmp_path / "wt"
        _git(tmp_path, "init", "-q", str(main))
        _git(main, "commit", "-q", "--allow-empty", "-m", "init")
        _git(main, "worktree", "add", "-q", str(wt))
        common = (main / ".git").resolve()
        docker = sandbox_docker.docker_run_argv("c", (wt,), "true", None)
        ro = [
            docker[i + 1][: -len(":ro")].split(":")[0]
            for i, a in enumerate(docker)
            if a == "-v" and docker[i + 1].endswith(":ro")
        ]
        admin = common / "worktrees" / "wt"
        assert ro == [
            str(common / "hooks"),
            str(common / "config"),
            str(common / "info" / "attributes"),
            str(wt.resolve() / ".git"),
            str(admin / "gitdir"),
            str(admin / "commondir"),
            str(common / "refs"),
            str(common / "logs" / "refs"),
            str(common / "packed-refs"),
        ]
        mounts = [i for i, a in enumerate(docker) if a == "-v"]
        rw_last = max(i for i in mounts if not docker[i + 1].endswith(":ro"))
        ro_first = min(i for i in mounts if docker[i + 1].endswith(":ro"))
        assert ro_first > rw_last
        assert f"{common}/hooks:{common}/hooks:ro" in docker
        assert f"{wt.resolve()}/.git:{wt.resolve()}/.git:ro" in docker

    def test_a_root_outside_any_repo_gains_no_extra_mounts(self, workspace: Path) -> None:
        argv = sandbox_landlock.landlock_argv((workspace,), "true")
        assert argv.count("--rw") == 1

    def test_docker_run_mounts_each_root_and_runs_as_the_caller(self, workspace: Path) -> None:
        argv = sandbox_docker.docker_run_argv("my-container", (workspace,), "echo hi", None)
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--name" in argv and "my-container" in argv
        assert f"{os.getuid()}:{os.getgid()}" in argv
        resolved = str(workspace.resolve())
        assert f"{resolved}:{resolved}" in argv
        assert argv[-4:] == [current_home().sandbox_docker_image, "sh", "-c", "echo hi"]

    def test_docker_run_forwards_only_the_explicit_env_not_the_host_env(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_HOST_SECRET_SHOULD_NOT_LEAK", "leak-me-not")
        argv = sandbox_docker.docker_run_argv(
            "c", (workspace,), "echo hi", {"DOCKET_SCRATCH_DIR": "/x"}
        )
        assert "-e" in argv
        assert "DOCKET_SCRATCH_DIR=/x" in argv
        assert not any("DOCKET_HOST_SECRET_SHOULD_NOT_LEAK" in part for part in argv)

    def test_docker_kill_never_raises_even_when_docker_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("no docker")

        monkeypatch.setattr(subprocess, "run", _raise)
        sandbox_docker.docker_kill("whatever")  # must not raise


# ── run_bash(sandbox="off"): the default is the original function ──────────


class TestSandboxOffIsUnchanged:
    def test_default_context_sandbox_is_off(self) -> None:
        assert ToolContext().sandbox == "off"

    def test_off_mode_matches_the_pre_p19_9_exact_output(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "printf %s hi", env={"X": "1"})
        assert out.ok and out.content == "hi"  # no marker, no suffix — byte for byte

    def test_off_mode_never_reports_a_sandbox_tag_even_when_both_backends_are_real(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        bind_launcher(docker=True)
        out = toolbox.run_bash((workspace,), "echo hi")  # sandbox left at the "off" default
        assert out.content == "hi"
        assert "sandbox" not in out.content


# ── honest reporting (deterministic — backends are mocked, not real) ───────


class TestHonestReportingIsDeterministic:
    def test_auto_with_no_backend_runs_nothing_and_says_why(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        """The gate allowed the command on the promise of a jail, so no jail means no run."""
        bind_launcher(landlock=False, seatbelt=False, docker=False)
        out = toolbox.run_bash((workspace,), "touch ran", sandbox="auto")
        assert not out.ok and not (workspace / "ran").exists()
        assert out.error.startswith("not run: no sandbox backend is usable")
        native = "seatbelt" if sys.platform == "darwin" else "landlock"
        assert (
            f"[sandbox: none ({native} unavailable, docker not chosen or unreachable)]" in out.error
        )

    def test_auto_forced_to_none_when_both_are_actually_available_says_so_too(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
    ) -> None:
        """A silent 'none' that looks identical whether or not a jail was
        possible is exactly the failure this card exists to prevent."""
        bind_launcher(landlock=True, docker=True)
        _fleet.set_sandbox_backend("docker")
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        out = toolbox.run_bash((workspace,), "echo hi", sandbox="auto")
        assert not out.ok
        assert "[sandbox: none (forced off via DOCKET_SANDBOX_BACKEND)]" in out.error

    def test_a_jail_that_fails_to_start_is_a_reported_failure_not_a_silent_fallback(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If `sandbox="auto"` resolves to a real backend but the subprocess launch fails, the
        command MUST NOT run unsandboxed instead -- that silent substitution is the failure mode
        this test guards against."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

        def _raise(*_args: object, **_kwargs: object) -> subprocess.Popen[str]:
            raise OSError("landlock vanished mid-flight")

        monkeypatch.setattr(subprocess, "Popen", _raise)
        out = toolbox.run_bash((workspace,), "echo should-never-run", sandbox="auto")
        assert not out.ok
        assert "sandbox (landlock) failed to start" in out.error


# ── the chokepoint still owns this: dispatch_tool wiring ────────────────────


class TestChokepointWiring:
    def _call(self, arguments: str) -> ToolCall:
        return ToolCall(id="c1", name="bash", arguments=arguments)

    def test_bash_tool_forwards_ctx_sandbox_through_the_real_chokepoint(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not just a direct toolbox.run_bash call — the field has to survive
        ToolContext -> the registered handler -> dispatch_tool -> the
        model-visible result."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        ctx = ToolContext(roots=(workspace,), sandbox="auto")
        # `printf` (not `echo`) — it is on governance.security's SAFE_BINS
        # allowlist, so the command classifier allows it outright and this
        # test is exercising the sandbox wiring, not the tool-call gate.
        res = dispatch_tool(self._call('{"command": "printf hi"}'), ctx, builtin_registry())
        assert not res.ok
        assert "not run: no sandbox backend is usable [sandbox: none" in res.error

    def test_default_context_through_the_chokepoint_reports_nothing(self, workspace: Path) -> None:
        ctx = ToolContext(roots=(workspace,))  # sandbox defaults to "off"
        res = dispatch_tool(self._call('{"command": "printf hi"}'), ctx, builtin_registry())
        assert res.content == "hi"

    def test_file_tool_containment_is_unaffected_by_ctx_sandbox(self, workspace: Path) -> None:
        """resolve_within's boundary is additional to the exec jail, never
        replaced by it — a `write` call outside the roots is refused exactly
        as before, regardless of what ctx.sandbox is set to."""
        ctx = ToolContext(roots=(workspace,), sandbox="auto")
        res = dispatch_tool(
            ToolCall(id="c1", name="write", arguments='{"path": "/etc/passwd", "content": "x"}'),
            ctx,
            builtin_registry(),
        )
        assert not res.ok
        assert "outside the allowed roots" in res.error


# ── real backend: landlock (skipped, with an explicit reason, if unavailable) ──


@needs_landlock
class TestRealLandlockJail:
    def test_blocks_writes_outside_the_allowed_roots(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`resolve_within` never inspects a bash command's shell text, so only the jail stops
        this. The canary sits outside every root and outside the temp dir the jail grants."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        canary = Path(__file__).parent / f".p19-9-canary-{uuid.uuid4().hex[:8]}"
        try:
            out = toolbox.run_bash(
                (workspace,), f"echo breached > {canary} 2>&1; echo rc=$?", sandbox="auto"
            )
            assert out.ok
            assert "rc=0" not in out.content
            assert not canary.exists()
        finally:
            canary.unlink(missing_ok=True)

    def test_still_allows_writes_inside_the_allowed_roots(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The jail must not be so wide it breaks legitimate work either."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        out = toolbox.run_bash(
            (workspace,), "echo inside > local.txt; cat local.txt", sandbox="auto"
        )
        assert out.ok and "inside" in out.content
        assert (workspace / "local.txt").read_text().strip() == "inside"

    def test_timeout_leaves_no_orphaned_children(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A command that forks children and hangs is the normal case, not
        the exotic one (see toolbox.run_bash's docstring) — this must hold
        under landlock the same way it already does unsandboxed."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        marker = f"p19-9-landlock-marker-{uuid.uuid4().hex[:8]}"
        out = toolbox.run_bash(
            (workspace,), f"echo {marker}; sleep 20 & sleep 20 & wait", timeout=1, sandbox="auto"
        )
        assert not out.ok and "timed out" in out.error
        time.sleep(1)
        assert _pgrep_count(marker) == 0

    def test_minimizes_env_a_host_secret_does_not_leak_in(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        monkeypatch.setenv("DOCKET_TEST_HOST_SECRET", "top-secret")
        out = toolbox.run_bash((workspace,), "echo VAL=$DOCKET_TEST_HOST_SECRET", sandbox="auto")
        assert "VAL=\n" in out.content or out.content.startswith("VAL=\n\n[sandbox")

    def test_explicit_ctx_env_still_reaches_the_jailed_command(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
        out = toolbox.run_bash(
            (workspace,),
            "echo VAL=$DOCKET_SCRATCH_DIR",
            env={"DOCKET_SCRATCH_DIR": "/scratch/demo"},
            sandbox="auto",
        )
        assert "VAL=/scratch/demo" in out.content


# ── real backend: docker (skipped, with an explicit reason, if unavailable) ─


@needs_docker
class TestRealDockerJail:
    def test_files_created_are_owned_by_the_calling_user_not_root(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        out = toolbox.run_bash((workspace,), "echo hi > owned.txt", sandbox="auto")
        assert out.ok
        stat = (workspace / "owned.txt").stat()
        assert stat.st_uid == os.getuid()

    def test_only_the_explicit_env_reaches_the_container(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        monkeypatch.setenv("DOCKET_TEST_HOST_SECRET", "top-secret")
        out = toolbox.run_bash(
            (workspace,),
            "echo VAL=$DOCKET_TEST_HOST_SECRET SCRATCH=$DOCKET_SCRATCH_DIR",
            env={"DOCKET_SCRATCH_DIR": "/scratch/demo"},
            sandbox="auto",
        )
        assert "VAL= " in out.content or "VAL=\n" in out.content
        assert "SCRATCH=/scratch/demo" in out.content

    def test_timeout_kills_the_container_not_just_the_cli_wrapper(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`docker run`'s CLI process is a thin client the daemon runs the real container under,
        so killing only its process group does not stop the container (`system.docker_kill`).
        Verified red by removing the `docker_kill` call: the container stayed up; reverted, not."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        killed: list[str] = []
        real_kill = sandbox_docker.docker_kill

        def recording_kill(name: str) -> None:
            killed.append(name)
            real_kill(name)

        monkeypatch.setattr(sandbox_docker, "docker_kill", recording_kill)
        out = toolbox.run_bash((workspace,), "sleep 20", timeout=1, sandbox="auto")
        assert not out.ok and "timed out" in out.error
        assert killed
        deadline = time.monotonic() + 10
        while True:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name=^{killed[0]}$", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if not result.stdout.strip() or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        assert result.stdout.strip() == ""


class TestJailedCommit:
    @needs_docker
    def test_a_jailed_command_commits_in_a_linked_worktree_but_cannot_write_elsewhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            main = tmp_path / "main"
            wt = tmp_path / "wt"
            _git(tmp_path, "init", "-q", str(main))
            _git(main, "commit", "-q", "--allow-empty", "-m", "init")
            _git(main, "worktree", "add", "-q", "-b", "docket/pod/wt", str(wt))
            outside = tmp_path / "outside"
            outside.mkdir()
            ident = {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            }

            outcome = toolbox.run_bash(
                (wt,),
                "echo x > f && git add f && git commit -q -m jailed",
                env=ident,
                sandbox="auto",
            )
            assert outcome.ok, outcome.error or outcome.content
            assert "jailed" in _git(wt, "log", "--format=%s", "-1")

            denied = toolbox.run_bash((wt,), f"echo x > {outside}/leak", sandbox="auto")
            assert not denied.ok
            assert not (outside / "leak").exists()

    @needs_docker
    @pytest.mark.parametrize("source", ["environment", "global-config"])
    def test_a_jailed_commit_uses_the_operators_git_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str, source: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            home = tmp_path / "home"
            home.mkdir()
            monkeypatch.setenv("HOME", str(home))
            monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
            for var in ("AUTHOR", "COMMITTER"):
                monkeypatch.delenv(f"GIT_{var}_NAME", raising=False)
                monkeypatch.delenv(f"GIT_{var}_EMAIL", raising=False)
            if source == "environment":
                for var in ("AUTHOR", "COMMITTER"):
                    monkeypatch.setenv(f"GIT_{var}_NAME", "Op")
                    monkeypatch.setenv(f"GIT_{var}_EMAIL", "op@example.com")
            else:
                (home / ".gitconfig").write_text("[user]\n\tname = Op\n\temail = op@example.com\n")
            main = tmp_path / "main"
            wt = tmp_path / "wt"
            _git(tmp_path, "init", "-q", str(main))
            _git(
                main,
                "-c",
                "user.name=i",
                "-c",
                "user.email=i@i",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "i",
            )
            _git(main, "worktree", "add", "-q", "-b", "docket/pod/wt", str(wt))

            outcome = toolbox.run_bash(
                (wt,), "git commit -q --allow-empty -m jailed", sandbox="auto"
            )
            assert outcome.ok, outcome.error or outcome.content
            assert _git(wt, "log", "--format=%an <%ae>", "-1").strip() == "Op <op@example.com>"

    @needs_docker
    def test_the_jail_cannot_plant_a_hook_or_a_config_the_host_would_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            main = tmp_path / "main"
            wt = tmp_path / "wt"
            _git(tmp_path, "init", "-q", str(main))
            _git(main, "commit", "-q", "--allow-empty", "-m", "init")
            _git(main, "worktree", "add", "-q", "-b", "docket/pod/wt", str(wt))
            common = main / ".git"
            ident = {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            }

            commit = toolbox.run_bash(
                (wt,), "echo x > f && git add f && git commit -q -m ok", env=ident, sandbox="auto"
            )
            assert commit.ok, commit.error or commit.content

            hook = toolbox.run_bash((wt,), f"echo x > {common}/hooks/post-checkout", sandbox="auto")
            assert not hook.ok
            assert not (common / "hooks" / "post-checkout").exists()

            cfg = toolbox.run_bash((wt,), "git config core.hooksPath /tmp/x", sandbox="auto")
            assert not cfg.ok
            host = subprocess.run(
                ["git", "-C", str(main), "config", "--get", "core.hooksPath"],
                capture_output=True,
                text=True,
            )
            assert host.stdout.strip() == ""


def _super_with_submodule(tmp_path: Path) -> tuple[Path, Path]:
    """A super-repo with one submodule checked out; returns (super, submodule git dir)."""
    sub_src = tmp_path / "sub_src"
    _git(tmp_path, "init", "-q", str(sub_src))
    _git(sub_src, "commit", "-q", "--allow-empty", "-m", "sub")
    sup = tmp_path / "super"
    _git(tmp_path, "init", "-q", str(sup))
    _git(sup, "commit", "-q", "--allow-empty", "-m", "init")
    _git(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub_src), "sub")
    return sup, sup / ".git" / "modules" / "sub"


class TestGitMetadataTheHostLaterRuns:
    def test_mount_dirs_guard_submodules_the_git_file_and_the_worktree_admin_files(
        self, tmp_path: Path
    ) -> None:
        sup, subgit = _super_with_submodule(tmp_path)
        (sup / ".git" / "info").mkdir(exist_ok=True)
        (sup / ".git" / "info" / "attributes").write_text("* -diff\n")
        wt = tmp_path / "wt"
        _git(sup, "worktree", "add", "-q", str(wt))

        _, ro = sandbox_landlock._mount_dirs((sup,))
        for expected in (
            subgit / "hooks",
            subgit / "config",
            sup / ".git" / "info" / "attributes",
            sup / "sub" / ".git",
        ):
            assert str(expected) in ro, expected

        rw, ro_wt = sandbox_landlock._mount_dirs((wt,))
        admin = sup / ".git" / "worktrees" / "wt"
        for expected in (wt / ".git", admin / "gitdir", admin / "commondir"):
            assert str(expected) in ro_wt, expected
        assert str(admin) in rw and str(wt) in rw

    def test_a_submodule_git_dir_nested_two_deep_is_guarded(self, tmp_path: Path) -> None:
        sup, subgit = _super_with_submodule(tmp_path)
        deep = subgit / "modules" / "a" / "modules" / "b"
        (deep / "hooks").mkdir(parents=True)
        (deep / "HEAD").write_text("ref: refs/heads/main\n")
        (deep / "config").write_text("")
        _, ro = sandbox_landlock._mount_dirs((sup,))
        assert str(deep / "hooks") in ro and str(deep / "config") in ro

    @needs_docker
    def test_an_absent_hooks_dir_cannot_be_created_from_the_jail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            repo = tmp_path / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            shutil.rmtree(repo / ".git" / "hooks")

            plant = toolbox.run_bash(
                (repo,),
                "mkdir -p .git/hooks && printf '#!/bin/sh\\ntouch pwned' > .git/hooks/post-commit"
                " && echo 'x' > .git/info/attributes",
                sandbox="auto",
            )
            assert not plant.ok
            assert not (repo / ".git" / "hooks" / "post-commit").exists()
            assert (repo / ".git" / "info" / "attributes").read_text() == ""

    @needs_docker
    def test_the_jail_cannot_plant_a_submodule_hook_or_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            sup, subgit = _super_with_submodule(tmp_path)

            hook = toolbox.run_bash((sup,), f"echo x > {subgit}/hooks/post-commit", sandbox="auto")
            assert not hook.ok
            assert not (subgit / "hooks" / "post-commit").exists()

            cfg = toolbox.run_bash((sup,), "git -C sub config core.hooksPath /x", sandbox="auto")
            assert not cfg.ok
            host = subprocess.run(
                ["git", "-C", str(sup / "sub"), "config", "--get", "core.hooksPath"],
                capture_output=True,
                text=True,
            )
            assert host.stdout.strip() == ""

            before = (sup / "sub" / ".git").read_text()
            redirect = toolbox.run_bash(
                (sup,), "echo 'gitdir: /tmp/evil' > sub/.git", sandbox="auto"
            )
            assert not redirect.ok
            assert (sup / "sub" / ".git").read_text() == before

    @needs_docker
    def test_the_jail_cannot_repoint_a_linked_worktrees_git_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        with _use_docker(monkeypatch, docker_git_image):
            main = tmp_path / "main"
            wt = tmp_path / "wt"
            _git(tmp_path, "init", "-q", str(main))
            _git(main, "commit", "-q", "--allow-empty", "-m", "init")
            _git(main, "worktree", "add", "-q", "-b", "docket/pod/wt", str(wt))
            (main / ".git" / "info").mkdir(exist_ok=True)
            (main / ".git" / "info" / "attributes").write_text("* -diff\n")
            before = _git(wt, "rev-parse", "--absolute-git-dir")
            admin = main / ".git" / "worktrees" / "wt"
            admin_before = (admin / "gitdir").read_text()

            rewrite = toolbox.run_bash((wt,), f"echo 'gitdir: {wt}/evil' > .git", sandbox="auto")
            assert not rewrite.ok
            assert _git(wt, "rev-parse", "--absolute-git-dir") == before

            admin_write = toolbox.run_bash((wt,), f"echo /x > {admin}/gitdir", sandbox="auto")
            assert not admin_write.ok
            assert (admin / "gitdir").read_text() == admin_before

            attrs = toolbox.run_bash(
                (wt,), f"echo '* filter=evil' > {main}/.git/info/attributes", sandbox="auto"
            )
            assert not attrs.ok
            assert (main / ".git" / "info" / "attributes").read_text() == "* -diff\n"

            ident = {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            }
            commit = toolbox.run_bash(
                (wt,),
                "echo x > f && git add f && git commit -q -m still",
                env=ident,
                sandbox="auto",
            )
            assert commit.ok, commit.error or commit.content


@contextmanager
def _use_docker(monkeypatch: pytest.MonkeyPatch, image: str) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
    with use_home(dataclasses.replace(current_home(), sandbox_docker_image=image)):
        yield


@pytest.fixture(scope="session")
def docker_git_image() -> str:
    """A tiny image with git (alpine plus one package), built once per session; skips when the
    daemon is down or the build fails (it is the one place a test uses the network)."""
    if not DOCKER_UP:
        pytest.skip("docker not installed or its daemon is not reachable on this host")
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


@needs_docker
class TestDockerJailedCommit:
    def test_a_jailed_command_commits_in_a_linked_worktree_and_the_host_sees_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, docker_git_image: str
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        with use_home(dataclasses.replace(current_home(), sandbox_docker_image=docker_git_image)):
            main = tmp_path / "main"
            wt = tmp_path / "wt"
            _git(tmp_path, "init", "-q", str(main))
            _git(main, "commit", "-q", "--allow-empty", "-m", "init")
            _git(main, "worktree", "add", "-q", "-b", "docket/pod/wt", str(wt))

            outcome = toolbox.run_bash(
                (wt,),
                "echo x > f && git add f && "
                "git -c user.name=t -c user.email=t@t commit -q -m jailed-in-docker",
                sandbox="auto",
            )
            assert outcome.ok, outcome.error or outcome.content
            assert "jailed-in-docker" in _git(wt, "log", "--format=%s", "-1")
            assert (wt / "f").read_text().strip() == "x"
