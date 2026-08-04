"""docket-native home + fleet registry.

Two invariants are pinned here, in order of how much they matter:

1. **fleet.json has exactly one writer.** Agent registration, channel
   bindings, and gates/isolation flags are docket-owned and read/written
   through `core/fleet.py`, which in turn goes through `edges/store.py`; a
   second module reaching for `config.FLEET_FILE` directly would reopen the
   second-writer drift this registry exists to prevent.
2. **The fleet registry does not duplicate what `.docket-meta.json` already
   owns.** `FleetAgent` tracks only the bare registration fact (`id`) — no
   `model`, no `sessionKey`. Re-adding either field would recreate
   drift-by-construction, even though nothing would look obviously wrong at
   a glance (the schema is `extra="allow"`, so a stray field round-trips
   silently).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

from docket.core.fleet import FleetAgent

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKET_SRC = REPO_ROOT / "src" / "docket"


class TestFleetSingleWriter:
    """Only core/fleet.py (and config.py, which just defines the constant) may
    reference FLEET_FILE. Mirrors test_tool_registry.py's
    'only the chokepoint imports the handler module' guard."""

    ALLOWED_REFERRERS: ClassVar[set[str]] = {
        "config.py",
        "core/fleet.py",
    }

    @staticmethod
    def _references_fleet_file(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "FLEET_FILE":
                return True
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "FLEET_FILE" for alias in node.names
            ):
                return True
        return False

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


class TestDualSourceModulesDeleted:
    """core/sync.py and core/oc_models.py are deleted, not ported — the
    dual-source drift check they implemented has nothing left to compare."""

    def test_core_sync_module_is_gone(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            import docket.core.sync  # noqa: F401

    def test_core_oc_models_module_is_gone(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            import docket.core.oc_models  # noqa: F401
