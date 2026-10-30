"""`teams/pod.py`'s role model resolves against the archetype registry
instead of a hardcoded 4-tuple — `normalize_role`/`member_id`
must keep returning the exact same values for the four legacy roles, while
also accepting a starter-library/user-defined role without a single new
hardcoded string in `teams/pod.py`.

Also covers `teams/model_selection.py`'s archetype-modelClass fallback (a role
with no named `ALL_ROLES` row resolves through its own `modelClass` against
the live rank anchors) and an end-to-end `docket pod add
<starter-role>` provisioning smoke test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.cli import invoke_pod
from tests.support.pods import build_pod
from tests.support.pods import ids as _ids
from tests.support.pods import seed_empty_home as _seed

from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import pod_members as _pod_members
from docket.kernel.home import Home, current_home, use_home
from docket.teams import model_selection as _mp
from docket.teams import pod
from docket.teams import roles as _arch

SUBJECT = "docket.teams.pod"


class TestNormalizeRoleAgainstRegistry:
    def test_builtin_roles_normalize(self) -> None:
        for role in ("lead", "implementer", "reviewer"):
            assert pod.normalize_role(role) == role

    def test_starter_role_accepted(self) -> None:
        assert pod.normalize_role("researcher") == "researcher"
        assert pod.normalize_role("MONITOR") == "monitor"

    def test_unknown_role_still_rejected(self) -> None:
        with pytest.raises(pod.PodError, match="unknown pod role"):
            pod.normalize_role("wizard")

    def test_user_defined_role_accepted_after_overlay_add(self, tmp_path: Path) -> None:
        with pytest.raises(pod.PodError):
            pod.normalize_role("producer", "shop")

        _arch.add_user_archetype(
            {
                "name": "producer",
                "version": 1,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "hi ${project}",
                "agentsTemplate": "hi ${project}",
                "gateContract": {"kind": "none"},
                "toolProfile": "x",
            },
            "shop",
        )
        assert pod.normalize_role("producer", "shop") == "producer"
        with pytest.raises(pod.PodError):
            pod.normalize_role("producer", "other")


class TestMemberIdUnaffected:
    def test_member_id_matches_legacy_shape(self) -> None:
        assert pod.member_id("shop", "implementer", 1) == "shop-implementer"
        assert pod.member_id("shop", "implementer", 2) == "shop-implementer-2"
        assert pod.member_id("shop", "lead") == "shop-lead"

    def test_parse_member_id_accepts_starter_role(self) -> None:
        assert pod.parse_member_id("shop-researcher", "shop") == ("researcher", 1)

    def test_parse_member_id_still_rejects_unknown(self) -> None:
        assert pod.parse_member_id("shop-wizard", "shop") is None

    def test_pod_of_still_works_for_legacy_and_starter(self) -> None:
        assert pod.pod_of("demo-lead") == "demo"
        assert pod.pod_of("demo-researcher") == "demo"
        assert pod.pod_of("demo-wizard") is None


class TestRegistryRoleNames:
    def test_registry_role_names_include_legacy_and_starter(self) -> None:
        names = set(_arch.load_registry().role_names())
        assert {"lead", "implementer", "reviewer"} <= names
        assert {"researcher", "analyst", "writer", "operator", "monitor"} <= names


class TestModelClassFallback:
    def test_legacy_roles_resolve_through_named_policy_row(self) -> None:
        role_models = {
            "lead": "anthropic/claude-haiku-4-5",
            "implementer": "anthropic/claude-sonnet-4-6",
            "reviewer": "anthropic/claude-haiku-4-5",
        }
        assert _mp.resolve_role_model("lead", role_models) == "anthropic/claude-haiku-4-5"
        assert _mp.resolve_role_model("implementer", role_models) == "anthropic/claude-sonnet-4-6"

    def test_unlisted_cheap_archetype_resolves_via_economy_anchor(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path)):
            _, tiers, _ = _mp.load_registry()
            # 'monitor' is a starter-library role with modelClass=cheap and no named
            # ALL_ROLES row — it must resolve through the economy anchor, not
            # Home.default_model unconditionally.
            assert _mp.resolve_role_model("monitor", {}) == tiers["economy"]

    def test_unlisted_strong_archetype_resolves_via_standard_anchor(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path)):
            _, tiers, _ = _mp.load_registry()
            assert _mp.resolve_role_model("researcher", {}) == tiers["standard"]

    def test_totally_unknown_role_falls_back_to_default_model(self, tmp_path: Path) -> None:
        with use_home(Home(tmp_path)):
            assert _mp.resolve_role_model("totally-not-a-role", {}) == current_home().default_model


class TestPodAddStarterRole:
    def test_add_researcher_provisions_full_workspace(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
            _pod_members.add_members("demo", "researcher")

            assert "demo-researcher" in _ids(oc_dir)
            ws = oc_dir / "state" / "workspaces" / "projects" / "demo-researcher"
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
            assert meta["model"] == current_home().default_model

    def test_pod_show_lists_the_added_researcher(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
            build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
            _pod_members.add_members("demo", "researcher")
            capsys.readouterr()

            result = invoke_pod(["show", "--pod", "demo", "--json"])
            assert result.exit_code == 0, result.output
            roles = [m["role"] for m in json.loads(result.stdout)["members"]]
            assert "researcher" in roles

    def test_members_of_lists_researcher_after_legacy_roles(self, tmp_path: Path) -> None:
        with _seed(tmp_path) as oc_dir:
            build_pod("demo", _pod.pod.FULL_POD_ROLES)
            _pod_members.add_members("demo", "researcher")
            all_ids = _ids(oc_dir)
            members = pod.members_of(all_ids, "demo")
            roles_in_order = [role for _mid, role, _idx in members]
            assert roles_in_order == ["lead", "implementer", "reviewer", "researcher"]
