"""M2 tests: data layer — models, store, fleet registry, _json bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_fleet(home: Path) -> Path:
    """Write a minimal fleet.json and return its path.

    Agent registration and channel bindings live here — fleet.json is
    docket's only registry; there is no openclaw.json.
    """
    fleet = {
        "agents": [{"id": "myshop"}],
        "bindings": [
            {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
        ],
        "defaults": {"model": "anthropic/claude-sonnet-4-6"},
        "security": {"gatesEnabled": False, "isolationEnabled": False},
    }
    path = home / "fleet.json"
    path.write_text(json.dumps(fleet, indent=2))
    return path


def _make_meta(workspace: Path, overrides: dict | None = None) -> Path:
    """Write a .docket-meta.json in *workspace*."""
    workspace.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "project",
        "type": "repo",
        "name": "My Shop",
        "codebase": "/home/user/myshop",
        "stack": "Docker,git",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": "agent:myshop:default",
        "projectKey": "default",
        "templateVersion": "3",
    }
    if overrides:
        data.update(overrides)
    path = workspace / ".docket-meta.json"
    path.write_text(json.dumps(data, indent=2))
    return path


# ── T2.1: AgentMeta ────────────────────────────────────────────────────────────


class TestAgentMeta:
    def test_round_trip_camel_case(self) -> None:
        from docket.core.models import AgentKind, AgentMeta

        raw = {
            "kind": "project",
            "type": "repo",
            "name": "My Shop",
            "model": "anthropic/claude-haiku-4-5",
            "modelSource": "pinned",
            "sessionKey": "agent:x:y",
            "projectKey": "y",
            "budgetUsd": 10.0,
        }
        meta = AgentMeta.model_validate(raw)
        assert meta.kind == AgentKind.project
        assert meta.model_source.value == "pinned"
        assert meta.session_key == "agent:x:y"
        assert meta.budget_usd == 10.0
        # Round-trip: dump with aliases produces camelCase keys
        dumped = meta.model_dump(by_alias=True)
        assert "modelSource" in dumped
        assert "sessionKey" in dumped

    def test_extra_fields_survive_round_trip(self) -> None:
        from docket.core.models import AgentMeta

        raw = {"kind": "specialist", "role": "programmer", "futureField": "x"}
        meta = AgentMeta.model_validate(raw)
        dumped = meta.model_dump(by_alias=True)
        assert dumped.get("futureField") == "x"

    def test_schema_version_defaults(self) -> None:
        from docket.core.models import SCHEMA_VERSION, AgentMeta

        meta = AgentMeta.model_validate({"kind": "specialist", "role": "reviewer"})
        assert meta.schema_version == SCHEMA_VERSION

    def test_specialist_kind(self) -> None:
        from docket.core.models import AgentKind, AgentMeta

        meta = AgentMeta.model_validate({"kind": "specialist", "role": "security"})
        assert meta.kind == AgentKind.specialist
        assert meta.role == "security"

    # ── the scope axis ──────────────────────────────────────

    def test_scope_round_trips_when_explicit(self) -> None:
        from docket.core.models import AgentMeta, AgentScope

        meta = AgentMeta.model_validate({"kind": "project", "type": "repo", "scope": "project"})
        assert meta.scope == AgentScope.project
        assert meta.model_dump(by_alias=True)["scope"] == "project"

    def test_scope_explicit_value_is_respected_over_inference(self) -> None:
        # A specialist explicitly marked org stays org even if its role would
        # otherwise infer project — explicit always wins.
        from docket.core.models import AgentMeta, AgentScope

        meta = AgentMeta.model_validate(
            {"kind": "specialist", "role": "programmer", "scope": "org"}
        )
        assert meta.scope == AgentScope.org

    def test_scope_rejects_unknown_value(self) -> None:
        from pydantic import ValidationError

        from docket.core.models import AgentMeta

        with pytest.raises(ValidationError):
            AgentMeta.model_validate({"kind": "project", "scope": "global"})

    def test_scope_backfill_project_agent(self) -> None:
        from docket.core.models import AgentMeta, AgentScope

        meta = AgentMeta.model_validate({"kind": "project"})
        assert meta.scope == AgentScope.project

    def test_scope_backfill_org_specialist(self) -> None:
        # security/knowledge (and, for now, manager) are cross-cutting → org.
        from docket.core.models import AgentMeta, AgentScope

        for role in ("security", "knowledge", "manager"):
            meta = AgentMeta.model_validate({"kind": "specialist", "role": role})
            assert meta.scope == AgentScope.org, role

    def test_scope_backfill_project_specialist(self) -> None:
        # programmer/reviewer/tester become per-pod project workers → project.
        from docket.core.models import AgentMeta, AgentScope

        for role in ("programmer", "reviewer", "tester"):
            meta = AgentMeta.model_validate({"kind": "specialist", "role": role})
            assert meta.scope == AgentScope.project, role


# ── T2.2: fleet models ────────────────────────────────────────


class TestFleetConfig:
    """core/fleet.py's FleetConfig -- docket's own agent/binding registry."""

    def test_parse_fixture(self, tmp_path: Path) -> None:
        from docket.core.fleet import FleetConfig

        raw = json.loads(_make_fleet(tmp_path).read_text())
        cfg = FleetConfig.model_validate(raw)
        assert len(cfg.agents) == 1
        assert cfg.agents[0].id == "myshop"
        assert cfg.defaults.model == "anthropic/claude-sonnet-4-6"
        assert len(cfg.bindings) == 1
        assert cfg.bindings[0].agent_id == "myshop"
        assert not cfg.security.gates_enabled

    def test_extra_fields_survive(self) -> None:
        from docket.core.fleet import FleetConfig

        raw = {
            "agents": [],
            "bindings": [],
            "security": {"gatesEnabled": False},
            "newTopLevelKey": 42,
        }
        cfg = FleetConfig.model_validate(raw)
        dumped = cfg.model_dump(by_alias=True)
        assert dumped["newTopLevelKey"] == 42

    # Auth-profiles were a daemon-owned concept with no docket-native
    # replacement -- deleted outright, not moved. See cli/_keys.py's
    # run_auth for the honest "gone" message this capability now surfaces.


# ── T2.3: store ────────────────────────────────────────────────────────────────


class TestStore:
    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        from docket.edges import store

        assert store.read_json(tmp_path / "nope.json") == {}

    def test_write_creates_file_with_correct_perms(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"key": "value"})
        assert path.exists()
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)
        assert json.loads(path.read_text()) == {"key": "value"}

    def test_write_creates_bak(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"v": 1})
        store.write_json(path, {"v": 2})
        bak = path.with_suffix(".json.bak")
        assert bak.exists()
        assert json.loads(bak.read_text()) == {"v": 1}

    def test_write_accepts_pydantic_model(self, tmp_path: Path) -> None:
        from docket.core.models import AgentMeta
        from docket.edges import store

        meta = AgentMeta.model_validate({"kind": "specialist", "role": "programmer"})
        path = tmp_path / "meta.json"
        store.write_json(path, meta)
        raw = json.loads(path.read_text())
        # Pydantic model serialises with camelCase aliases
        assert raw["role"] == "programmer"

    # ── R-1: read_modify_write / with_lock (the locked-claim primitive) ──────────

    def test_read_modify_write_mutates_and_persists(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"count": 1})

        def _bump(doc: dict) -> dict:
            doc["count"] = doc.get("count", 0) + 1
            return doc

        result = store.read_modify_write(path, _bump)
        assert result == {"count": 2}
        assert json.loads(path.read_text()) == {"count": 2}

    def test_read_modify_write_on_missing_file_starts_from_empty_dict(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "nope.json"
        seen: dict = {}

        def _fn(doc: dict) -> dict:
            seen.update(doc)
            return {"created": True}

        result = store.read_modify_write(path, _fn)
        assert seen == {}  # missing file reads as {}, not an error
        assert result == {"created": True}
        assert json.loads(path.read_text()) == {"created": True}

    def test_read_modify_write_none_aborts_without_writing(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"v": 1})
        mtime_before = path.stat().st_mtime_ns

        result = store.read_modify_write(path, lambda _doc: None)
        assert result == {"v": 1}  # unmodified contents returned
        assert path.stat().st_mtime_ns == mtime_before  # file genuinely untouched

    def test_read_modify_write_sets_perms_and_bak(self, tmp_path: Path) -> None:
        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"v": 1})
        store.read_modify_write(path, lambda doc: {"v": 2})
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)
        bak = path.with_suffix(".json.bak")
        assert json.loads(bak.read_text()) == {"v": 1}

    def test_with_lock_serialises_a_concurrent_writer(self, tmp_path: Path) -> None:
        """A write_json call made while with_lock holds the lock waits — it never
        interleaves and corrupts the file; it just blocks until the lock is free."""
        import threading
        import time

        from docket.edges import store

        path = tmp_path / "test.json"
        store.write_json(path, {"v": 0})
        order: list[str] = []

        def _writer() -> None:
            order.append("writer-start")
            store.write_json(path, {"v": 1})
            order.append("writer-done")

        with store.with_lock(path):
            order.append("lock-held")
            t = threading.Thread(target=_writer)
            t.start()
            time.sleep(0.1)  # give the writer a chance to run — it must still be blocked
            assert order == ["lock-held", "writer-start"]
        t.join(timeout=5)
        assert order == ["lock-held", "writer-start", "writer-done"]
        assert json.loads(path.read_text()) == {"v": 1}


# ── T2.4: ACL ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def oc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temp DOCKET_HOME with fleet.json and a project workspace."""
    home = tmp_path / ".docket"
    home.mkdir()
    workspace = home / "workspaces" / "projects" / "myshop"
    _make_meta(workspace)
    fleet_file = _make_fleet(home)  # writes home/fleet.json

    monkeypatch.setenv("DOCKET_HOME", str(home))

    import docket.config as _cfg

    projects_dir = home / "workspaces" / "projects"
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home)
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json")
    return home


class TestFleet:
    """core/fleet.py, replacing the deleted edges/adapters/openclaw.py ACL.

    oc_get_path/oc_set_path had no fleet.py successor: fleet.json is read
    through a validated Pydantic model now, not raw dotted-path string
    lookups, so there is nothing to round-trip a dotted path through.
    """

    def test_list_agents(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        agents = _fleet.list_agents()
        assert len(agents) == 1
        assert agents[0].id == "myshop"

    def test_agent_registered_true(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert _fleet.agent_registered("myshop")

    def test_agent_registered_false(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert not _fleet.agent_registered("nobody")

    def test_get_agent(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        agent = _fleet.get_agent("myshop")
        assert agent is not None
        assert agent.id == "myshop"
        # The fleet registry tracks bare registration only — model and
        # sessionKey are .docket-meta.json's job (core/fleet.py's rationale).
        assert not hasattr(agent, "model")
        assert _fleet.meta_get("myshop", "sessionKey") == "agent:myshop:default"

    def test_add_remove_agent(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        _fleet.add_agent("newbot", "anthropic/claude-haiku-4-5", "agent:newbot:proj")
        assert _fleet.agent_registered("newbot")
        _fleet.remove_agent("newbot")
        assert not _fleet.agent_registered("newbot")

    def test_add_agent_idempotent(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        _fleet.add_agent("myshop", "anthropic/claude-haiku-4-5")
        # Should not duplicate
        assert len(_fleet.list_agents()) == 1

    def test_get_binding(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        peer_id = _fleet.get_binding("myshop")
        assert peer_id == "-999"

    def test_get_binding_missing(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert _fleet.get_binding("nobody") == ""

    def test_upsert_and_remove_binding(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        _fleet.upsert_binding("myshop", "-1001234567890")
        assert _fleet.get_binding("myshop") == "-1001234567890"
        _fleet.remove_binding("myshop")
        assert _fleet.get_binding("myshop") == ""

    def test_security_gates(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert not _fleet.get_gates_enabled()
        _fleet.set_gates_enabled(True)
        assert _fleet.get_gates_enabled()

    def test_isolation(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert not _fleet.get_isolation_enabled()
        _fleet.set_isolation_enabled(True)
        assert _fleet.get_isolation_enabled()

    def test_default_model(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        assert _fleet.get_default_model() == "anthropic/claude-sonnet-4-6"
        _fleet.set_default_model("anthropic/claude-haiku-4-5")
        assert _fleet.get_default_model() == "anthropic/claude-haiku-4-5"

    def test_meta_get_set(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        val = _fleet.meta_get("myshop", "name")
        assert val == "My Shop"
        _fleet.meta_set("myshop", "name", "Updated Shop")
        assert _fleet.meta_get("myshop", "name") == "Updated Shop"

    def test_meta_get_default(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        val = _fleet.meta_get("myshop", "nonexistent", "fallback")
        assert val == "fallback"

    def test_meta_read(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet
        from docket.core.models import AgentKind

        meta = _fleet.meta_read("myshop")
        assert meta.kind == AgentKind.project
        assert meta.name == "My Shop"

    def test_set_model_both(self, oc_env: Path) -> None:
        from docket.core import fleet as _fleet

        _fleet.set_model_both("myshop", "anthropic/claude-haiku-4-5")
        assert _fleet.meta_get("myshop", "model") == "anthropic/claude-haiku-4-5"


# core/sync.py (meta<->openclaw.json drift check) does not exist -- with
# fleet.json as the single source of truth for registration/bindings/gates/
# defaults, and .docket-meta.json the single source for model/sessionKey,
# there is nothing left to drift between.

# ── T2.6: _json bridge (CLI) ──────────────────────────────────────────────────


class TestJsonBridge:
    """Test the _json CLI command end-to-end via subprocess."""

    @pytest.fixture(autouse=True)
    def _patch_env(self, oc_env: Path, tmp_path: Path) -> None:
        os.environ["DOCKET_HOME"] = str(oc_env)

    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, "-m", "docket", "_json", *args],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DOCKET_HOME": os.environ["DOCKET_HOME"],
            },
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def test_meta_get(self) -> None:
        rc, out, _ = self._run("meta-get", "myshop", "name")
        assert rc == 0
        assert out == "My Shop"

    def test_meta_get_default(self) -> None:
        rc, out, _ = self._run("meta-get", "myshop", "nofield", "fallback")
        assert rc == 0
        assert out == "fallback"

    def test_meta_set(self) -> None:
        rc, _, _ = self._run("meta-set", "myshop", "description", "New desc")
        assert rc == 0
        rc2, out, _ = self._run("meta-get", "myshop", "description")
        assert rc2 == 0
        assert out == "New desc"

    def test_agent_registered_yes(self) -> None:
        rc, out, _ = self._run("agent-registered", "myshop")
        assert rc == 0
        assert out == "1"

    def test_agent_registered_no(self) -> None:
        rc, out, _ = self._run("agent-registered", "ghost")
        assert rc == 1
        assert out == "0"

    def test_binding_get(self) -> None:
        rc, out, _ = self._run("binding-get", "myshop")
        assert rc == 0
        assert out == "-999"

    def test_binding_get_missing(self) -> None:
        rc, out, _ = self._run("binding-get", "nobody")
        assert rc == 0
        assert out == ""

    # test_oc_get/test_oc_get_missing deleted: the "oc-get" verb read raw
    # openclaw.json dotted paths through the now-deleted ACL and has no
    # successor in the _json bridge (fleet.json is read through a validated
    # model, not dotted-path string lookups).

    def test_gates_get_false(self) -> None:
        rc, out, _ = self._run("gates-get")
        assert rc == 0
        assert out == "false"

    def test_gates_set_true(self) -> None:
        self._run("gates-set", "true")
        _rc, out, _ = self._run("gates-get")
        assert out == "true"

    def test_unknown_verb_exits_2(self) -> None:
        rc, _, err = self._run("nonexistent-verb")
        assert rc == 2
        assert "unknown verb" in err
