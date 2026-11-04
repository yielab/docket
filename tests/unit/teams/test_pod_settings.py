"""Unit coverage for ``teams.apply.plan``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from docket.governance.audit import read_audit
from docket.kernel import mcp as _mcp
from docket.kernel.home import current_home, use_home
from docket.platform import store as _store
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod, pod_settings

SUBJECT = "docket.teams.pod_settings"


def _write_lead_meta(project: str, fields: dict[str, object] | None = None) -> None:
    """Seed just the pod Lead's meta keys ``PodSettings`` reads."""
    path = current_home().meta_path(pod.member_id(project, "lead"))
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "scope": "project"}
    if fields:
        data.update(fields)
    _store.write_json(path, data)


class TestPodSettings:
    def test_defaults_when_nothing_stored(self) -> None:
        _write_lead_meta("shop")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.budget_tokens is None
        assert settings.max_rework_cycles == 1
        assert settings.turn_timeout_s is None
        assert settings.verify_timeout_s is None
        assert settings.approval_mode == "wait"

    def test_approval_mode_refuse_round_trips(self) -> None:
        _write_lead_meta("shop", {"approvalMode": "refuse"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.approval_mode == "refuse"

    def test_invalid_approval_mode_names_the_key(self) -> None:
        _write_lead_meta("shop", {"approvalMode": "sometimes"})
        with pytest.raises(pod_settings.PodSettingsError, match="approvalMode"):
            pod_settings.PodSettings.load_for("shop")

    def test_coerce_names_a_rejected_value_not_a_stored_one(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError) as err:
            pod_settings.PodSettings.coerce("turnTimeoutS", "notanumber")
        assert str(err.value).startswith("turnTimeoutS: invalid value 'notanumber'")
        assert "stored" not in str(err.value)

    @pytest.mark.parametrize("bad", ["0", "-1", "x", "1.5", ""])
    def test_budget_tokens_refuses_what_is_not_a_positive_whole_number(self, bad: str) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="budgetTokens"):
            pod_settings.PodSettings.coerce("budgetTokens", bad)

    def test_budget_tokens_persists_the_validated_integer(self) -> None:
        assert pod_settings.PodSettings.coerce("budgetTokens", "500000") == 500000

    def test_budget_usd_is_refused_naming_budget_tokens(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="budgetTokens"):
            pod_settings.PodSettings.coerce("budgetUsd", "5")

    def test_a_stored_zero_budget_is_unreadable_not_silently_unlimited(self) -> None:
        _write_lead_meta("shop", {"budgetTokens": 0})
        with pytest.raises(pod_settings.PodSettingsError, match="budgetTokens"):
            pod_settings.PodSettings.load_for("shop")

    def test_coerce_accepts_approval_mode(self) -> None:
        assert pod_settings.PodSettings.coerce("approvalMode", "refuse") == "refuse"

    def test_coerce_rejects_invalid_approval_mode(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="approvalMode"):
            pod_settings.PodSettings.coerce("approvalMode", "sometimes")

    def test_accepts_numeric_strings_from_existing_installs(self) -> None:
        _write_lead_meta(
            "shop",
            {
                "budgetTokens": "5000",
                "maxReworkCycles": "2",
                "turnTimeoutS": "45",
                "verifyTimeoutS": "600",
            },
        )
        settings = pod_settings.PodSettings.load_for("shop")
        assert (settings.budget_tokens, settings.max_rework_cycles) == (5000, 2)
        assert (settings.turn_timeout_s, settings.verify_timeout_s) == (45, 600)

    def test_invalid_stored_value_names_the_key(self) -> None:
        _write_lead_meta("shop", {"turnTimeoutS": "not-a-number"})
        with pytest.raises(pod_settings.PodSettingsError, match="turnTimeoutS"):
            pod_settings.PodSettings.load_for("shop")

    def test_negative_max_rework_cycles_is_invalid(self) -> None:
        _write_lead_meta("shop", {"maxReworkCycles": "-1"})
        with pytest.raises(pod_settings.PodSettingsError, match="maxReworkCycles"):
            pod_settings.PodSettings.load_for("shop")

    def test_coerce_accepts_a_valid_value(self) -> None:
        assert pod_settings.PodSettings.coerce("turnTimeoutS", "90") == 90

    def test_coerce_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="turnTimeoutS"):
            pod_settings.PodSettings.coerce("turnTimeoutS", "0")

    def test_coerce_rejects_unknown_key(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="unknown"):
            pod_settings.PodSettings.coerce("definitelyNotARealSetting", "x")

    def test_value_and_source_reports_set_vs_default(self) -> None:
        _write_lead_meta("shop", {"maxReworkCycles": "3"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("maxReworkCycles", "shop") == (3, "set")
        assert settings.value_and_source("budgetTokens", "shop") == (None, "default")

    def test_value_and_source_reports_approval_mode(self) -> None:
        _write_lead_meta("shop", {"approvalMode": "refuse"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("approvalMode", "shop") == ("refuse", "set")

    def test_approval_mode_park_round_trips(self) -> None:
        _write_lead_meta("shop", {"approvalMode": "park"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.approval_mode == "park"

    def test_coerce_accepts_park(self) -> None:
        assert pod_settings.PodSettings.coerce("approvalMode", "park") == "park"

    def test_approval_expiry_hours_defaults_to_24(self) -> None:
        _write_lead_meta("shop")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.approval_expiry_hours == 24

    def test_input_expiry_hours_defaults_to_72(self) -> None:
        _write_lead_meta("shop")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.input_expiry_hours == 72

    def test_approval_expiry_hours_round_trips(self) -> None:
        _write_lead_meta("shop", {"approvalExpiryHours": "6"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.approval_expiry_hours == 6

    def test_input_expiry_hours_round_trips(self) -> None:
        _write_lead_meta("shop", {"inputExpiryHours": "48"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.input_expiry_hours == 48

    def test_approval_expiry_hours_rejects_non_positive(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="approvalExpiryHours"):
            pod_settings.PodSettings.coerce("approvalExpiryHours", "0")

    def test_input_expiry_hours_rejects_non_positive(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="inputExpiryHours"):
            pod_settings.PodSettings.coerce("inputExpiryHours", "0")

    def test_max_consultations_per_task_defaults_to_3_and_round_trips(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").max_consultations_per_task == 3
        _write_lead_meta("shop", {"maxConsultationsPerTask": "1"})
        assert pod_settings.PodSettings.load_for("shop").max_consultations_per_task == 1

    def test_max_consultations_per_task_rejects_negative(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="maxConsultationsPerTask"):
            pod_settings.PodSettings.coerce("maxConsultationsPerTask", "-1")

    def test_consult_mode_defaults_to_park_and_round_trips(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").consult_mode == "park"
        _write_lead_meta("shop", {"consultMode": "decide"})
        assert pod_settings.PodSettings.load_for("shop").consult_mode == "decide"

    def test_consult_mode_coerces_case_and_rejects_anything_else(self) -> None:
        assert pod_settings.PodSettings.coerce("consultMode", " Decide ") == "decide"
        with pytest.raises(pod_settings.PodSettingsError, match="consultMode"):
            pod_settings.PodSettings.coerce("consultMode", "ask")

    def test_require_verify_defaults_to_false(self) -> None:
        _write_lead_meta("shop")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.require_verify is False

    def test_require_verify_true_round_trips(self) -> None:
        _write_lead_meta("shop", {"requireVerify": True})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.require_verify is True

    def test_coerce_accepts_require_verify(self) -> None:
        assert pod_settings.PodSettings.coerce("requireVerify", True) is True
        assert pod_settings.PodSettings.coerce("requireVerify", False) is False


class TestPodSettingsSchedule:
    """`PodSettings.schedule`: validated through the same `coerce` path as every other
    setting; the CLI's dedicated write path is covered in
    tests/integration/test_pod_config_settings.py."""

    def test_defaults_to_none(self) -> None:
        _write_lead_meta("shop")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.schedule is None

    def test_recognized_spec_round_trips(self) -> None:
        _write_lead_meta("shop", {"schedule": "@every 30m"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.schedule == "@every 30m"

    def test_invalid_spec_names_the_key(self) -> None:
        _write_lead_meta("shop", {"schedule": "@every 3x"})
        with pytest.raises(pod_settings.PodSettingsError, match="schedule"):
            pod_settings.PodSettings.load_for("shop")

    def test_coerce_accepts_a_recognized_spec(self) -> None:
        assert pod_settings.PodSettings.coerce("schedule", "@every 30m") == "@every 30m"

    def test_coerce_rejects_an_unrecognized_spec(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="schedule"):
            pod_settings.PodSettings.coerce("schedule", "@every 3x")

    def test_value_and_source_reports_set_schedule(self) -> None:
        _write_lead_meta("shop", {"schedule": "09:00"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("schedule", "shop") == ("09:00", "set")


class TestPodSettingsAllowCommands:
    """`PodSettings.allowCommands`: a pod's own extra unattended binaries."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").allow_commands == ()

    def test_parses_and_dedupes_a_comma_separated_list(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "tox, uv, tox"})
        assert pod_settings.PodSettings.load_for("shop").allow_commands == ("tox", "uv")

    def test_a_bin_already_on_safe_bins_is_silently_dropped(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "tox, ls"})
        assert pod_settings.PodSettings.load_for("shop").allow_commands == ("tox",)

    def test_rejects_a_path(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="allowCommands"):
            pod_settings.PodSettings.coerce("allowCommands", "./pytest")

    def test_rejects_a_shell_metacharacter(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="allowCommands"):
            pod_settings.PodSettings.coerce("allowCommands", "pytest;rm")

    @pytest.mark.parametrize("name", ["eval", "exec", "source", ".", "export"])
    def test_rejects_opaque_or_scope_changing_names(self, name: str) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="allowCommands"):
            pod_settings.PodSettings.coerce("allowCommands", name)

    def test_rejects_a_high_risk_class_bin(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="allowCommands"):
            pod_settings.PodSettings.coerce("allowCommands", "git")

    def test_coerce_returns_the_canonical_comma_joined_form(self) -> None:
        assert pod_settings.PodSettings.coerce("allowCommands", "uv, tox") == "uv,tox"

    def test_value_and_source_reports_the_joined_string(self) -> None:
        _write_lead_meta("shop", {"allowCommands": "tox,uv"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("allowCommands", "shop") == ("tox,uv", "set")


class TestPodSettingsProjectInstructions:
    """`PodSettings.projectInstructions`: opt-in relative paths inside the codebase
    root, composed by `teams/identity.py` — see
    tests/integration/test_role_tools_and_identity.py for the composition itself."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").project_instructions == ()

    def test_parses_and_dedupes_a_comma_separated_list(self) -> None:
        _write_lead_meta("shop", {"projectInstructions": "AGENTS.md, docs/style.md, AGENTS.md"})
        assert pod_settings.PodSettings.load_for("shop").project_instructions == (
            "AGENTS.md",
            "docs/style.md",
        )

    def test_rejects_an_absolute_path(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="projectInstructions"):
            pod_settings.PodSettings.coerce("projectInstructions", "/etc/passwd")

    def test_rejects_a_home_relative_path(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="projectInstructions"):
            pod_settings.PodSettings.coerce("projectInstructions", "~/AGENTS.md")

    def test_rejects_a_dot_dot_segment(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="projectInstructions"):
            pod_settings.PodSettings.coerce("projectInstructions", "../outside/AGENTS.md")

    def test_a_dot_dot_segment_is_rejected_even_mid_path(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="projectInstructions"):
            pod_settings.PodSettings.coerce("projectInstructions", "docs/../../AGENTS.md")

    def test_coerce_returns_the_canonical_comma_joined_form(self) -> None:
        assert (
            pod_settings.PodSettings.coerce("projectInstructions", "AGENTS.md, CLAUDE.md")
            == "AGENTS.md,CLAUDE.md"
        )

    def test_value_and_source_reports_the_joined_string(self) -> None:
        _write_lead_meta("shop", {"projectInstructions": "AGENTS.md"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("projectInstructions", "shop") == ("AGENTS.md", "set")


class TestPodSettingsMcpServers:
    """`PodSettings.mcpServers`: a pod's selection from the shared MCP server
    catalog. `None` (the default) means "every configured server"."""

    def test_defaults_to_none(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").mcp_servers is None

    def test_coerce_accepts_names_in_the_live_catalog(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="a", command="stub"))
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="b", command="stub"))
        assert pod_settings.PodSettings.coerce("mcpServers", "a, b") == "a,b"

    def test_coerce_rejects_a_name_absent_from_the_catalog(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="mcpServers"):
            pod_settings.PodSettings.coerce("mcpServers", "zzz")

    def test_load_for_rejects_a_stored_name_no_longer_in_the_catalog(self) -> None:
        _write_lead_meta("shop", {"mcpServers": "gone"})
        with pytest.raises(pod_settings.PodSettingsError, match="mcpServers"):
            pod_settings.PodSettings.load_for("shop")

    def test_value_and_source_reports_the_joined_string(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="a", command="stub"))
        _write_lead_meta("shop", {"mcpServers": "a"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("mcpServers", "shop") == ("a", "set")


class TestPodSettingsReadOnly:
    """`readOnly` narrows the machine's read-only jail grants and never widens them."""

    @pytest.fixture
    def grants(self, tmp_path: Path) -> tuple[Path, Path]:
        from docket.teams import fleet as _fleet

        node, py = tmp_path / "node", tmp_path / "py"
        node.mkdir()
        py.mkdir()
        _fleet.add_read_only(str(node))
        _fleet.add_read_only(str(py))
        return node.resolve(), py.resolve()

    def test_unset_keeps_every_machine_grant(self, grants: tuple[Path, Path]) -> None:
        _write_lead_meta("shop")
        assert pod_settings.effective_read_only("shop") == grants

    def test_a_list_keeps_only_the_named_grants(self, grants: tuple[Path, Path]) -> None:
        _write_lead_meta("shop", {"readOnly": str(grants[1])})
        assert pod_settings.effective_read_only("shop") == (grants[1],)

    def test_none_keeps_nothing(self, grants: tuple[Path, Path]) -> None:
        _write_lead_meta("shop", {"readOnly": "none"})
        assert pod_settings.effective_read_only("shop") == ()

    def test_a_grant_the_operator_removes_leaves_the_pod(self, grants: tuple[Path, Path]) -> None:
        from docket.teams import fleet as _fleet

        _write_lead_meta("shop", {"readOnly": f"{grants[0]},{grants[1]}"})
        _fleet.remove_read_only(str(grants[0]))
        assert pod_settings.effective_read_only("shop") == (grants[1],)

    def test_coerce_refuses_a_path_the_machine_has_not_granted(
        self, grants: tuple[Path, Path], tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(pod_settings.PodSettingsError, match="readOnly"):
            pod_settings.PodSettings.coerce("readOnly", f"{grants[0]},{other}")

    def test_coerce_stores_granted_paths_and_none(self, grants: tuple[Path, Path]) -> None:
        assert pod_settings.PodSettings.coerce("readOnly", f" {grants[1]} ") == str(grants[1])
        assert pod_settings.PodSettings.coerce("readOnly", "none") == "none"


class TestPodSettingsPrepare:
    """`prepare` is one install line, `none` to turn it off, `""` to leave it to the lockfile."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").prepare == ""

    def test_coerce_keeps_the_stripped_line_and_none(self) -> None:
        assert pod_settings.PodSettings.coerce("prepare", " make deps ") == "make deps"
        assert pod_settings.PodSettings.coerce("prepare", "none") == "none"

    @pytest.mark.parametrize("bad", ["a\nb", "a\x00b", "x" * 1001])
    def test_coerce_refuses_a_multiline_nul_or_long_value(self, bad: str) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="prepare"):
            pod_settings.PodSettings.coerce("prepare", bad)

    def test_a_stored_value_is_read_back(self) -> None:
        _write_lead_meta("shop", {"prepare": "make deps"})
        assert pod_settings.PodSettings.load_for("shop").prepare == "make deps"


class TestPodSettingsProtects:
    """`protects` is a comma-joined list of repository globs; it only ever adds to the defaults."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").protects == ()

    def test_coerce_joins_the_stripped_unique_globs(self) -> None:
        assert pod_settings.PodSettings.coerce("protects", " src/*.js , Makefile,src/*.js") == (
            "src/*.js,Makefile"
        )

    @pytest.mark.parametrize("bad", ["/abs", "a/../b", "x" * 201])
    def test_coerce_refuses_an_escaping_or_long_glob(self, bad: str) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="protects"):
            pod_settings.PodSettings.coerce("protects", bad)

    def test_coerce_refuses_more_than_fifty_globs(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="protects"):
            pod_settings.PodSettings.coerce("protects", ",".join(f"d{n}/*" for n in range(51)))

    def test_a_stored_value_is_read_back_as_a_tuple(self) -> None:
        _write_lead_meta("shop", {"protects": "a/*,b"})
        assert pod_settings.PodSettings.load_for("shop").protects == ("a/*", "b")


class TestPodSettingsDeniedTools:
    """`PodSettings.deniedTools`: built-in tool names every role in this pod
    additionally denies, unioned by `teams.roles.registry_for_role` -- see
    `tests/unit/core/test_archetypes.py::TestPodDeniedTools` for the union itself."""

    def test_defaults_to_empty(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").denied_tools == ()

    def test_parses_and_dedupes_a_comma_separated_list(self) -> None:
        _write_lead_meta("shop", {"deniedTools": "fetch, bash, fetch"})
        assert pod_settings.PodSettings.load_for("shop").denied_tools == ("fetch", "bash")

    def test_coerce_accepts_a_known_tool_name(self) -> None:
        assert pod_settings.PodSettings.coerce("deniedTools", "fetch") == "fetch"

    def test_coerce_accepts_the_send_kind(self) -> None:
        assert pod_settings.PodSettings.coerce("deniedTools", "send, fetch") == "send,fetch"

    def test_coerce_accepts_the_record_kind(self) -> None:
        assert pod_settings.PodSettings.coerce("deniedTools", "record, fetch") == "record,fetch"

    def test_coerce_rejects_an_unknown_tool_name(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="deniedTools"):
            pod_settings.PodSettings.coerce("deniedTools", "zzz")

    def test_value_and_source_reports_the_joined_string(self) -> None:
        _write_lead_meta("shop", {"deniedTools": "fetch"})
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.value_and_source("deniedTools", "shop") == ("fetch", "set")


_GRANT = {"at": "2026-10-30T10:00:00+00:00", "by": "cli"}


class TestEffectiveNetworkGrant:
    """A pod widens a machine at ``none`` only through a recorded ``networkGrant``."""

    def test_machine_none_and_pod_open_stays_none(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"network": "open"})
        assert pod_settings.effective_network("shop") == ("none", "global")

    def test_machine_none_and_a_grant_is_open_for_that_pod(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"network": "open", "networkGrant": _GRANT})
        assert pod_settings.effective_network("shop") == ("open", "pod-grant")

    def test_the_unrecorded_default_none_is_widened_by_a_grant_too(self) -> None:
        _write_lead_meta("shop", {"networkGrant": _GRANT})
        assert pod_settings.effective_network("shop") == ("open", "pod-grant")

    def test_a_second_pod_without_a_grant_stays_none(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"networkGrant": _GRANT})
        _write_lead_meta("other")
        assert pod_settings.effective_network("other") == ("none", "global")

    def test_a_grant_with_unreadable_settings_fails_closed(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"networkGrant": _GRANT, "turnTimeoutS": "not-a-number"})
        assert pod_settings.effective_network("shop")[0] == "none"

    @pytest.mark.parametrize("bad", ["x", {"at": "now"}, {"at": "", "by": "cli"}, ["a"]])
    def test_an_unparseable_grant_fails_closed(self, bad: object) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"networkGrant": bad})
        assert pod_settings.effective_network("shop")[0] == "none"

    def test_a_pod_none_wins_over_a_grant(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop", {"network": "none", "networkGrant": _GRANT})
        assert pod_settings.effective_network("shop")[0] == "none"

    def test_a_grant_changes_nothing_when_the_machine_is_open(self) -> None:
        _fleet.set_network_mode("open")
        _write_lead_meta("shop", {"networkGrant": _GRANT})
        assert pod_settings.effective_network("shop") == ("open", "default")

    def test_a_grant_is_not_settable_by_coerce(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="unknown pod setting"):
            pod_settings.PodSettings.coerce("networkGrant", "x")

    def test_the_grant_is_a_recorded_key_not_a_settable_one(self) -> None:
        assert "networkGrant" in pod_settings.PodSettings.RECORDED_KEYS
        assert "networkGrant" not in pod_settings.PodSettings.KEYS

    def test_grant_and_revoke_round_trip(self) -> None:
        _fleet.set_network_mode("none")
        _write_lead_meta("shop")
        pod_settings.grant_network("shop", by="cli")
        assert pod_settings.effective_network("shop") == ("open", "pod-grant")
        assert pod_settings.network_grant_pods(["shop", "other"]) == ["shop"]
        assert pod_settings.revoke_network_grant("shop") is True
        assert pod_settings.revoke_network_grant("shop") is False
        assert pod_settings.effective_network("shop") == ("none", "global")


class TestPodSettingsNeeds:
    def test_needs_is_a_recorded_key_not_a_settable_one(self) -> None:
        assert "needs" in pod_settings.PodSettings.RECORDED_KEYS
        assert "needs" not in pod_settings.PodSettings.KEYS
        with pytest.raises(pod_settings.PodSettingsError, match="unknown pod setting"):
            pod_settings.PodSettings.coerce("needs", "isolation")

    def test_needs_reads_back_comma_joined_in_order(self) -> None:
        _write_lead_meta("shop", {"needs": "isolation,fetch-hosts,isolation"})
        assert pod_settings.PodSettings.load_for("shop").needs == ("isolation", "fetch-hosts")


class TestWorkspaceKind:
    """A pod's workspace kind is the one its Lead records; a folder pod takes no install."""

    def test_the_kind_is_read_from_the_lead_and_defaults_to_codebase(self) -> None:
        _write_lead_meta("web")
        _write_lead_meta("ops", {"workspaceKind": "workdir"})
        assert pod_settings.workspace_kind("web") == "codebase"
        assert pod_settings.workspace_kind("ops") == "workdir"

    def test_a_workdir_pod_refuses_a_prepare_command_and_accepts_none(self) -> None:
        _write_lead_meta("ops", {"workspaceKind": "workdir"})
        with pytest.raises(
            pod_settings.PodSettingsError,
            match=r"^prepare: pod 'ops' works in a folder \(workspaceKind workdir\); "
            r"a prepare command applies only to a pod with a codebase$",
        ):
            pod_settings.PodSettings.coerce("prepare", "npm ci", project="ops")
        assert pod_settings.PodSettings.coerce("prepare", "none", project="ops") == "none"


class TestFetchDomains:
    """A pod declares the hosts its `fetch` reads; `*` is a recorded grant only."""

    def test_set_and_clear_round_trip_through_the_stored_form(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.PodSettings.load_for("shop").fetch_domains == ()
        stored = pod_settings.PodSettings.coerce(
            "fetchDomains", " Docs.Python.org, *.wikipedia.org ,docs.python.org"
        )
        assert stored == "docs.python.org,*.wikipedia.org"
        _write_lead_meta("shop", {"fetchDomains": stored})
        assert pod_settings.PodSettings.load_for("shop").fetch_domains == (
            "docs.python.org",
            "*.wikipedia.org",
        )
        _write_lead_meta("shop", {"fetchDomains": None})
        assert pod_settings.PodSettings.load_for("shop").fetch_domains == ()

    @pytest.mark.parametrize(
        "bad", ["https://docs.python.org", "docs python.org", "*.org", "*.", "a.*.org", "ex*.org"]
    )
    def test_an_entry_that_is_not_a_host_or_a_registered_wildcard_is_refused(
        self, bad: str
    ) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="fetchDomains"):
            pod_settings.PodSettings.coerce("fetchDomains", bad)

    def test_a_bare_star_is_refused_without_the_grant(self) -> None:
        with pytest.raises(pod_settings.PodSettingsError, match="--widen"):
            pod_settings.PodSettings.coerce("fetchDomains", "*")
        with pytest.raises(pod_settings.PodSettingsError, match="--widen"):
            pod_settings.PodSettings.coerce("fetchDomains", "docs.python.org,*")

    def test_a_stored_star_without_a_grant_is_unreadable_settings(self) -> None:
        _write_lead_meta("shop", {"fetchDomains": "*"})
        with pytest.raises(pod_settings.PodSettingsError, match="fetchDomains"):
            pod_settings.PodSettings.load_for("shop")
        assert pod_settings.effective_fetch_domains("shop") == ()

    def test_the_grant_records_its_date_and_operator_and_is_audited(self) -> None:
        _write_lead_meta("shop")
        pod_settings.grant_fetch_any("shop", by="cli")
        settings = pod_settings.PodSettings.load_for("shop")
        assert settings.fetch_domains == ("*",)
        grant = json.loads(settings.fetch_grant)
        assert grant["by"] == "cli" and grant["at"]
        (entry,) = [e for e in read_audit() if e["action"] == "pod.fetch_widen"]
        assert "pod=shop" in str(entry["detail"])
        assert pod_settings.effective_fetch_domains("shop") == ("*",)

    def test_the_grant_is_recorded_not_settable(self) -> None:
        assert "fetchGrant" in pod_settings.PodSettings.RECORDED_KEYS
        assert "fetchGrant" not in pod_settings.PodSettings.KEYS
        with pytest.raises(pod_settings.PodSettingsError, match="unknown pod setting"):
            pod_settings.PodSettings.coerce("fetchGrant", "x")

    def test_narrowing_drops_the_grant_and_audits_once(self) -> None:
        _write_lead_meta("shop")
        assert pod_settings.revoke_fetch_grant("shop") is False
        pod_settings.grant_fetch_any("shop", by="cli")
        assert pod_settings.revoke_fetch_grant("shop") is True
        assert pod_settings.revoke_fetch_grant("shop") is False
        assert pod_settings.PodSettings.load_for("shop").fetch_domains == ()
        assert [e["action"] for e in read_audit() if e["action"].startswith("pod.fetch_")] == [
            "pod.fetch_widen",
            "pod.fetch_narrow",
        ]

    def test_the_member_set_is_the_machine_list_plus_the_pods_own(self) -> None:
        _write_lead_meta("shop", {"fetchDomains": "docs.python.org"})
        _write_lead_meta("other")
        machine = dataclasses.replace(
            current_home(), fetch_allowed_domains=("api.example.test", "*", "*.cdn.test")
        )
        with use_home(machine):
            assert pod_settings.effective_fetch_domains("shop") == (
                "api.example.test",
                "*.cdn.test",
                "docs.python.org",
            )
            assert pod_settings.effective_fetch_domains("other") == (
                "api.example.test",
                "*.cdn.test",
            )
            assert pod_settings.effective_fetch_domains(None) == ("api.example.test", "*.cdn.test")

    def test_unreadable_pod_settings_leave_the_machine_list_alone(self) -> None:
        _write_lead_meta("shop", {"fetchDomains": "docs.python.org", "turnTimeoutS": "x"})
        machine = dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
        with use_home(machine):
            assert pod_settings.effective_fetch_domains("shop") == ("api.example.test",)
