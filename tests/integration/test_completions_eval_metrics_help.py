"""completions, metrics, help commands.

These call the public run_* entry points in-process. stdout is captured with
capsys to assert on the rendered text; the return value is the process exit
code. Config-dependent modules (metrics) are repointed at a temp DOCKET_HOME.

`docket eval` is not a command — see tests/guards/test_removed_commands.py for its
removed-command-notice coverage.
"""

from __future__ import annotations

import pytest

from docket.cli import _completions, _help

SUBJECT = "docket.cli"

# ── completions ─────────────────────────────────────────────────────────────────


class TestCompletions:
    def test_bash_emits_completion_function(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _completions.run_completions("bash")
        out = capsys.readouterr().out
        assert rc == 0
        assert "_docket_complete()" in out
        assert "complete -F _docket_complete docket" in out
        # command table is present
        assert "list status add init info delete maintain" in out

    def test_zsh_emits_completion_function(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _completions.run_completions("zsh")
        out = capsys.readouterr().out
        assert rc == 0
        assert "#compdef docket" in out
        assert "_docket()" in out
        assert "_docket_ids()" in out
        assert "'init:Initialize the current project with its minimum isolated pod'" in out

    def test_no_arg_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _completions.run_completions(None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Usage: docket completions <bash|zsh>" in out

    def test_help_token_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _completions.run_completions("--help")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Usage: docket completions <bash|zsh>" in out

    def test_unknown_shell_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _completions.run_completions("fish")
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown shell 'fish'" in err

    def test_bash_is_byte_stable(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Re-emitting yields identical bytes (drift guard)."""
        _completions.run_completions("bash")
        first = capsys.readouterr().out
        _completions.run_completions("bash")
        second = capsys.readouterr().out
        assert first == second
        assert first.endswith("complete -F _docket_complete docket\n")


# ── help ────────────────────────────────────────────────────────────────────────


class TestHelp:
    def test_prints_all_sections(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help()
        out = capsys.readouterr().out
        assert rc == 0
        for section in (
            "AGENT TYPES",
            "USAGE",
            "LIFECYCLE",
            "MAINTENANCE",
            "TELEGRAM",
            "CONFIGURATION",
            "CONTEXT & MEMORY",
            "MONITORING",
            "OBSERVABILITY",
            "PODS & QUEUE",
            "UTILITIES",
            "MODEL POLICY",
            "EXAMPLES",
            "PATHS",
        ):
            assert section in out, f"missing section: {section}"

    def test_includes_resolved_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help()
        out = capsys.readouterr().out
        # cheap/strong labels with a resolved model id each
        assert "cheap" in out
        assert "strong" in out
        assert "/" in out  # provider/model ids rendered

    def test_lists_core_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help()
        out = capsys.readouterr().out
        for cmd in ("install", "list", "add", "doctor", "completions", "help"):
            assert cmd in out

    def test_topic_prints_that_commands_own_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help("doctor")
        out = capsys.readouterr().out
        assert rc == 0
        assert "doctor" in out
        assert "AGENT TYPES" not in out  # differs from the bare `docket help` reference

    def test_unknown_topic_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _help.run_help("not-a-real-command")
        err = capsys.readouterr().err
        assert rc == 1
        assert "not-a-real-command" in err

    def test_topic_differs_from_bare_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        _help.run_help("doctor")
        topic_out = capsys.readouterr().out
        _help.run_help()
        bare_out = capsys.readouterr().out
        assert topic_out != bare_out
