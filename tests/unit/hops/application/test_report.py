"""The pod report readers -- root resolution, scope labels and the network line."""

from __future__ import annotations

from pathlib import Path

from tests.support.pods import bind_pipeline, build_pod, seed_empty_home

from docket.hops.application import report as pod_report
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _models
from docket.teams.models import AgentMeta

SUBJECT = "docket.hops.application.report"


class TestTaskCounts:
    def test_every_status_is_counted_once_and_there_is_no_completed_key(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / ".docket"
        (home / "state" / "workspaces" / "projects").mkdir(parents=True)
        with use_home(Home(home)):
            repo = TaskRepository.for_pod("demo")
            for index, status in enumerate(Status):
                repo.add(TaskRecord(id=f"t{index}", description="x", status=status))
            repo.add(TaskRecord(id="again", description="x", status=Status.done))

            counts = pod_report.task_counts("demo")

        assert counts == {
            "pending": 1,
            "running": 1,
            "waitingInput": 1,
            "waitingApproval": 1,
            "blocked": 1,
            "failed": 1,
            "done": 2,
            "cancelled": 1,
        }
        assert "completed" not in counts


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
        assert roots == (current_home().workspace_dir("agent-1"),)


class TestScopeLabel:
    """`_scope_label` maps `ArchetypeRegistry.source_of`'s result onto the report's
    built-in/pod provenance model."""

    def test_built_in_and_starter_collapse_to_built_in(self) -> None:
        assert pod_report._scope_label("built-in") == "built-in"
        assert pod_report._scope_label("starter") == "built-in"

    def test_pod_overlay_is_pod(self) -> None:
        assert pod_report._scope_label("pod:demo") == "pod"

    def test_unknown_source_is_empty(self) -> None:
        assert pod_report._scope_label("") == ""


class TestNetworkText:
    def test_none_with_isolation_off_says_it_is_not_enforced(self, tmp_path: Path) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        with use_home(Home(home)):
            text = pod_report.network_text({"mode": "none", "scope": "default", "enforced": False})
            assert "not enforced" in text and "egress is open" in text

    def test_none_that_a_jail_enforces_says_the_jail_cuts_it(self) -> None:
        text = pod_report.network_text({"mode": "none", "scope": "default", "enforced": True})
        assert text == "none (default); jailed tool calls have no network"


_PIPELINE = """\
name: p
steps:
  - plan: lead
  - build: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: build, max: 2}}
  - fan:
      parallel:
        - left: lead
        - right: reviewer
  - ship:
      run: make ship
  - hold: {wait: 1h}
"""


class TestPodReportShapeAndSteps:
    """The pod report says which blueprint made the pod and its pipeline as data."""

    def test_the_blueprint_and_every_step_kind(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            roles = ("lead", "implementer", "reviewer")
            build_pod("demo", roles, codebase="/src/demo", blueprint_name="build")
            bind_pipeline("demo", _PIPELINE)
            _, tiers, _ = _models.load_registry()
            _fleet.meta_set("demo-implementer", "model", tiers["economy"])
            _fleet.meta_set("demo-reviewer", "model", tiers["standard"])

            report = pod_report.pod_report("demo")

        assert report["blueprint"] == "build"
        steps = {s["id"]: s for s in report["pipeline"]["steps"]}
        assert list(steps) == ["plan", "build", "review", "fan", "ship", "hold"]
        assert {k: steps["build"][k] for k in ("kind", "role", "modelClass", "gate", "rework")} == {
            "kind": "agent",
            "role": "implementer",
            "modelClass": "cheap",
            "gate": "mechanical",
            "rework": [],
        }
        assert (steps["review"]["modelClass"], steps["review"]["gate"]) == ("strong", "verdict")
        assert steps["review"]["rework"] == [{"when": ["request-changes"], "to": "build", "max": 2}]
        assert steps["plan"]["gate"] is None
        assert [c["id"] for c in steps["fan"]["steps"]] == ["left", "right"]
        assert steps["fan"]["kind"] == "parallel"
        assert (steps["ship"]["kind"], steps["ship"]["role"]) == ("command", None)
        assert (steps["hold"]["kind"], steps["hold"]["modelClass"]) == ("wait", None)
        assert "steps" not in steps["build"]
