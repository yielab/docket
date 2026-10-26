"""docket-native home + fleet registry.

Two invariants pinned here: (1) **fleet.json has exactly one writer** --
agent registration, channel bindings, and gates/isolation flags are
docket-owned and read/written through `teams/fleet.py`, which goes through
`platform/store.py`; a second module reaching for `Home.fleet_file` directly
would reopen second-writer drift. (2) **The fleet registry does not
duplicate what `.docket-meta.json` already owns** -- `FleetAgent` tracks
only the bare `id`, no `model`/`sessionKey`; re-adding either would recreate
drift-by-construction silently, since the schema is `extra="allow"`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

from docket.teams.fleet import FleetAgent

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKET_SRC = REPO_ROOT / "src" / "docket"


class TestFleetSingleWriter:
    """Only teams/fleet.py (and kernel/home.py, which defines the path) may open fleet.json.
    The two CLI modules below only name its path, to tighten its mode and to report it.
    Mirrors test_tool_registry.py's 'only the chokepoint imports the handler module' guard."""

    ALLOWED_REFERRERS: ClassVar[set[str]] = {
        "kernel/home.py",
        "teams/fleet.py",
        "interfaces/cli/commands/setup.py",
        "interfaces/cli/commands/setup_check.py",
    }

    @staticmethod
    def _references_fleet_file(tree: ast.AST) -> bool:
        return any(
            isinstance(node, ast.Attribute) and node.attr == "fleet_file" for node in ast.walk(tree)
        )

    def test_only_the_acl_references_fleet_file(self) -> None:
        offenders = [
            rel
            for path in sorted(DOCKET_SRC.rglob("*.py"))
            if (rel := path.relative_to(DOCKET_SRC).as_posix()) not in self.ALLOWED_REFERRERS
            and self._references_fleet_file(ast.parse(path.read_text()))
        ]
        assert not offenders, f"fleet.json reachable outside the ACL from: {offenders}"


class TestFleetAgentSchemaMinimal:
    """FleetAgent must never grow model/sessionKey — that is .docket-meta.json's job."""

    def test_fleet_agent_declares_only_id(self) -> None:
        assert set(FleetAgent.model_fields) == {"id"}

    def test_fleet_agent_has_no_model_attribute(self) -> None:
        agent = FleetAgent(id="myshop")
        assert not hasattr(agent, "model")
        assert not hasattr(agent, "session_key")
