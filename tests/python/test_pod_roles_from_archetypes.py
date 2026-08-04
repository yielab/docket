"""`core/pod.py`'s role model resolves against the archetype registry
instead of a hardcoded 4-tuple — `normalize_role`/`member_id`/`policy_role_for`
must keep returning the exact same values for the four legacy roles, while
also accepting a starter-library/user-defined role without a single new
hardcoded string in `core/pod.py`.

Also covers `core/models_policy.py`'s archetype-modelClass fallback (a role
with no named `ALL_ROLES` row resolves through its own `modelClass` against
the live rank anchors) and an end-to-end `docket pod <project> add
<starter-role>` provisioning smoke test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import archetypes as _arch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import pod


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", home / "docket-roles.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    return home


def _ids(home: Path) -> list[str]:
    # Agent registration lives in fleet.json.
    del home  # kept for call-site compatibility; no longer the source
    return [a.id for a in _fleet.list_agents()]


class TestNormalizeRoleAgainstRegistry:
    def test_legacy_roles_still_normalize(self) -> None:
        for role in ("lead", "implementer", "reviewer", "tester"):
            assert pod.normalize_role(role) == role

    def test_programmer_alias_still_works(self) -> None:
        assert pod.normalize_role("programmer") == "implementer"

    def test_starter_role_accepted(self) -> None:
        assert pod.normalize_role("researcher") == "researcher"
        assert pod.normalize_role("MONITOR") == "monitor"

    def test_unknown_role_still_rejected(self) -> None:
        with pytest.raises(pod.PodError, match="unknown pod role"):
            pod.normalize_role("wizard")

    def test_user_defined_role_accepted_after_overlay_add(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        with pytest.raises(pod.PodError):
            pod.normalize_role("producer")

        _arch.add_user_archetype(
            {
                "name": "producer",
                "version": 1,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "hi ${project}",
                "agentsTemplate": "hi ${project}",
                "gateContract": {"kind": "none"},
                "editRights": "write",
                "toolProfile": "x",
            }
        )
        assert pod.normalize_role("producer") == "producer"


class TestMemberIdUnaffected:
    def test_member_id_matches_legacy_shape(self) -> None:
        assert pod.member_id("shop", "implementer", 1) == "shop-implementer"
        assert pod.member_id("shop", "implementer", 2) == "shop-implementer-2"
        assert pod.member_id("shop", "lead") == "shop-lead"

    def test_parse_member_id_round_trips_for_legacy_roles(self) -> None:
        assert pod.parse_member_id("shop-implementer", "shop") == ("implementer", 1)
        assert pod.parse_member_id("shop-implementer-2", "shop") == ("implementer", 2)
        assert pod.parse_member_id("shop-lead", "shop") == ("lead", 1)

    def test_parse_member_id_accepts_starter_role(self) -> None:
        assert pod.parse_member_id("shop-researcher", "shop") == ("researcher", 1)

    def test_parse_member_id_still_rejects_unknown(self) -> None:
        assert pod.parse_member_id("shop-wizard", "shop") is None

    def test_pod_of_still_works_for_legacy_and_starter(self) -> None:
        assert pod.pod_of("demo-lead") == "demo"
        assert pod.pod_of("demo-researcher") == "demo"
        assert pod.pod_of("demo-wizard") is None


class TestPolicyRoleForLegacyAndStarterRoles:
    def test_legacy_roles_preserve_named_policy_mapping(self) -> None:
        assert pod.policy_role_for("lead") == "manager"
        assert pod.policy_role_for("implementer") == "programmer"
        assert pod.policy_role_for("reviewer") == "reviewer"
        assert pod.policy_role_for("tester") == "tester"

    def test_starter_roles_identity_map(self) -> None:
        assert pod.policy_role_for("researcher") == "researcher"
        assert pod.policy_role_for("monitor") == "monitor"

    def test_registry_role_names_include_legacy_and_starter(self) -> None:
        names = set(_arch.load_registry().role_names())
        assert {"lead", "implementer", "reviewer", "tester"} <= names
        assert {"researcher", "analyst", "writer", "critic", "operator", "monitor"} <= names


class TestModelClassFallback:
    def test_legacy_roles_resolve_through_named_policy_row(self) -> None:
        role_models = {
            "manager": "anthropic/claude-haiku-4-5",
            "programmer": "anthropic/claude-sonnet-4-6",
            "reviewer": "anthropic/claude-haiku-4-5",
            "tester": "anthropic/claude-haiku-4-5",
        }
        assert _mp.resolve_role_model("manager", role_models) == "anthropic/claude-haiku-4-5"
        assert _mp.resolve_role_model("programmer", role_models) == "anthropic/claude-sonnet-4-6"

    def test_unlisted_cheap_archetype_resolves_via_economy_anchor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", tmp_path / "docket-models.json")
        _, tiers, _ = _mp.load_registry()
        # 'monitor' is a starter-library role with modelClass=cheap and no named
        # ALL_ROLES row — it must resolve through the economy anchor, not
        # cfg.DEFAULT_MODEL unconditionally.
        assert _mp.resolve_role_model("monitor", {}) == tiers["economy"]

    def test_unlisted_strong_archetype_resolves_via_standard_anchor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", tmp_path / "docket-models.json")
        _, tiers, _ = _mp.load_registry()
        assert _mp.resolve_role_model("researcher", {}) == tiers["standard"]

    def test_totally_unknown_role_falls_back_to_default_model(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", tmp_path / "docket-models.json")
        assert _mp.resolve_role_model("totally-not-a-role", {}) == _cfg.DEFAULT_MODEL


class TestPodAddStarterRole:
    def test_add_researcher_provisions_full_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _pod.dispatch("demo", "add", ["researcher"])

        assert "demo-researcher" in _ids(oc_dir)
        ws = oc_dir / "workspaces" / "projects" / "demo-researcher"
        assert (ws / "SOUL.md").is_file()
        assert (ws / "AGENTS.md").is_file()
        soul = (ws / "SOUL.md").read_text()
        assert "Researcher" in soul
        assert "demo-researcher" in soul

        meta = json.loads((ws / ".docket-meta.json").read_text())
        assert meta["role"] == "researcher"
        assert meta["pod"] == "demo"
        # researcher is modelClass=strong -> resolves via the 'standard' anchor,
        # same model an implementer (also strong-class) would get by default.
        assert meta["model"] == _cfg.DEFAULT_MODEL or meta["modelSource"] == "policy"

    def test_pod_list_shows_researcher_with_description(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _pod.dispatch("demo", "add", ["researcher"])
        capsys.readouterr()

        _pod.dispatch("demo", "list", [])
        out = capsys.readouterr().out
        assert "researcher" in out
        assert "gathers and synthesizes source material" in out

    def test_members_of_lists_researcher_after_legacy_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        _pod.dispatch("demo", "add", ["researcher"])
        all_ids = _ids(oc_dir)
        members = pod.members_of(all_ids, "demo")
        roles_in_order = [role for _mid, role, _idx in members]
        assert roles_in_order == ["lead", "implementer", "reviewer", "tester", "researcher"]
