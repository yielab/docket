"""Unit coverage for ``teams.autonomy``: the policy table, the level a task runs at, and the pod
settings that win over the table."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.platform import store as _store
from docket.teams import autonomy, config_docs, fleet, pod

SUBJECT = "docket.teams.autonomy"

TABLE = {
    ("approval", "L3"): ("person", "deny"),
    ("approval", "L4"): ("person", "deny"),
    ("approval", "L5"): ("deny", "deny"),
    ("consult", "L3"): ("person", "block"),
    ("consult", "L4"): ("recommendation", "block"),
    ("consult", "L5"): ("recommendation", "block"),
    ("input", "L3"): ("person", "block"),
    ("input", "L4"): ("fail", "block"),
    ("input", "L5"): ("fail", "block"),
    ("gate", "L3"): ("person", "deny"),
    ("gate", "L4"): ("fail", "deny"),
    ("gate", "L5"): ("fail", "deny"),
    ("check_changed", "L3"): ("person", "deny"),
    ("check_changed", "L4"): ("person", "deny"),
    ("check_changed", "L5"): ("person", "deny"),
    ("wait", "L3"): ("machine", "block"),
    ("wait", "L4"): ("machine", "block"),
    ("wait", "L5"): ("machine", "block"),
}


def _pod(project: str = "shop", **meta: object) -> str:
    """Seed the Lead's meta of *project* with *meta*."""
    path = current_home().meta_path(pod.member_id(project, "lead"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"kind": "project", "scope": "project", **meta})
    return project


class TestPolicyFor:
    @pytest.mark.parametrize(("kind", "level"), sorted(TABLE))
    def test_every_cell_of_the_table(self, kind: str, level: str) -> None:
        assert autonomy.policy_for(kind, level) == TABLE[(kind, level)]

    def test_the_table_has_eighteen_cells(self) -> None:
        assert len(TABLE) == len(autonomy.KINDS) * len(autonomy.LEVELS) == 18

    def test_a_wait_is_the_same_at_every_level(self) -> None:
        assert {autonomy.policy_for("wait", level) for level in autonomy.LEVELS} == {
            ("machine", "block")
        }

    @pytest.mark.parametrize(("kind", "level"), [("banana", "L3"), ("consult", "L2")])
    def test_an_unknown_kind_or_level_is_refused(self, kind: str, level: str) -> None:
        with pytest.raises(InvalidInput):
            autonomy.policy_for(kind, level)

    def test_the_built_in_document_is_a_valid_kind_autonomy_document(self) -> None:
        document = config_docs.load_document(autonomy.DEFAULT_DOCUMENT)
        assert (document.kind, document.name) == ("autonomy", "default")


class TestTheDocument:
    def _write(self, tmp_path: Path, rows: dict[str, object]) -> Path:
        path = tmp_path / "autonomy.yaml"
        path.write_text(
            yaml.safe_dump({"kind": "autonomy", "name": "x", "rows": rows}), encoding="utf-8"
        )
        return path

    def _rows(self) -> dict[str, dict[str, dict[str, str]]]:
        rows: dict[str, dict[str, dict[str, str]]] = {}
        for (kind, level), (policy, on_expiry) in TABLE.items():
            rows.setdefault(kind, {})[level] = {"policy": policy, "onExpiry": on_expiry}
        return rows

    def test_a_missing_cell_is_refused_naming_it(self, tmp_path: Path) -> None:
        rows = self._rows()
        del rows["consult"]["L4"]
        with pytest.raises(autonomy.AutonomyError, match=r"consult.*L4"):
            autonomy.load_autonomy_document(self._write(tmp_path, rows))

    def test_an_unknown_policy_is_refused(self, tmp_path: Path) -> None:
        rows = self._rows()
        rows["input"]["L5"]["policy"] = "shrug"
        with pytest.raises(autonomy.AutonomyError, match=r"policy"):
            autonomy.load_autonomy_document(self._write(tmp_path, rows))

    def test_a_complete_document_loads(self, tmp_path: Path) -> None:
        loaded = autonomy.load_autonomy_document(self._write(tmp_path, self._rows()))
        assert loaded.cell("consult", "L5") == ("recommendation", "block")


class TestTheLevelOfATask:
    def test_an_attended_pod_defaults_to_l3_and_a_lights_out_pod_to_l4(self) -> None:
        _pod("shop")
        _pod("night", profile="lights-out")
        assert autonomy.effective_level("shop", None) == "L3"
        assert autonomy.effective_level("night", None) == "L4"

    def test_a_requested_level_narrows_within_the_ceiling(self) -> None:
        _pod("night", profile="lights-out")
        assert autonomy.effective_level("night", "L5") == "L5"
        assert autonomy.effective_level("night", "L3") == "L3"

    def test_the_global_profile_lifts_the_ceiling_of_every_pod(self) -> None:
        _pod("shop")
        fleet.set_profile("lights-out")
        assert autonomy.effective_level("shop", None) == "L4"
        assert autonomy.check_level("shop", "L5") == "L5"

    def test_a_level_above_the_ceiling_is_refused_naming_the_ceiling(self) -> None:
        _pod("shop")
        with pytest.raises(autonomy.LevelAboveCeiling, match=r"L5.*ceiling L3.*attended"):
            autonomy.check_level("shop", "L5")

    def test_an_invalid_level_is_refused(self) -> None:
        _pod("shop")
        with pytest.raises(InvalidInput, match="L3, L4 or L5"):
            autonomy.check_level("shop", "L9")

    def test_a_level_that_outlived_a_tighter_profile_is_clamped(self) -> None:
        _pod("shop")
        assert autonomy.effective_level("shop", "L5") == "L3"


class TestPodSettingsWinOverTheTable:
    @pytest.mark.parametrize(
        ("meta", "level", "expected"),
        [
            ({}, "L3", "park"),
            ({}, "L4", "decide"),
            ({}, "L5", "decide"),
            ({"consultMode": "park"}, "L4", "park"),
            ({"consultMode": "decide"}, "L3", "decide"),
        ],
    )
    def test_consult_mode(self, meta: dict[str, str], level: str, expected: str) -> None:
        project = _pod("shop", **meta)
        assert autonomy.consult_mode_for(project, level) == expected

    @pytest.mark.parametrize(
        ("meta", "level", "policy", "table_decided"),
        [
            ({}, "L3", "person", False),
            ({}, "L4", "person", False),
            ({}, "L5", "deny", True),
            ({"approvalMode": "refuse"}, "L3", "deny", False),
            ({"approvalMode": "wait"}, "L5", "person", False),
            ({"approvalMode": "park"}, "L5", "person", False),
        ],
    )
    def test_approval_policy(
        self, meta: dict[str, str], level: str, policy: str, table_decided: bool
    ) -> None:
        project = _pod("shop", **meta)
        assert autonomy.approval_policy_for(project, level) == policy
        assert autonomy.table_denies_approval(project, level) is table_decided
