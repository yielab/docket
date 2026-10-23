"""`docket log` -- the count argument, the unknown-verb refusal and the chain check."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.cli import app
from docket.core.audit import audit_log
from docket.kernel.home import Home, use_home

SUBJECT = "docket.cli._log"

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with use_home(Home(tmp_path / "home")):
        yield tmp_path / "home"


def _record(count: int) -> None:
    for i in range(count):
        audit_log("keys.add", f"entry-{i}")


class TestLog:
    def test_a_leading_number_limits_the_entries(self, home: Path) -> None:
        _record(5)
        result = runner.invoke(app, ["log", "2"])
        assert result.exit_code == 0
        assert "entry-4" in result.output and "entry-3" in result.output
        assert "entry-2" not in result.output

    def test_json_prints_the_raw_lines(self, home: Path) -> None:
        _record(2)
        result = runner.invoke(app, ["log", "--json"])
        assert result.exit_code == 0
        assert [json.loads(line)["detail"] for line in result.output.splitlines()] == [
            "entry-0",
            "entry-1",
        ]

    def test_json_on_an_empty_log_prints_nothing(self, home: Path) -> None:
        result = runner.invoke(app, ["log", "--json"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_an_unknown_verb_is_a_usage_error(self, home: Path) -> None:
        assert runner.invoke(app, ["log", "bogus"]).exit_code == 2

    def test_a_word_that_is_not_a_count_is_named_with_the_usage(self, home: Path) -> None:
        result = runner.invoke(app, ["log", "abc"])
        assert result.exit_code == 2
        assert "'abc'" in result.output and "[N]" in result.output
        assert "No such command" not in result.output

    def test_the_empty_log_message_names_what_is_recorded_without_scope(self, home: Path) -> None:
        result = runner.invoke(app, ["log"])
        assert result.exit_code == 0
        assert "No log yet." in result.output
        assert "scope" not in result.output

    def test_audit_is_not_a_command(self, home: Path) -> None:
        assert runner.invoke(app, ["audit"]).exit_code == 2


class TestVerify:
    def test_a_clean_chain_exits_zero(self, home: Path) -> None:
        _record(3)
        assert runner.invoke(app, ["log", "verify"]).exit_code == 0

    def test_a_tampered_line_exits_one(self, home: Path) -> None:
        _record(3)
        logf = home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["detail"] = "forged"
        lines[0] = json.dumps(first)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert runner.invoke(app, ["log", "verify"]).exit_code == 1
