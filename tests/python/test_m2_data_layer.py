"""M2 tests: data layer — models, store, ACL, sync, _json bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_openclaw(tmp_path: Path) -> Path:
    """Write a minimal openclaw.json and return its path."""
    oc = {
        "agents": {
            "defaults": {"model": "anthropic/claude-sonnet-4-6"},
            "list": [
                {
                    "id": "myshop",
                    "model": "anthropic/claude-sonnet-4-6",
                    "metadata": {
                        "sessionKey": "agent:myshop:default",
                        "projectKey": "default",
                    },
                },
            ],
        },
        "bindings": [
            {
                "agentId": "myshop",
                "match": {
                    "channel": "telegram",
                    "peer": {"kind": "group", "id": "-999"},
                },
            }
        ],
        "security": {
            "gates": {"enabled": False},
            "isolation": {"enabled": False},
        },
    }
    path = tmp_path / "openclaw.json"
    path.write_text(json.dumps(oc, indent=2))
    return path


def _make_fleet(oc_dir: Path) -> Path:
    """Write a minimal fleet.json (P19-6) and return its path.

    Mirrors _make_openclaw's registration/binding content — agent
    registration and channel bindings live here now, not in openclaw.json.
    """
    fleet = {
        "agents": [{"id": "myshop"}],
        "bindings": [
            {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-999"}
        ],
        "defaults": {"model": "anthropic/claude-sonnet-4-6"},
        "security": {"gatesEnabled": False, "isolationEnabled": False},
    }
    path = oc_dir / "fleet.json"
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

    # ── AA-1: the scope axis (Phase 10) ──────────────────────────────────────

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


# ── T2.2: fleet + auth-profiles models ────────────────────────────────────────


class TestFleetConfig:
    """ROADMAP Phase 19 P19-6: core/fleet.py's FleetConfig, replacing the
    deleted core/oc_models.py's OpenClawConfig for docket's own registry."""

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

    def test_auth_profiles_parse(self) -> None:
        # Phase 19 P19-6: moved from core/oc_models.py (deleted) into the ACL
        # itself, since it is the only remaining consumer.
        from docket.edges.adapters.openclaw import AuthProfiles

        raw = {
            "profiles": {
                "p1": {"provider": "anthropic", "type": "token"},
            },
            "usageStats": {
                "p1": {"disabledUntil": 0, "disabledReason": ""},
            },
        }
        ap = AuthProfiles.model_validate(raw)
        assert ap.profiles["p1"].provider == "anthropic"
        assert ap.usage_stats["p1"].disabled_until == 0.0


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
    """Set up a temp OPENCLAW_DIR with openclaw.json, fleet.json, and a project workspace."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    workspace = oc_dir / "workspaces" / "projects" / "myshop"
    _make_meta(workspace)
    _make_openclaw(oc_dir)  # writes oc_dir/openclaw.json
    fleet_file = _make_fleet(oc_dir)  # writes oc_dir/fleet.json

    monkeypatch.setenv("OPENCLAW_DIR", str(oc_dir))
    monkeypatch.setenv("DOCKET_HOME", str(oc_dir))
    # Patch both docket.config (where functions read from at call time) AND
    # docket.edges.adapters.openclaw (where CONFIG_FILE was captured at import time).
    import docket.config as _cfg
    import docket.edges.adapters.openclaw as _oc

    config_file = oc_dir / "openclaw.json"
    projects_dir = oc_dir / "workspaces" / "projects"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json")
    # CONFIG_FILE / FLEET_FILE are imported by value into the ACL module — patch there too.
    monkeypatch.setattr(_oc, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_oc, "FLEET_FILE", fleet_file)
    return oc_dir


class TestACL:
    def test_list_agents(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        agents = oc.list_agents()
        assert len(agents) == 1
        assert agents[0].id == "myshop"

    def test_agent_registered_true(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert oc.agent_registered("myshop")

    def test_agent_registered_false(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert not oc.agent_registered("nobody")

    def test_get_agent(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        agent = oc.get_agent("myshop")
        assert agent is not None
        assert agent.id == "myshop"
        # P19-6: the fleet registry tracks bare registration only — model and
        # sessionKey are .docket-meta.json's job (core/fleet.py's rationale).
        assert not hasattr(agent, "model")
        assert oc.meta_get("myshop", "sessionKey") == "agent:myshop:default"

    def test_add_remove_agent(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        oc.add_agent("newbot", "anthropic/claude-haiku-4-5", "agent:newbot:proj")
        assert oc.agent_registered("newbot")
        oc.remove_agent("newbot")
        assert not oc.agent_registered("newbot")

    def test_add_agent_idempotent(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        oc.add_agent("myshop", "anthropic/claude-haiku-4-5")
        # Should not duplicate
        assert len(oc.list_agents()) == 1

    def test_get_binding(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        peer_id = oc.get_binding("myshop")
        assert peer_id == "-999"

    def test_get_binding_missing(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert oc.get_binding("nobody") == ""

    def test_upsert_and_remove_binding(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        oc.upsert_binding("myshop", "-1001234567890")
        assert oc.get_binding("myshop") == "-1001234567890"
        oc.remove_binding("myshop")
        assert oc.get_binding("myshop") == ""

    def test_security_gates(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert not oc.get_gates_enabled()
        oc.set_gates_enabled(True)
        assert oc.get_gates_enabled()

    def test_isolation(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert not oc.get_isolation_enabled()
        oc.set_isolation_enabled(True)
        assert oc.get_isolation_enabled()

    def test_default_model(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert oc.get_default_model() == "anthropic/claude-sonnet-4-6"
        oc.set_default_model("anthropic/claude-haiku-4-5")
        assert oc.get_default_model() == "anthropic/claude-haiku-4-5"

    def test_meta_get_set(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        val = oc.meta_get("myshop", "name")
        assert val == "My Shop"
        oc.meta_set("myshop", "name", "Updated Shop")
        assert oc.meta_get("myshop", "name") == "Updated Shop"

    def test_meta_get_default(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        val = oc.meta_get("myshop", "nonexistent", "fallback")
        assert val == "fallback"

    def test_meta_read(self, oc_env: Path) -> None:
        from docket.core.models import AgentKind
        from docket.edges.adapters import openclaw as oc

        meta = oc.meta_read("myshop")
        assert meta.kind == AgentKind.project
        assert meta.name == "My Shop"

    def test_oc_get_path(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        model = oc.oc_get_path("agents.defaults.model")
        assert model == "anthropic/claude-sonnet-4-6"

    def test_oc_get_path_missing(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        assert oc.oc_get_path("no.such.key", "mydefault") == "mydefault"

    def test_oc_set_path(self, oc_env: Path) -> None:
        # oc_get_path/oc_set_path are raw openclaw.json dotted-path helpers,
        # untouched by P19-6 (openclaw.json stays the daemon's file until
        # P19-7) — round-trip through them alone, not through
        # get_default_model() (fleet.json now, a different file).
        from docket.edges.adapters import openclaw as oc

        oc.oc_set_path("agents.defaults.model", '"anthropic/claude-haiku-4-5"')
        assert oc.oc_get_path("agents.defaults.model") == "anthropic/claude-haiku-4-5"

    def test_set_model_both(self, oc_env: Path) -> None:
        from docket.edges.adapters import openclaw as oc

        oc.set_model_both("myshop", "anthropic/claude-haiku-4-5")
        assert oc.meta_get("myshop", "model") == "anthropic/claude-haiku-4-5"


# P19-6: core/sync.py (meta<->openclaw.json drift check) is deleted, not
# ported — with fleet.json as the single source of truth for registration/
# bindings/gates/defaults, and .docket-meta.json the single source for
# model/sessionKey, there is nothing left to drift between. TestSync (which
# exercised core.sync.check_agent/check_all) is removed along with it.

# ── T2.6: _json bridge (CLI) ──────────────────────────────────────────────────


class TestJsonBridge:
    """Test the _json CLI command end-to-end via subprocess."""

    @pytest.fixture(autouse=True)
    def _patch_env(self, oc_env: Path, tmp_path: Path) -> None:
        os.environ["OPENCLAW_DIR"] = str(oc_env)
        # P19-6: DOCKET_HOME (fleet.json's home) no longer defaults from
        # OPENCLAW_DIR — a real subprocess needs both pinned to the same dir.
        os.environ["DOCKET_HOME"] = str(oc_env)

    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, "-m", "docket", "_json", *args],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "OPENCLAW_DIR": os.environ["OPENCLAW_DIR"],
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

    def test_oc_get(self) -> None:
        rc, out, _ = self._run("oc-get", "agents.defaults.model")
        assert rc == 0
        assert out == "anthropic/claude-sonnet-4-6"

    def test_oc_get_missing(self) -> None:
        rc, out, _ = self._run("oc-get", "no.such.key", "MISSING")
        assert rc == 0
        assert out == "MISSING"

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
