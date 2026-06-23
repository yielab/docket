"""AA-3: pod composition model (core/pod.py) — pure-logic unit tests."""

from __future__ import annotations

import pytest

from docket.core import pod

# A fixed role→model map so tests don't depend on the live registry.
_MODELS = {
    "manager": "anthropic/claude-haiku-4-5",
    "programmer": "anthropic/claude-sonnet-4-6",
    "reviewer": "anthropic/claude-haiku-4-5",
    "tester": "anthropic/claude-haiku-4-5",
}


class TestMemberId:
    def test_first_of_role_is_bare(self) -> None:
        assert pod.member_id("shop", "implementer", 1) == "shop-implementer"

    def test_duplicate_is_indexed(self) -> None:
        assert pod.member_id("shop", "implementer", 2) == "shop-implementer-2"

    def test_parse_round_trip(self) -> None:
        assert pod.parse_member_id("shop-implementer", "shop") == ("implementer", 1)
        assert pod.parse_member_id("shop-implementer-2", "shop") == ("implementer", 2)
        assert pod.parse_member_id("shop-lead", "shop") == ("lead", 1)

    def test_parse_rejects_foreign_or_unknown(self) -> None:
        assert pod.parse_member_id("other-lead", "shop") is None
        assert pod.parse_member_id("shop-wizard", "shop") is None
        assert pod.parse_member_id("shop", "shop") is None


class TestNormalizeRole:
    def test_programmer_aliases_to_implementer(self) -> None:
        assert pod.normalize_role("programmer") == "implementer"
        assert pod.normalize_role("Implementer") == "implementer"

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(pod.PodError):
            pod.normalize_role("wizard")


class TestDefaultPod:
    def test_lean_default_is_lead_plus_implementer(self) -> None:
        members = pod.plan_pod("shop", role_models=_MODELS)
        assert [m.member_id for m in members] == ["shop-lead", "shop-implementer"]
        assert [m.role for m in members] == ["lead", "implementer"]

    def test_lead_gets_coordination_model_implementer_gets_codegen(self) -> None:
        members = {m.role: m for m in pod.plan_pod("shop", role_models=_MODELS)}
        # Lead → manager policy (cheap), Implementer → programmer policy (strong).
        assert members["lead"].model == _MODELS["manager"]
        assert members["implementer"].model == _MODELS["programmer"]

    def test_all_members_share_session_key(self) -> None:
        members = pod.plan_pod("shop", role_models=_MODELS)
        keys = {m.session_key for m in members}
        assert keys == {"agent:shop:default"}

    def test_full_pod_has_four_roles(self) -> None:
        members = pod.plan_pod("shop", pod.FULL_POD_ROLES, role_models=_MODELS)
        assert [m.role for m in members] == ["lead", "implementer", "reviewer", "tester"]


class TestDuplicateRoles:
    def test_two_implementers_in_plan_are_indexed(self) -> None:
        members = pod.plan_pod("shop", ("lead", "implementer", "implementer"), role_models=_MODELS)
        ids = [m.member_id for m in members]
        assert ids == ["shop-lead", "shop-implementer", "shop-implementer-2"]

    def test_second_lead_in_plan_rejected(self) -> None:
        with pytest.raises(pod.PodError):
            pod.plan_pod("shop", ("lead", "lead"), role_models=_MODELS)


class TestAddMember:
    def test_add_second_implementer_gets_index_2(self) -> None:
        existing = ["shop-lead", "shop-implementer"]
        m = pod.plan_added_member("shop", "implementer", existing, role_models=_MODELS)
        assert m.member_id == "shop-implementer-2"

    def test_add_fills_lowest_free_index(self) -> None:
        existing = ["shop-lead", "shop-implementer", "shop-implementer-3"]
        m = pod.plan_added_member("shop", "implementer", existing, role_models=_MODELS)
        assert m.member_id == "shop-implementer-2"

    def test_add_first_reviewer_is_bare(self) -> None:
        existing = ["shop-lead", "shop-implementer"]
        m = pod.plan_added_member("shop", "reviewer", existing, role_models=_MODELS)
        assert m.member_id == "shop-reviewer"

    def test_add_second_lead_rejected(self) -> None:
        existing = ["shop-lead", "shop-implementer"]
        with pytest.raises(pod.PodError):
            pod.plan_added_member("shop", "lead", existing, role_models=_MODELS)

    def test_next_index_ignores_other_projects(self) -> None:
        existing = ["shop-implementer", "other-implementer", "other-implementer-2"]
        assert pod.next_index(existing, "shop", "implementer") == 2
