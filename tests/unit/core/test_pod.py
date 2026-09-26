"""Pod composition model (core/pod.py) — pure-logic unit tests."""

from __future__ import annotations

import pytest

import docket.config as _cfg
from docket.core import pod
from docket.edges import store as _store

SUBJECT = "docket.core.pod"


def _write_meta(member_id: str, pod_name: str, role: str = "") -> None:
    """Seed just enough of `.docket-meta.json` for `pod_of`'s meta-first read."""
    path = _cfg.meta_path(member_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(
        path,
        {"schemaVersion": 1, "kind": "project", "scope": "project", "role": role, "pod": pod_name},
    )


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


class TestPodOf:
    def test_resolves_member_to_project(self) -> None:
        assert pod.pod_of("demo-lead") == "demo"
        assert pod.pod_of("demo-implementer-2") == "demo"
        assert pod.pod_of("my-shop-reviewer") == "my-shop"

    def test_non_pod_ids_return_none(self) -> None:
        assert pod.pod_of("myshop") is None  # legacy single agent, no dash
        assert pod.pod_of("my-api") is None  # 'api' is not a pod role
        assert pod.pod_of("manager") is None  # org specialist

    def test_meta_wins_when_a_custom_role_name_ends_in_a_registered_role(self) -> None:
        # 'proj-security-reviewer' string-parses as role 'reviewer' of project
        # 'proj-security' -- wrong. Recorded meta is authoritative.
        _write_meta("proj-security-reviewer", "proj", role="security-reviewer")
        assert pod.pod_of("proj-security-reviewer") == "proj"

    def test_falls_back_to_string_parsing_with_no_meta(self) -> None:
        # No .docket-meta.json on disk for this id -- unchanged legacy behavior.
        assert pod.pod_of("demo-lead") == "demo"

    def test_falls_back_to_string_parsing_when_meta_has_no_pod_field(self) -> None:
        path = _cfg.meta_path("demo-lead")
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(path, {"schemaVersion": 1, "kind": "project", "role": "lead"})
        assert pod.pod_of("demo-lead") == "demo"

    def test_alien_id_still_refused_even_with_unrelated_meta_present(self) -> None:
        _write_meta("proj-security-reviewer", "proj", role="security-reviewer")
        assert pod.pod_of("some-other-agent") is None


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

    def test_all_members_share_base_metadata_session_key(self) -> None:
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


def _write_lead_meta(project: str, fields: dict[str, object] | None = None) -> None:
    """Seed just the pod Lead's meta keys ``PodSettings`` reads."""
    path = _cfg.meta_path(pod.member_id(project, "lead"))
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"schemaVersion": 1, "kind": "project", "scope": "project"}
    if fields:
        data.update(fields)
    _store.write_json(path, data)


class TestPodSettings:
    def test_defaults_when_nothing_stored(self) -> None:
        _write_lead_meta("shop")
        settings = pod.PodSettings.load_for("shop")
        assert settings.budget_usd == 0.0
        assert settings.max_rework_cycles == 1
        assert settings.turn_timeout_s is None
        assert settings.verify_timeout_s is None

    def test_accepts_numeric_strings_from_existing_installs(self) -> None:
        _write_lead_meta(
            "shop",
            {
                "budgetUsd": "5",
                "maxReworkCycles": "2",
                "turnTimeoutS": "45",
                "verifyTimeoutS": "600",
            },
        )
        settings = pod.PodSettings.load_for("shop")
        assert (settings.budget_usd, settings.max_rework_cycles) == (5.0, 2)
        assert (settings.turn_timeout_s, settings.verify_timeout_s) == (45, 600)

    def test_invalid_stored_value_names_the_key(self) -> None:
        _write_lead_meta("shop", {"turnTimeoutS": "not-a-number"})
        with pytest.raises(pod.PodSettingsError, match="turnTimeoutS"):
            pod.PodSettings.load_for("shop")

    def test_negative_max_rework_cycles_is_invalid(self) -> None:
        _write_lead_meta("shop", {"maxReworkCycles": "-1"})
        with pytest.raises(pod.PodSettingsError, match="maxReworkCycles"):
            pod.PodSettings.load_for("shop")

    def test_coerce_accepts_a_valid_value(self) -> None:
        assert pod.PodSettings.coerce("turnTimeoutS", "90") == 90

    def test_coerce_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(pod.PodSettingsError, match="turnTimeoutS"):
            pod.PodSettings.coerce("turnTimeoutS", "0")

    def test_coerce_rejects_unknown_key(self) -> None:
        with pytest.raises(pod.PodSettingsError, match="unknown"):
            pod.PodSettings.coerce("approvalMode", "x")

    def test_value_and_source_reports_set_vs_default(self) -> None:
        _write_lead_meta("shop", {"maxReworkCycles": "3"})
        settings = pod.PodSettings.load_for("shop")
        assert settings.value_and_source("maxReworkCycles", "shop") == (3, "set")
        assert settings.value_and_source("budgetUsd", "shop") == (0.0, "default")


class TestPodSettingsAllowCommands:
    """`PodSettings.allowCommands`: a pod's own extra unattended binaries."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod.PodSettings.load_for("shop").allow_commands == ()

    def test_parses_and_dedupes_a_comma_separated_list(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "pytest, uv, pytest"})
        assert pod.PodSettings.load_for("shop").allow_commands == ("pytest", "uv")

    def test_a_bin_already_on_safe_bins_is_silently_dropped(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "pytest, ls"})
        assert pod.PodSettings.load_for("shop").allow_commands == ("pytest",)

    def test_rejects_a_path(self) -> None:
        with pytest.raises(pod.PodSettingsError, match="allowCommands"):
            pod.PodSettings.coerce("allowCommands", "./pytest")

    def test_rejects_a_shell_metacharacter(self) -> None:
        with pytest.raises(pod.PodSettingsError, match="allowCommands"):
            pod.PodSettings.coerce("allowCommands", "pytest;rm")

    @pytest.mark.parametrize("name", ["eval", "exec", "source", ".", "export"])
    def test_rejects_opaque_or_scope_changing_names(self, name: str) -> None:
        with pytest.raises(pod.PodSettingsError, match="allowCommands"):
            pod.PodSettings.coerce("allowCommands", name)

    def test_rejects_a_high_risk_class_bin(self) -> None:
        with pytest.raises(pod.PodSettingsError, match="allowCommands"):
            pod.PodSettings.coerce("allowCommands", "git")

    def test_coerce_returns_the_canonical_comma_joined_form(self) -> None:
        assert pod.PodSettings.coerce("allowCommands", "uv, pytest") == "uv,pytest"

    def test_value_and_source_reports_the_joined_string(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "pytest,uv"})
        settings = pod.PodSettings.load_for("shop")
        assert settings.value_and_source("allowCommands", "shop") == ("pytest,uv", "set")
