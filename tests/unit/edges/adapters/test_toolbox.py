"""`run_bash`'s process lifecycle callback (`on_process`).

An external plan-of-record (Tack) spawning `docket harness run` needs one event per real OS
process group a `bash` call starts, so it can show and cancel a long-running command. Pins:
exactly one `("started", {"pgid": ...})` followed by exactly one `("exited", {...})` per call,
`exitCode` on a normal (or non-zero) completion, `signal="SIGKILL"` when this module itself
killed the group (timeout), no event at all when `Popen` never produced a process, and no calls
at all when `on_process` is left `None` -- the default, byte-for-byte-unchanged path. `tool`/
`callId` are not this module's concern: `core/tools.py` tags those on top. See
specs/functional/trace-store.spec.md "Process lifecycle events".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.edges.adapters import toolbox

SUBJECT = "docket.edges.adapters.toolbox"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def __call__(self, kind: str, data: dict[str, object]) -> None:
        self.events.append((kind, dict(data)))


class TestOnProcessLifecycle:
    def test_a_successful_command_fires_started_then_exited_with_exit_code_zero(
        self, workspace: Path
    ) -> None:
        recorder = _Recorder()

        out = toolbox.run_bash((workspace,), "true", timeout=5, on_process=recorder)

        assert out.ok
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        started_data = recorder.events[0][1]
        exited_data = recorder.events[1][1]
        assert started_data == {"pgid": started_data["pgid"]}
        assert isinstance(started_data["pgid"], int) and started_data["pgid"] > 0
        assert exited_data["pgid"] == started_data["pgid"]
        assert exited_data["exitCode"] == 0
        assert "signal" not in exited_data

    def test_a_failing_command_fires_exited_with_its_real_nonzero_exit_code(
        self, workspace: Path
    ) -> None:
        recorder = _Recorder()

        out = toolbox.run_bash((workspace,), "exit 7", timeout=5, on_process=recorder)

        assert not out.ok
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        assert recorder.events[1][1]["exitCode"] == 7
        assert "signal" not in recorder.events[1][1]

    def test_a_timed_out_command_fires_exited_with_signal_sigkill_not_an_exit_code(
        self, workspace: Path
    ) -> None:
        recorder = _Recorder()

        out = toolbox.run_bash(
            (workspace,),
            'python3 -c "import time; time.sleep(5)"',
            timeout=1,
            on_process=recorder,
        )

        assert not out.ok
        assert "timed out" in out.error
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        exited_data = recorder.events[1][1]
        assert exited_data["signal"] == "SIGKILL"
        assert "exitCode" not in exited_data

    def test_a_cancelled_command_fires_exited_with_signal_sigkill(self, workspace: Path) -> None:
        recorder = _Recorder()

        out = toolbox.run_bash(
            (workspace,),
            'python3 -c "import time; time.sleep(30)"',
            timeout=60,
            cancelled=lambda: True,
            on_process=recorder,
        )

        assert not out.ok
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        assert recorder.events[1][1]["signal"] == "SIGKILL"

    def test_with_no_callback_nothing_is_invoked_and_behaviour_is_unchanged(
        self, workspace: Path
    ) -> None:
        out = toolbox.run_bash((workspace,), "echo hi", timeout=5, on_process=None)
        assert out.ok
        assert "hi" in out.content

    def test_a_popen_failure_produces_no_event_at_all(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder()

        def _raise(*args: object, **kwargs: object) -> None:
            raise OSError("no such binary")

        monkeypatch.setattr(toolbox.subprocess, "Popen", _raise)

        out = toolbox.run_bash((workspace,), "irrelevant", timeout=5, on_process=recorder)

        assert not out.ok
        assert recorder.events == []

    def test_pgid_matches_the_real_process_started(self, workspace: Path) -> None:
        recorder = _Recorder()
        pidfile = workspace / "pid"
        # `exec`s into `true` rather than forking it, so the shell reported as `$$` is the
        # same process this call actually starts -- no separate child pid to confuse with it.
        command = f"echo $$ > {pidfile}; exec true"

        toolbox.run_bash((workspace,), command, timeout=5, on_process=recorder)

        real_pid = int(pidfile.read_text().strip())
        assert recorder.events[0][1]["pgid"] == real_pid
