"""`docket init` refuses what it cannot store faithfully and answers `--json` on every stop
(cli-interface, input-validation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support.pods import members as _members
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.teams import fleet as _fleet

_hermetic = _support_home.hermetic_4

SUBJECT = "docket.interfaces.cli.commands.agents"

runner = CliRunner()


class TestInitRefusesWhatItCannotStore:
    @pytest.mark.parametrize("bad", ["!!!", "---"])
    def test_defect_30_83_an_empty_slug_is_refused_with_exit_2(self, bad: str) -> None:
        result = runner.invoke(app, ["init", bad])

        assert result.exit_code == 2, result.output
        assert "already exists" not in result.output
        assert _members() == []

    def test_defect_31_a_name_over_64_characters_is_refused_without_a_traceback(self) -> None:
        result = runner.invoke(app, ["init", "a" * 70])

        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
        assert "64" in result.output
        assert _members() == []

    def test_defect_32_a_missing_codebase_is_refused(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "demo", str(tmp_path / "nope")])

        assert result.exit_code == 2, result.output
        assert "nope" in result.output
        assert _members() == []

    def test_defect_32_a_relative_codebase_is_stored_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "rel").mkdir()
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["init", "demo", "rel"])

        assert result.exit_code == 0, result.output
        stored = _fleet.meta_get("demo-lead", "codebase", "")
        assert Path(stored).is_absolute()
        assert Path(stored) == (tmp_path / "rel").resolve()

    @pytest.mark.parametrize(
        "args",
        [["!!!"], ["a" * 70], ["demo", "/nonexistent-w120-2"]],
        ids=["defect-30-83", "defect-31", "defect-32"],
    )
    def test_the_refusals_print_json_that_parses_under_json(self, args: list[str]) -> None:
        result = runner.invoke(app, ["init", *args, "--json"])

        assert result.exit_code == 2, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "invalid"
        assert payload["reason"]

    def test_defect_85_the_invalid_id_message_keeps_its_bracketed_pattern(
        self, tmp_path: Path
    ) -> None:
        spec = tmp_path / "spec.json"
        spec.write_text(
            json.dumps([{"id": "Bad_ID", "blueprint": "software", "codebase": str(tmp_path)}])
        )

        result = runner.invoke(app, ["init", "--from", str(spec)])

        assert result.exit_code == 1
        assert "^[a-z0-9]+(?:-[a-z0-9]+)*$" in result.output


def _repo_with(tmp_path: Path, relpath: str, text: str) -> Path:
    code = tmp_path / "code"
    (code / ".docket").mkdir(parents=True)
    (code / ".docket" / relpath).write_text(text)
    return code


class TestJsonOnEveryReviewStop:
    def test_defect_58_a_refused_shell_prints_json(self, tmp_path: Path) -> None:
        code = _repo_with(
            tmp_path, "pod.yaml", "kind: pod\nname: demo\nsettings:\n  allowCommands: [bash]\n"
        )

        result = runner.invoke(app, ["init", "demo", str(code), "--json"])

        assert result.exit_code == 2, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "refused"
        assert payload["refused"] == ["bash"]

    def test_defect_58_a_changed_code_prints_json_without_the_current_code(
        self, tmp_path: Path
    ) -> None:
        code = _repo_with(
            tmp_path, "pipeline.yaml", "name: p\nsteps:\n  - id: migrate\n    run: sh m.sh\n"
        )
        first = json.loads(runner.invoke(app, ["init", "demo", str(code), "--json"]).stdout)

        result = runner.invoke(app, ["init", "demo", str(code), "--accept", "000000", "--json"])

        assert result.exit_code == 2, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "code_mismatch"
        assert first["reviewCode"] not in result.stdout
        assert [i["runs"] for i in payload["items"]] == ["sh m.sh"]
