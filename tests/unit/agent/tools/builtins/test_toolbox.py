"""`run_bash`'s process lifecycle callback (`on_process`).

An external plan-of-record (Tack) running a pod task needs one event per real OS
process group a `bash` call starts, so it can show and cancel a long-running command. Pins:
exactly one `("started", {"pgid": ...})` followed by exactly one `("exited", {...})` per call,
`exitCode` on a normal (or non-zero) completion, `signal="SIGKILL"` when this module itself
killed the group (timeout), no event at all when `Popen` never produced a process, and no calls
at all when `on_process` is left `None` -- the default, byte-for-byte-unchanged path. `tool`/
`callId` are not this module's concern: `agent/tools/registry.py` tags those on top. See
specs/functional/trace-store.spec.md "Process lifecycle events".
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.fakes import FakeGit

from docket.agent.tools.builtins import toolbox
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import artifact_path_in, artifact_scope
from docket.sandbox import landlock as _landlock
from docket.sandbox.launch import Launcher

workspace = _support_pods.workspace

SUBJECT = "docket.agent.tools.builtins.toolbox"


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

    def test_output_that_cannot_be_decoded_is_a_failed_outcome_with_a_paired_exit(
        self, workspace: Path
    ) -> None:
        recorder = _Recorder()

        out = toolbox.run_bash((workspace,), "printf '\\377\\376'", timeout=5, on_process=recorder)

        assert not out.ok
        assert "could not be read" in out.error
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        exited_data = recorder.events[1][1]
        assert exited_data["exitCode"] == 0
        assert "signal" not in exited_data

    def test_a_read_failure_with_the_command_still_running_kills_the_group(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _Recorder()
        real_popen = toolbox.subprocess.Popen

        class _FailingRead(real_popen):  # type: ignore[type-arg, misc]
            def communicate(self, *args: object, **kwargs: object) -> tuple[str, str]:
                if not getattr(self, "_failed_once", False):
                    self._failed_once = True
                    raise RuntimeError("pipe broke")
                return super().communicate(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(toolbox.subprocess, "Popen", _FailingRead)
        command = 'exec python3 -c "import time; time.sleep(30)"'

        out = toolbox.run_bash((workspace,), command, timeout=60, on_process=recorder)

        assert not out.ok
        assert [kind for kind, _ in recorder.events] == ["started", "exited"]
        assert recorder.events[1][1]["signal"] == "SIGKILL"
        assert "exitCode" not in recorder.events[1][1]
        with pytest.raises(ProcessLookupError):
            os.killpg(int(str(recorder.events[0][1]["pgid"])), 0)

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


class TestJailedCacheDir:
    def _capture(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
        fake_git: FakeGit,
    ) -> dict[str, object]:
        seen: dict[str, object] = {}

        def _popen(argv: object, **kwargs: object) -> None:
            seen["argv"] = argv
            seen["env"] = kwargs["env"]
            raise OSError("stop")

        monkeypatch.setattr(toolbox.subprocess, "Popen", _popen)
        monkeypatch.setattr(_landlock, "git_dirs", lambda _root: [])
        bind_launcher(landlock=True, seatbelt=False, docker=False)
        return seen

    def test_a_jailed_command_gets_the_cache_variables_and_a_rw_root(
        self,
        workspace: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
        fake_git: FakeGit,
    ) -> None:
        seen = self._capture(monkeypatch, bind_launcher, fake_git)
        cache = tmp_path / "cache"
        cache.mkdir()

        toolbox.run_bash((workspace,), "true", sandbox="auto", cache_dir=cache)

        env = seen["env"]
        assert isinstance(env, dict)
        for name in (
            "HOME",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "UV_CACHE_DIR",
            "PIP_CACHE_DIR",
            "npm_config_cache",
        ):
            assert env[name] == str(cache)
        argv = seen["argv"]
        assert isinstance(argv, list)
        assert str(cache.resolve()) in argv

    def test_without_a_cache_dir_home_is_not_redirected(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
        bind_launcher: Callable[..., Launcher],
        fake_git: FakeGit,
    ) -> None:
        seen = self._capture(monkeypatch, bind_launcher, fake_git)

        toolbox.run_bash((workspace,), "true", sandbox="auto")

        env = seen["env"]
        assert isinstance(env, dict)
        assert "HOME" not in env
        assert "XDG_CACHE_HOME" not in env


class TestToolOutputBudget:
    """Glob, grep and read print root-relative, bounded output (agent-loop requirements 80-82)."""

    @staticmethod
    def _tree(workspace: Path, count: int = 2000) -> None:
        for i in range(count):
            package = workspace / "src" / f"pkg{i // 100:02d}"
            package.mkdir(parents=True, exist_ok=True)
            (package / f"mod{i:04d}.py").write_text("needle\n", encoding="utf-8")
        vendored = workspace / "node_modules" / "left-pad"
        vendored.mkdir(parents=True)
        (vendored / "index.js").write_text("needle\n", encoding="utf-8")

    def test_glob_prints_root_relative_sorted_paths_and_skips_vendored_dirs(
        self, workspace: Path
    ) -> None:
        self._tree(workspace)
        out = toolbox.glob_files((workspace,), "**/*")
        assert out.ok
        body, _, footer = out.content.partition("\n\n[truncated")
        lines = body.splitlines()
        assert lines[0].startswith("src/")
        assert str(workspace) not in out.content
        assert "node_modules" not in out.content
        assert lines == sorted(lines)
        assert footer  # the 300-result cap is announced, not silent
        assert len(out.content) <= current_home().tool_max_output_chars + 80

    def test_glob_under_a_second_root_prints_relative_to_that_root(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        (second / "lib").mkdir(parents=True)
        first.mkdir()
        (second / "lib" / "util.py").write_text("x", encoding="utf-8")
        out = toolbox.glob_files((first, second), "**/*.py", path=str(second))
        assert out.ok and out.content == "lib/util.py"

    def test_grep_prints_root_relative_paths_and_skips_vendored_dirs(self, workspace: Path) -> None:
        self._tree(workspace, count=3)
        out = toolbox.grep_files((workspace,), "needle")
        assert out.ok
        lines = out.content.splitlines()
        assert lines == sorted(lines)
        assert lines[0].startswith("src/pkg00/mod0000.py:1:")
        assert str(workspace) not in out.content
        assert "node_modules" not in out.content

    def test_read_without_a_window_returns_numbered_default_lines_and_footer(
        self, workspace: Path
    ) -> None:
        path = workspace / "long.txt"
        path.write_text("".join(f"line {i}\n" for i in range(1, 1001)), encoding="utf-8")
        out = toolbox.read_file((workspace,), "long.txt")
        assert out.ok
        lines = out.content.splitlines()
        assert lines[0] == f"{1}\tline 1"
        window, footer = lines[:-2], lines[-1]
        assert len(window) == toolbox.READ_DEFAULT_LINES
        assert window[-1] == f"{toolbox.READ_DEFAULT_LINES}\tline {toolbox.READ_DEFAULT_LINES}"
        assert (
            footer
            == f"[lines 1-{toolbox.READ_DEFAULT_LINES} of 1000; call read with offset={toolbox.READ_DEFAULT_LINES + 1} for more]"
        )

    def test_read_without_a_window_stops_at_the_default_character_budget(
        self, workspace: Path
    ) -> None:
        """A file of long lines is cut by characters before the line count is reached."""
        row = "x" * 99
        (workspace / "wide.txt").write_text(f"{row}\n" * 300, encoding="utf-8")
        out = toolbox.read_file((workspace,), "wide.txt")
        window, footer = out.content.split("\n\n[")
        assert len(window) <= toolbox.READ_DEFAULT_CHARS
        shown = len(window.splitlines())
        assert 0 < shown < 300
        assert footer == f"lines 1-{shown} of 300; call read with offset={shown + 1} for more]"

    def test_read_without_a_window_stops_at_the_turns_read_window(self, workspace: Path) -> None:
        """A turn's `read_window` replaces the default character budget."""
        row = "x" * 99
        (workspace / "wide.txt").write_text(f"{row}\n" * 300, encoding="utf-8")
        with artifact_scope("", read_chars=1000):
            out = toolbox.read_file((workspace,), "wide.txt")
        window = out.content.split("\n\n[")[0]
        assert len(window) <= 1000 and len(window.splitlines()) < 10

    def test_read_with_an_explicit_window_is_numbered_and_names_what_remains(
        self, workspace: Path
    ) -> None:
        (workspace / "short.txt").write_text(
            "".join(f"line {i}\n" for i in range(1, 31)), encoding="utf-8"
        )
        out = toolbox.read_file((workspace,), "short.txt", offset=10, limit=5)
        assert out.content.splitlines() == [f"{n}\tline {n}" for n in range(10, 15)] + [
            "",
            "[lines 10-14 of 30; call read with offset=15 for more]",
        ]
        tail = toolbox.read_file((workspace,), "short.txt", offset=28)
        assert tail.content == f"{28}\tline 28\n{29}\tline 29\n{30}\tline 30"

    def test_edit_applies_to_text_copied_from_the_numbered_window(self, workspace: Path) -> None:
        path = workspace / "edit.txt"
        path.write_text("".join(f"line {i}\n" for i in range(1, 11)), encoding="utf-8")
        window = toolbox.read_file((workspace,), "edit.txt").content.splitlines()
        copied = "\n".join(numbered.split("\t", 1)[1] for numbered in window[:3])
        out = toolbox.edit_file((workspace,), "edit.txt", copied, "EDITED")
        assert out.ok
        assert path.read_text(encoding="utf-8").startswith("EDITED\nline 4\n")

    def test_glob_and_grep_output_is_bounded_by_the_announced_truncation(
        self, workspace: Path
    ) -> None:
        with use_home(dataclasses.replace(current_home(), tool_max_output_chars=120)):
            self._tree(workspace, count=50)
            out = toolbox.grep_files((workspace,), "needle")
            assert out.ok and out.content.endswith("more characters]")
            assert len(out.content) <= 120 + 60


class TestFileStateIsVisible:
    """`read`, `write` and `bash` tell the model the state a gate will judge: the final newline."""

    def test_read_names_a_missing_trailing_newline(self, workspace: Path) -> None:
        (workspace / "a.txt").write_text("one\ntwo", encoding="utf-8")
        out = toolbox.read_file((workspace,), "a.txt")
        assert out.content == "1\tone\n2\ttwo\n[2 lines; no newline at end of file]"

    def test_read_of_a_file_with_a_trailing_newline_has_no_footer(self, workspace: Path) -> None:
        (workspace / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        assert toolbox.read_file((workspace,), "a.txt").content == "1\tone\n2\ttwo"

    def test_read_of_an_empty_file_says_so(self, workspace: Path) -> None:
        (workspace / "a.txt").write_text("", encoding="utf-8")
        assert toolbox.read_file((workspace,), "a.txt").content == "[empty file]"

    def test_read_of_a_paged_file_without_a_final_newline_keeps_both_footers(
        self, workspace: Path
    ) -> None:
        (workspace / "a.txt").write_text("\n".join(f"l{i}" for i in range(1, 501)), "utf-8")
        tail = toolbox.read_file((workspace,), "a.txt").content.splitlines()[-2:]
        assert tail[0] == "[lines 1-400 of 500; call read with offset=401 for more]"
        assert tail[1] == "[500 lines; no newline at end of file]"

    def test_write_reports_path_bytes_lines_newline_and_whether_it_existed(
        self, workspace: Path
    ) -> None:
        first = toolbox.write_file((workspace,), "sub/a.txt", "café\n")
        assert (
            first.content == "wrote sub/a.txt: 6 bytes, 1 lines, ends with newline: yes (created)"
        )
        again = toolbox.write_file((workspace,), "sub/a.txt", "x\ny")
        assert (
            again.content
            == "wrote sub/a.txt: 3 bytes, 2 lines, ends with newline: no (overwritten)"
        )

    def test_write_of_nothing_counts_zero_lines(self, workspace: Path) -> None:
        out = toolbox.write_file((workspace,), "a.txt", "")
        assert out.content == "wrote a.txt: 0 bytes, 0 lines, ends with newline: no (created)"

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("printf 'a\\nb'", "a\nb\n[output had no trailing newline]"),
            ("printf 'a\\nb\\n'", "a\nb"),
            ("echo hi", "hi"),
            ("true", "(no output)"),
        ],
    )
    def test_bash_names_a_missing_trailing_newline(
        self, workspace: Path, command: str, expected: str
    ) -> None:
        assert toolbox.run_bash((workspace,), command, timeout=5).content == expected


class TestBashOutputForTheModel:
    def test_a_failure_shows_stderr_before_stdout_and_a_success_the_reverse(
        self, workspace: Path
    ) -> None:
        command = "echo to-stdout; echo to-stderr >&2; exit {code}"

        failed = toolbox.run_bash((workspace,), command.format(code=3), timeout=5)
        passed = toolbox.run_bash((workspace,), command.format(code=0), timeout=5)

        assert failed.content == "to-stderr\nto-stdout"
        assert failed.error == "command exited 3"
        assert passed.content == "to-stdout\nto-stderr"

    def test_exit_127_names_the_known_cause(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "no-such-docket-binary", timeout=5)

        assert not out.ok
        assert out.error == (
            "command exited 127; not on PATH inside the jail or not in allowCommands"
        )

    def test_another_exit_status_adds_no_cause(self, workspace: Path) -> None:
        assert toolbox.run_bash((workspace,), "exit 2", timeout=5).error == "command exited 2"

    def test_progress_lines_and_colour_are_normalized_before_the_cut(self, workspace: Path) -> None:
        command = "printf '\\033[32mok\\033[0m\\n1%%\\r50%%\\r100%%\\n'; yes retry | head -n 50"

        out = toolbox.run_bash((workspace,), command, timeout=5)

        assert out.content == "ok\n100%\nretry  [x 50]"

    def test_a_cut_result_keeps_the_tail_where_the_verdict_is(self, workspace: Path) -> None:
        command = "seq 1 400; echo '== 3 failed, 9 passed =='"

        with use_home(dataclasses.replace(current_home(), tool_max_output_chars=200)):
            out = toolbox.run_bash((workspace,), command, timeout=5)

        head, marker, _tail = out.content.partition("\n\n[truncated:")
        assert head.startswith("1\n2\n3")
        assert marker
        assert out.content.endswith("== 3 failed, 9 passed ==")

    def test_a_result_cut_in_a_pod_names_its_whole_and_read_returns_the_rest(
        self, workspace: Path
    ) -> None:
        (current_home().pods_dir / "pod").mkdir(parents=True)

        with (
            use_home(dataclasses.replace(current_home(), tool_max_output_chars=300)),
            artifact_scope("pod"),
        ):
            out = toolbox.run_bash((workspace,), "seq 1 2000", timeout=5)
            path = artifact_path_in(out.content)
            assert path is not None
            window = toolbox.read_file((workspace,), path, offset=1500, limit=3)
            found = toolbox.grep_files((workspace,), r"^1999$", path)

        assert Path(path).read_text() == "\n".join(str(n) for n in range(1, 2001))
        assert window.content.splitlines()[:3] == ["1500\t1500", "1501\t1501", "1502\t1502"]
        assert ":1999:1999" in found.content

    def test_a_path_outside_the_roots_and_the_artifacts_stays_refused(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        (current_home().pods_dir / "pod").mkdir(parents=True)
        outside = tmp_path / "outside.txt"
        outside.write_text("secret\n")
        artifacts = current_home().pod_cache_dir("pod") / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "link.txt").symlink_to(outside)

        with artifact_scope("pod"):
            direct = toolbox.read_file((workspace,), str(outside))
            via_link = toolbox.read_file((workspace,), str(artifacts / "link.txt"))

        assert direct.refusal == "path_escape"
        assert via_link.refusal == "path_escape"

    def test_without_a_pod_scope_read_does_not_open_artifacts(self, workspace: Path) -> None:
        artifacts = current_home().pod_cache_dir("pod") / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "a.txt").write_text("x\n")

        assert toolbox.read_file((workspace,), str(artifacts / "a.txt")).refusal == "path_escape"


class TestEditNotFound:
    def _file(self, workspace: Path) -> None:
        (workspace / "f.py").write_text(
            "def alpha():\n    return 1\n\n\ndef beta(value):\n    return value + 1\n"
        )

    def test_a_near_miss_lists_the_closest_lines_and_changes_nothing(self, workspace: Path) -> None:
        self._file(workspace)

        out = toolbox.edit_file((workspace,), "f.py", "def beta(values):", "def gamma():")

        assert not out.ok
        assert out.error.startswith("old_string not found in f.py")
        assert "5\tdef beta(value):" in out.error
        assert out.error.endswith(
            "the text must match exactly; copy it from read without the line-number prefix"
        )
        assert (workspace / "f.py").read_text().count("def beta(value):") == 1

    def test_at_most_three_lines_are_offered_best_first(self, workspace: Path) -> None:
        (workspace / "g.txt").write_text(
            "total = 10\ntotal = 11\ntotal = 12\ntotal = 13\nunrelated words here\n"
        )

        out = toolbox.edit_file((workspace,), "g.txt", "total = 14", "x")

        shown = [line for line in out.error.splitlines() if line[:1].isdigit()]
        assert len(shown) == 3

    def test_text_with_nothing_close_says_only_that_it_was_not_found(self, workspace: Path) -> None:
        self._file(workspace)

        out = toolbox.edit_file((workspace,), "f.py", "zzzzzzzzzzzzzzzz", "x")

        assert out.error == "old_string not found in f.py"
