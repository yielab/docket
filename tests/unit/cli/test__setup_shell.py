"""`docket setup shell` -- the completion scripts are generated from the live command tree."""

from __future__ import annotations

from typer.testing import CliRunner

from docket.cli import app

SUBJECT = "docket.cli._setup_shell"

_runner = CliRunner()


def test_bash_emits_the_completion_function_and_the_setup_words() -> None:
    result = _runner.invoke(app, ["setup", "shell", "bash"])

    assert result.exit_code == 0
    assert "_docket_complete()" in result.stdout
    assert "complete -F _docket_complete docket" in result.stdout
    assert '"setup provider")' in result.stdout


def test_zsh_emits_the_compdef_header() -> None:
    result = _runner.invoke(app, ["setup", "shell", "zsh"])

    assert result.exit_code == 0
    assert result.stdout.startswith("#compdef docket")


def test_output_is_byte_stable() -> None:
    first = _runner.invoke(app, ["setup", "shell", "bash"]).stdout
    second = _runner.invoke(app, ["setup", "shell", "bash"]).stdout

    assert first == second


def test_an_unknown_shell_is_a_usage_error() -> None:
    assert _runner.invoke(app, ["setup", "shell", "fish"]).exit_code == 2


def test_the_scripts_complete_pods_and_task_ids_from_the_workspace_tree() -> None:
    for shell in ("bash", "zsh"):
        out = _runner.invoke(app, ["setup", "shell", shell]).stdout
        assert "-lead/" in out
        assert "TASK_LIST.json" in out
        assert "jq" not in out
        assert "$_ids" not in out
