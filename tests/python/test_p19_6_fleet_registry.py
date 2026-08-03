"""P19-6: docket-native home + fleet registry.

Three invariants are pinned here, in order of how much they matter:

1. **fleet.json has exactly one writer.** Agent registration, channel
   bindings, and gates/isolation flags used to live in `openclaw.json`, a
   file the daemon (or a raw `openclaw` CLI call, or an older docket version)
   could also write — that second writer was the actual mechanism behind
   every drift `core/sync.py` ever caught. `fleet.json` is docket-owned and
   read/written **only** through `edges/adapters/openclaw.py`'s ACL
   functions, which in turn go through `edges/store.py`; a second module
   reaching for `config.FLEET_FILE` directly would reopen exactly the
   second-writer shape this card exists to close.
2. **The fleet registry does not duplicate what `.docket-meta.json` already
   owns.** `FleetAgent` tracks only the bare registration fact (`id`) — no
   `model`, no `sessionKey`. Re-adding either field would recreate the
   drift-by-construction this card removes, even though nothing would look
   obviously wrong at a glance (the schema is `extra="allow"`, so a stray
   field round-trips silently).
3. **Registering/unregistering an agent never touches `openclaw.json`.** Pre-
   P19-6, `add_agent`/`remove_agent` wrote `agents.list` there. Post-P19-6,
   `openclaw.json` is entirely the daemon's business (until P19-7 deletes it)
   and these calls must leave it byte-for-byte alone.
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
    """Only the ACL (and config.py, which just defines the constant) may
    reference FLEET_FILE. Mirrors test_p19_2_tool_registry.py's
    'only the chokepoint imports the handler module' guard."""

    ALLOWED_REFERRERS: ClassVar[set[str]] = {
        "config.py",
        "edges/adapters/openclaw.py",
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


# TestRegistrationNeverTouchesOpenclawJson deleted (Phase 19 P19-7b):
# openclaw.json itself -- not just fleet registration's non-interference with
# it -- is gone. P19-6 proved add_agent/remove_agent left the daemon's file
# byte-identical; P19-7b closes the loop by deleting that file format
# outright, so there is no longer anything for this test to leave untouched.


class TestDualSourceModulesDeleted:
    """core/sync.py and core/oc_models.py are deleted, not ported — the
    dual-source drift check they implemented has nothing left to compare."""

    def test_core_sync_module_is_gone(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            import docket.core.sync  # noqa: F401

    def test_core_oc_models_module_is_gone(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            import docket.core.oc_models  # noqa: F401
