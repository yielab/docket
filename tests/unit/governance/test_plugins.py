"""Unit coverage for ``governance.plugins``'s discovery/evaluation, and the ``when.plugin`` fail-closed
path it wires into ``governance.policy``. See ``docket.governance.plugin_api`` for the public API a plugin imports."""

from __future__ import annotations

import json
from pathlib import Path

from docket.governance import audit as _audit
from docket.governance import plugins as _plugins
from docket.governance import policy as _policy
from docket.kernel.home import Home, use_home

SUBJECT = "docket.governance.plugins"

_MIGRATION_PLUGIN = """
from docket.governance.plugin_api import predicate


@predicate("touches_migrations")
def touches_migrations(call, ctx, **with_):
    return call.args.get("path", "").startswith("app/migrations/")
"""

_RAISING_PLUGIN = """
from docket.governance.plugin_api import predicate


@predicate("boom")
def boom(call, ctx, **with_):
    raise RuntimeError("boom")
"""


def _write_policy(policies_dir: Path, name: str, doc: object) -> None:
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / name).write_text(json.dumps(doc), encoding="utf-8")


class TestGlobalPluginDrivesAPolicy:
    def test_a_global_plugin_returning_true_makes_ask_fire(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with use_home(Home(home)):
            plugins_dir = home / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "migrations.py").write_text(_MIGRATION_PLUGIN, encoding="utf-8")

            _write_policy(
                home / "policies",
                "touches-migrations.json",
                {
                    "kind": "policy",
                    "name": "touches-migrations",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"plugin": "touches_migrations"},
                    "then": "ask",
                },
            )

            call = _policy.ToolCallFacts("write", {"path": "app/migrations/0002.py"}, lambda: "")
            hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
            assert hit.action == "require_approval"
            assert hit.policy_id == "touches-migrations"


class TestUnappliedPluginFailsClosed:
    def test_a_plugin_only_under_a_codebase_is_absent_and_the_policy_blocks(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        with use_home(Home(home)):
            # Present only in a codebase's own .docket/plugins/ -- never a scope `discover` reads.
            codebase_plugins = tmp_path / "codebase" / ".docket" / "plugins"
            codebase_plugins.mkdir(parents=True)
            (codebase_plugins / "migrations.py").write_text(_MIGRATION_PLUGIN, encoding="utf-8")

            assert "touches_migrations" not in _plugins.discover()

            _write_policy(
                home / "policies",
                "touches-migrations.json",
                {
                    "kind": "policy",
                    "name": "touches-migrations",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"plugin": "touches_migrations"},
                    "then": "ask",
                },
            )

            call = _policy.ToolCallFacts("write", {"path": "app/migrations/0002.py"}, lambda: "")
            hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
            assert hit.action == "block"
            assert "touches_migrations" in hit.message
            assert "not applied" in hit.message


class TestARaisingPluginFailsClosedAndAudits:
    def test_a_raising_plugin_blocks_and_audits_one_deny(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with use_home(Home(home)):
            plugins_dir = home / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "boom.py").write_text(_RAISING_PLUGIN, encoding="utf-8")

            _write_policy(
                home / "policies",
                "boom.json",
                {
                    "kind": "policy",
                    "name": "boom-policy",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"plugin": "boom"},
                    "then": "allow",
                },
            )

            call = _policy.ToolCallFacts("write", {"path": "x.py"}, lambda: "")
            hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
            assert hit.action == "block"
            assert "boom" in hit.message

            entries = [e for e in _audit.read_audit() if e.get("action") == "policy.plugin"]
            assert len(entries) == 1
            assert "verdict=deny" in entries[0]["detail"]
