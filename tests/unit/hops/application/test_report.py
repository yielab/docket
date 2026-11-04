"""The pod report readers -- root resolution, scope labels and the network line."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from tests.support.pods import bind_pipeline, build_pod, seed_empty_home, spend_tokens

from docket.hops.application import report as pod_report
from docket.kernel import clock as _clock
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


class TestSettingsNetworkRow:
    """The `settings.network` row and the top-level `network` read one effective mode."""

    def test_a_pod_with_no_network_set_reports_the_same_mode_in_both(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")

            report = pod_report.pod_report("demo")

        assert report["network"]["mode"] == "none"
        assert report["settings"]["network"] == {"value": "none", "source": "default"}

    def test_a_pod_open_under_a_machine_none_reports_none_with_its_own_source(
        self, tmp_path: Path
    ) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            _fleet.meta_set("demo-lead", "network", "open")

            report = pod_report.pod_report("demo")

        assert report["network"]["mode"] == "none"
        assert report["settings"]["network"] == {"value": "none", "source": "set"}


class TestPodReportNeeds:
    """The pod report serves the recorded needs as wire entries, recomputed as the pod is now."""

    def test_no_recorded_need_is_an_empty_list(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")

            assert pod_report.pod_report("demo")["needs"] == []

    def test_each_recorded_need_has_exactly_the_four_wire_keys(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            _fleet.meta_set("demo-lead", "needs", "fetch-hosts,search-host")
            _fleet.meta_set("demo-lead", "fetchDomains", "html.duckduckgo.com")

            needs = pod_report.pod_report("demo")["needs"]

        assert needs == [
            {"kind": "fetch-hosts", "name": "fetch-hosts", "fix": "", "satisfied": True},
            {"kind": "search-host", "name": "search-host", "fix": "", "satisfied": True},
        ]


class TestBudgetFields:
    """`budget` on the pod report and the summary row: the cap, what the gate would count, the window."""

    def test_a_pod_with_no_cap_reports_every_token_and_no_window(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            today = _clock.now().strftime("%Y-%m-%d")
            spend_tokens("demo-lead", {"2026-01-01": 40, today: 2})

            expected = {"tokens": None, "used": 42, "window": "none", "windowStart": None}

            assert pod_report.pod_report("demo")["budget"] == expected
            assert pod_report.pod_summary("demo")["budget"] == expected

    def test_a_day_window_counts_today_only_from_midnight_utc(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            today = _clock.now().strftime("%Y-%m-%d")
            _fleet.meta_set("demo-lead", "budgetTokens", 100)
            _fleet.meta_set("demo-lead", "budgetWindow", "day")
            spend_tokens("demo-lead", {"2026-01-01": 40, today: 2})

            budget = pod_report.pod_report("demo")["budget"]

            assert budget == {
                "tokens": 100,
                "used": 2,
                "window": "day",
                "windowStart": f"{today}T00:00:00Z",
            }

    def test_a_week_window_starts_on_the_most_recent_monday(self, tmp_path: Path) -> None:
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            _fleet.meta_set("demo-lead", "budgetWindow", "week")

            start = pod_report.pod_summary("demo")["budget"]["windowStart"]

            monday = _dt.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")
            assert monday.weekday() == 0
            assert (monday.hour, monday.minute) == (0, 0)
            assert 0 <= (_clock.now().replace(tzinfo=None) - monday).days < 7
