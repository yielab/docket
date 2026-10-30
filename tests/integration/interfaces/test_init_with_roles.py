"""`docket init --with` takes any role `docket pod roles` lists, in the order given, and refuses a
name the registry does not know before it provisions anything (cli-interface, `docket init`)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import home as _support_home
from tests.support.pods import members as _members
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet

_hermetic = _support_home.hermetic_no_tty

SUBJECT = "docket.interfaces.cli.commands.pod"

runner = CliRunner()


def _operator_role(name: str) -> None:
    roles = current_home().config_dir / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / f"{name}.yaml").write_text(
        f"kind: role\nname: {name}\ndescription: a test role\nmodel: strong\n"
        f"cannot: [write, edit, bash]\ninstructions: {name}.md\n"
    )
    (roles / f"{name}.md").write_text("x\n")


def _registered() -> list[str]:
    """The pod's member ids in the order provisioning registered them."""
    return [a.id for a in _fleet.list_agents()]


class TestInitWithRoles:
    def test_a_starter_and_an_operator_role_follow_the_lean_pair_in_the_given_order(
        self, tmp_path: Path
    ) -> None:
        _operator_role("critic")

        result = runner.invoke(app, ["init", "demo", str(tmp_path), "--with", "analyst,critic"])

        assert result.exit_code == 0, result.output
        assert _registered() == [
            "demo-lead",
            "demo-implementer",
            "demo-analyst",
            "demo-critic",
        ]

    def test_the_given_order_is_kept_not_the_registry_order(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "demo", str(tmp_path), "--with", "writer,analyst"])

        assert result.exit_code == 0, result.output
        assert _registered()[2:] == ["demo-writer", "demo-analyst"]

    def test_a_lean_role_or_a_repeat_adds_nothing(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "demo", str(tmp_path), "--with", "lead,analyst,Analyst,implementer"]
        )

        assert result.exit_code == 0, result.output
        assert _registered() == ["demo-lead", "demo-implementer", "demo-analyst"]


class TestInitWithAnUnknownRole:
    def test_it_exits_2_naming_the_name_and_the_known_roles_and_provisions_nothing(
        self, tmp_path: Path
    ) -> None:
        result = runner.invoke(app, ["init", "demo", str(tmp_path), "--with", "analyst,analist"])

        assert result.exit_code == 2, result.output
        assert "analist" in result.output
        assert "reviewer" in result.output
        assert _members() == []
        assert not (current_home().projects_dir / "demo-lead").exists()

    def test_under_json_it_prints_the_invalid_object(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "demo", str(tmp_path), "--with", "analist", "--json"])

        assert result.exit_code == 2, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "invalid"
        assert "analist" in payload["reason"]
        assert _members() == []
