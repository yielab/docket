"""The pod report readers -- root resolution, scope labels and the network line."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import pod_report
from docket.core.models import AgentMeta

SUBJECT = "docket.core.pod_report"


class TestRootsFor:
    def test_codebase_wins_over_work_dir(self) -> None:
        meta = AgentMeta(kind="project", codebase="/repo", work_dir="/work")
        roots = pod_report._roots_for("agent-1", meta)
        assert roots == (Path("/repo"),)

    def test_work_dir_when_no_codebase(self) -> None:
        meta = AgentMeta(kind="project", work_dir="/work")
        roots = pod_report._roots_for("agent-1", meta)
        assert roots == (Path("/work"),)

    def test_falls_back_to_the_agents_own_workspace(self) -> None:
        meta = AgentMeta(kind="project")
        roots = pod_report._roots_for("agent-1", meta)
        assert roots == (_cfg.workspace_dir("agent-1"),)


class TestScopeLabel:
    """`_scope_label` maps `ArchetypeRegistry.source_of`'s result onto the report's
    built-in/global/pod provenance model."""

    def test_built_in_and_starter_collapse_to_built_in(self) -> None:
        assert pod_report._scope_label("built-in") == "built-in"
        assert pod_report._scope_label("starter") == "built-in"

    def test_user_overlay_is_global(self) -> None:
        assert pod_report._scope_label("user") == "global"

    def test_pod_overlay_is_pod(self) -> None:
        assert pod_report._scope_label("pod:demo") == "pod"

    def test_unknown_source_is_empty(self) -> None:
        assert pod_report._scope_label("") == ""


class TestNetworkText:
    def test_none_with_isolation_off_says_it_is_not_enforced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        repoint_docket_home(monkeypatch, home)
        text = pod_report.network_text({"mode": "none", "scope": "default"})
        assert "not enforced" in text and "egress is open" in text
