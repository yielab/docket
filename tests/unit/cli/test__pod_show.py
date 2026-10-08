"""``docket pod show`` -- root resolution, scope labels and the leaf's refusals.

The end-to-end oracle (report values match a real FakeDriver dispatch) lives in
tests/integration/test_pod_show.py; this file covers the pure pieces that don't need a
full pod fixture.
"""

from __future__ import annotations

from pathlib import Path

import docket.config as _cfg
from docket.cli import _pod_show
from docket.core.models import AgentMeta

SUBJECT = "docket.cli._pod_show"


class TestRootsFor:
    def test_codebase_wins_over_work_dir(self) -> None:
        meta = AgentMeta(kind="project", codebase="/repo", work_dir="/work")
        roots = _pod_show._roots_for("agent-1", meta)
        assert roots == (Path("/repo"),)

    def test_work_dir_when_no_codebase(self) -> None:
        meta = AgentMeta(kind="project", work_dir="/work")
        roots = _pod_show._roots_for("agent-1", meta)
        assert roots == (Path("/work"),)

    def test_falls_back_to_the_agents_own_workspace(self) -> None:
        meta = AgentMeta(kind="project")
        roots = _pod_show._roots_for("agent-1", meta)
        assert roots == (_cfg.workspace_dir("agent-1"),)


class TestScopeLabel:
    """`_scope_label` maps `ArchetypeRegistry.source_of`'s result onto the report's
    built-in/global/pod provenance model."""

    def test_built_in_and_starter_collapse_to_built_in(self) -> None:
        assert _pod_show._scope_label("built-in") == "built-in"
        assert _pod_show._scope_label("starter") == "built-in"

    def test_user_overlay_is_global(self) -> None:
        assert _pod_show._scope_label("user") == "global"

    def test_pod_overlay_is_pod(self) -> None:
        assert _pod_show._scope_label("pod:demo") == "pod"

    def test_unknown_source_is_empty(self) -> None:
        assert _pod_show._scope_label("") == ""
