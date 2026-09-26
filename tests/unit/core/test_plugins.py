"""Unit coverage for ``core.plugins``'s discovery/evaluation, and the ``when.plugin`` fail-closed
path it wires into ``core.policy``. See ``docket.plugins`` for the public API a plugin imports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.core import audit as _audit
from docket.core import plugins as _plugins
from docket.core import policy as _policy

SUBJECT = "docket.core.plugins"

_MIGRATION_PLUGIN = """
from docket.plugins import predicate


@predicate("touches_migrations")
def touches_migrations(call, ctx, **with_):
    return call.args.get("path", "").startswith("app/migrations/")
"""

_RAISING_PLUGIN = """
from docket.plugins import predicate


@predicate("boom")
def boom(call, ctx, **with_):
    raise RuntimeError("boom")
"""


def _write_policy(policies_dir: Path, name: str, doc: object) -> None:
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / name).write_text(json.dumps(doc), encoding="utf-8")


class TestGlobalPluginDrivesAPolicy:
    def test_a_global_plugin_returning_true_makes_ask_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)

        plugins_dir = home / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "migrations.py").write_text(_MIGRATION_PLUGIN, encoding="utf-8")

        _write_policy(
            home / "policies",
            "touches-migrations.json",
            {
                "id": "touches-migrations",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "when": {"plugin": "touches_migrations"},
                "action": "require_approval",
            },
        )

        call = _policy.ToolCallFacts("write", {"path": "app/migrations/0002.py"}, lambda: "")
        hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
        assert hit.action == "require_approval"
        assert hit.policy_id == "touches-migrations"


class TestUnappliedPluginFailsClosed:
    def test_a_plugin_only_under_a_codebase_is_absent_and_the_policy_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)

        # Present only in a codebase's own .docket/plugins/ -- never a scope `discover` reads.
        codebase_plugins = tmp_path / "codebase" / ".docket" / "plugins"
        codebase_plugins.mkdir(parents=True)
        (codebase_plugins / "migrations.py").write_text(_MIGRATION_PLUGIN, encoding="utf-8")

        assert "touches_migrations" not in _plugins.discover()

        _write_policy(
            home / "policies",
            "touches-migrations.json",
            {
                "id": "touches-migrations",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "when": {"plugin": "touches_migrations"},
                "action": "require_approval",
            },
        )

        call = _policy.ToolCallFacts("write", {"path": "app/migrations/0002.py"}, lambda: "")
        hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
        assert hit.action == "block"
        assert "touches_migrations" in hit.message
        assert "not applied" in hit.message


class TestARaisingPluginFailsClosedAndAudits:
    def test_a_raising_plugin_blocks_and_audits_one_deny(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)

        plugins_dir = home / "plugins"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "boom.py").write_text(_RAISING_PLUGIN, encoding="utf-8")

        _write_policy(
            home / "policies",
            "boom.json",
            {
                "id": "boom-policy",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "when": {"plugin": "boom"},
                "action": "allow",
            },
        )

        call = _policy.ToolCallFacts("write", {"path": "x.py"}, lambda: "")
        hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
        assert hit.action == "block"
        assert "boom" in hit.message

        entries = [e for e in _audit.read_audit() if e.get("action") == "policy.plugin"]
        assert len(entries) == 1
        assert "verdict=deny" in entries[0]["detail"]
