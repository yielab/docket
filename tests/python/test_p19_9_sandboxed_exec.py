"""Sandboxed execution for bash-class tools.

The tool-call gate decides whether a command may run at all. This decides
what it can reach once it does — the gate is not a sandbox, and
`toolbox.run_bash`'s own docstring says so. Four things are pinned here, in
order of how much they matter:

1. **Detection is real, not assumed.** `system.sandbox_availability()` probes
   both backends and never claims one that is not actually usable — a docker
   binary with no reachable daemon, a bwrap binary a hardened kernel refuses
   to let build a namespace — is still "unavailable". Pure unit tests, no
   real docker/bwrap needed.
2. **`sandbox="off"` (the default) is the original function, unchanged.**
   `run_bash` never sandboxes unless asked, and never behaves differently —
   not even by a stray byte in its output — when nobody asked.
3. **Reporting is honest.** Asking for a jail (`sandbox="auto"`) always says
   what actually happened, including "none, because X" — a caller (or
   `docket doctor`, later) can always tell "sandboxing is configured" apart
   from "this specific command ran in one".
4. **When a real backend is present, the jail is real** — containment holds
   in *addition* to `resolve_within` (never instead of it), and a timed-out
   sandboxed command leaves no orphan: a process under bwrap, a container
   under docker. These tests are skipped, with an explicit reason, on a host
   with neither — the skip is the "detected, not assumed" contract in action,
   not a coverage gap.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core.llm import ToolCall
from docket.core.tools import ToolContext, builtin_registry, dispatch_tool
from docket.edges.adapters import system, toolbox

DOCKER_UP = system.docker_daemon_reachable()
BWRAP_UP = system.bwrap_available()

needs_docker = pytest.mark.skipif(
    not DOCKER_UP, reason="docker not installed or its daemon is not reachable on this host"
)
needs_bwrap = pytest.mark.skipif(
    not BWRAP_UP, reason="bwrap not installed, or this host disallows unprivileged user namespaces"
)


@pytest.fixture(autouse=True)
def _isolate_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same isolation test_p19_2_tool_registry.py uses: tests here call
    `dispatch_tool` directly, which consults `core/policy.py` and
    `core/approval.py` — point both at an ephemeral, empty directory so this
    file never reads a developer's real ``~/.openclaw/policies`` and never
    blocks for real on an approval nothing will ever grant.
    """
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "_policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "_approvals", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def _pgrep_count(marker: str) -> int:
    """Count host processes whose command line contains *marker* — the
    orphan check for the bwrap timeout tests. Not used for docker: a
    container's processes are not visible to a host-level `pgrep` at all,
    which is exactly why docker needs its own `docker ps`-based check.
    """
    result = subprocess.run(["pgrep", "-fc", marker], capture_output=True, text=True)
    return int((result.stdout or "0").strip() or "0")


# ── detection: real, not assumed ─────────────────────────────────────────────


class TestSandboxAvailabilityDetection:
    def test_env_override_wins_over_real_probes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(system, "bwrap_available", lambda: True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        availability = system.sandbox_availability()
        assert availability.backend == "none"
        # The override forces the *choice*; it does not fake the underlying probes.
        assert availability.docker is True
        assert availability.bwrap is True

    def test_docker_preferred_over_bwrap_when_both_usable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(system, "bwrap_available", lambda: True)
        assert system.sandbox_availability().backend == "docker"

    def test_bwrap_used_when_docker_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: False)
        monkeypatch.setattr(system, "bwrap_available", lambda: True)
        assert system.sandbox_availability().backend == "bwrap"

    def test_none_when_neither_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: False)
        monkeypatch.setattr(system, "bwrap_available", lambda: False)
        availability = system.sandbox_availability()
        assert availability.backend == "none"
        assert availability.docker is False
        assert availability.bwrap is False

    def test_docker_binary_present_but_daemon_down_is_still_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The binary-only check (`docker_available`) is not the bar —
        `docker_daemon_reachable` must actually talk to the daemon."""
        monkeypatch.setattr(system, "docker_available", lambda: True)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, returncode=1),
        )
        assert system.docker_daemon_reachable() is False

    def test_bwrap_binary_present_but_smoke_test_fails_is_still_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirrors the docker case: a kernel that refuses unprivileged user
        namespaces makes the *binary* present but the *capability* absent —
        `bwrap_available` must observe the real failure, not just `which`."""
        monkeypatch.setattr(system, "_which", lambda b: True)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, returncode=1),
        )
        assert system.bwrap_available() is False

    def test_missing_binary_degrades_to_false_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(system, "_which", lambda b: False)
        assert system.bwrap_available() is False


# ── argv construction: mechanism, no execution ──────────────────────────────


class TestArgvShape:
    def test_bwrap_binds_each_root_read_write_over_a_read_only_host(self, workspace: Path) -> None:
        argv = system.bwrap_argv((workspace,), "echo hi")
        assert argv[:2] == ["bwrap", "--unshare-all"]
        assert "--share-net" in argv  # network stays reachable; see module docstring
        ro_index = argv.index("--ro-bind")
        assert argv[ro_index : ro_index + 3] == ["--ro-bind", "/", "/"]
        bind_index = argv.index("--bind")
        resolved = str(workspace.resolve())
        assert argv[bind_index : bind_index + 3] == ["--bind", resolved, resolved]
        assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]

    def test_bwrap_binds_every_root_when_there_are_several(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        second = tmp_path / "codebase"
        second.mkdir()
        argv = system.bwrap_argv((workspace, second), "echo hi")
        assert argv.count("--bind") == 2

    def test_docker_run_mounts_each_root_and_runs_as_the_caller(self, workspace: Path) -> None:
        argv = system.docker_run_argv("my-container", (workspace,), "echo hi", None)
        assert argv[:3] == ["docker", "run", "--rm"]
        assert "--name" in argv and "my-container" in argv
        assert f"{os.getuid()}:{os.getgid()}" in argv
        resolved = str(workspace.resolve())
        assert f"{resolved}:{resolved}" in argv
        assert argv[-4:] == [system.SANDBOX_DOCKER_IMAGE, "sh", "-c", "echo hi"]

    def test_docker_run_forwards_only_the_explicit_env_not_the_host_env(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_HOST_SECRET_SHOULD_NOT_LEAK", "leak-me-not")
        argv = system.docker_run_argv("c", (workspace,), "echo hi", {"DOCKET_SCRATCH_DIR": "/x"})
        assert "-e" in argv
        assert "DOCKET_SCRATCH_DIR=/x" in argv
        assert not any("DOCKET_HOST_SECRET_SHOULD_NOT_LEAK" in part for part in argv)

    def test_docker_kill_never_raises_even_when_docker_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("no docker")

        monkeypatch.setattr(subprocess, "run", _raise)
        system.docker_kill("whatever")  # must not raise


# ── run_bash(sandbox="off"): the default is the original function ──────────


class TestSandboxOffIsUnchanged:
    def test_default_context_sandbox_is_off(self) -> None:
        assert ToolContext().sandbox == "off"

    def test_off_mode_matches_the_pre_p19_9_exact_output(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "printf %s hi", env={"X": "1"})
        assert out.ok and out.content == "hi"  # no marker, no suffix — byte for byte

    def test_off_mode_never_reports_a_sandbox_tag_even_when_both_backends_are_real(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(system, "bwrap_available", lambda: True)
        out = toolbox.run_bash((workspace,), "echo hi")  # sandbox left at the "off" default
        assert out.content == "hi"
        assert "sandbox" not in out.content


# ── honest reporting (deterministic — backends are mocked, not real) ───────


class TestHonestReportingIsDeterministic:
    def test_auto_with_neither_backend_reports_none_and_says_why(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: False)
        monkeypatch.setattr(system, "bwrap_available", lambda: False)
        out = toolbox.run_bash((workspace,), "echo hi", sandbox="auto")
        assert out.ok
        assert "[sandbox: none (docker unavailable, bwrap unavailable)]" in out.content

    def test_auto_forced_to_none_when_both_are_actually_available_says_so_too(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A silent 'none' that looks identical whether or not a jail was
        possible is exactly the failure this card exists to prevent."""
        monkeypatch.setattr(system, "docker_daemon_reachable", lambda: True)
        monkeypatch.setattr(system, "bwrap_available", lambda: True)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        out = toolbox.run_bash((workspace,), "echo hi", sandbox="auto")
        assert "[sandbox: none (forced off via DOCKET_SANDBOX_BACKEND)]" in out.content

    def test_a_jail_that_fails_to_start_is_a_reported_failure_not_a_silent_fallback(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If `sandbox="auto"` resolves to a real backend but the actual
        subprocess launch fails, the command MUST NOT run unsandboxed
        instead — that silent substitution is the specific failure mode
        this card exists to prevent."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")

        def _raise(*_args: object, **_kwargs: object) -> subprocess.Popen[str]:
            raise OSError("bwrap vanished mid-flight")

        monkeypatch.setattr(subprocess, "Popen", _raise)
        out = toolbox.run_bash((workspace,), "echo should-never-run", sandbox="auto")
        assert not out.ok
        assert "sandbox (bwrap) failed to start" in out.error

    def test_auto_reports_which_real_backend_ran(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
        # backend forced to "none" here only to keep this specific assertion
        # host-independent; the "real backend" classes below exercise docker
        # and bwrap for real when present.
        out = toolbox.run_bash((workspace,), "echo hi", sandbox="auto")
        assert "sandbox: none" in out.content


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
        # `printf` (not `echo`) — it is on core.security's SAFE_BINS
        # allowlist, so the command classifier allows it outright and this
        # test is exercising the sandbox wiring, not the tool-call gate.
        res = dispatch_tool(self._call('{"command": "printf hi"}'), ctx, builtin_registry())
        assert res.ok and res.executed
        assert "[sandbox: none" in res.content

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


# ── real backend: bwrap (skipped, with an explicit reason, if unavailable) ──


@needs_bwrap
class TestRealBwrapJail:
    def test_blocks_writes_outside_the_allowed_roots(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard this card exists to add: resolve_within never inspects
        a bash command's shell text at all, so nothing stopped this before.
        Planted and verified red by temporarily swapping bwrap_argv's
        `--ro-bind` for `--bind` (making the whole host writable) — the
        canary file landed on the real host filesystem; reverted, it does
        not.
        """
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        canary = Path(f"/tmp/p19-9-canary-{uuid.uuid4().hex[:8]}")
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
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
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
        under bwrap the same way it already does unsandboxed."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        marker = f"p19-9-bwrap-marker-{uuid.uuid4().hex[:8]}"
        out = toolbox.run_bash(
            (workspace,), f"echo {marker}; sleep 20 & sleep 20 & wait", timeout=1, sandbox="auto"
        )
        assert not out.ok and "timed out" in out.error
        time.sleep(1)
        assert _pgrep_count(marker) == 0

    def test_minimizes_env_a_host_secret_does_not_leak_in(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        monkeypatch.setenv("DOCKET_TEST_HOST_SECRET", "top-secret")
        out = toolbox.run_bash((workspace,), "echo VAL=$DOCKET_TEST_HOST_SECRET", sandbox="auto")
        assert "VAL=\n" in out.content or out.content.startswith("VAL=\n\n[sandbox")

    def test_explicit_ctx_env_still_reaches_the_jailed_command(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
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
        """The orphan risk unique to this backend: `docker run`'s own CLI
        process is a thin client the daemon runs the real container under,
        so killing only its process group does not stop the container
        (verified empirically while building this card — see
        `system.docker_kill`'s docstring). Planted and verified red by
        temporarily removing the `docker_kill` call from run_bash's timeout
        handler — the container was still running after the call returned;
        reverted, it is not.
        """
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        out = toolbox.run_bash((workspace,), "sleep 20", timeout=1, sandbox="auto")
        assert not out.ok and "timed out" in out.error
        time.sleep(1)
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=docket-sbx-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.stdout.strip() == ""
