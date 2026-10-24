"""``docket pod set`` / ``unset`` / ``show`` — typed, validated pod dispatch settings.

Closes the gap where `maxReworkCycles`/`turnTimeoutS`/`verifyTimeoutS` were writable only by
hand-editing `.docket-meta.json` or the internal `_json meta-set` debug path, and an invalid
stored value silently fell back to its default instead of refusing dispatch. See
pod-dispatch.spec.md ("Timeout configuration", "Budget gate and auto-pause", "Reviewer verdict
gate and bounded rework") and cli-json-shapes.spec.md ("`docket pod show --json`").
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import typer
from tests.support.cli import invoke_pod
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.hops.application import steps as _steps
from docket.interfaces.cli.commands import pod_settings as _pod_settings
from docket.interfaces.http import sweeps as _sweeps
from docket.kernel.home import current_home
from docket.platform import store as _store
from docket.tasks.application import queue as _queue
from docket.teams import pod, pod_settings
from docket.teams import settings as _settings

SUBJECT = "docket.interfaces.cli.commands.pod"


@contextmanager
def _build(tmp_path: Path, project: str = "proj") -> Iterator[None]:
    with _seed(tmp_path):
        build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield


def _lead_meta(project: str) -> dict[str, object]:
    path = current_home().meta_path(f"{project}-lead")
    return dict(json.loads(path.read_text()))


def _show(project: str = "proj") -> tuple[int, str]:
    result = invoke_pod(["show", "--pod", project, "--json"])
    return result.exit_code, result.output


class TestPodShowSettings:
    def test_defaults_when_nothing_configured(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            code, out = _show()
            assert code == 0, out
            data = json.loads(out)["settings"]
            assert data["maxReworkCycles"] == {"value": 1, "source": "default"}
            assert data["budgetUsd"] == {"value": 0.0, "source": "default"}

    def test_invalid_stored_value_refuses_instead_of_showing_a_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            meta = _lead_meta("proj")
            meta["turnTimeoutS"] = "not-a-number"
            current_home().meta_path("proj-lead").write_text(json.dumps(meta))

            code, out = _show()
            assert code == 1
            assert "turnTimeoutS" in out


class TestConfigSet:
    def test_set_persists_a_validated_value_and_dispatch_reads_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "maxReworkCycles", "2")
            assert _settings.pod_max_rework_cycles("proj") == 2
            capsys.readouterr()

    def test_set_approval_mode_refuse_persists_and_dispatch_reads_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            assert _settings.pod_approval_mode("proj") == "wait"
            _pod_settings.set_setting("proj", "approvalMode", "refuse")
            assert _settings.pod_approval_mode("proj") == "refuse"
            capsys.readouterr()

    def test_set_invalid_value_exits_1_and_leaves_meta_unchanged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            before = _lead_meta("proj")

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "turnTimeoutS", "abc")
            assert exc.value.exit_code == 1
            assert "turnTimeoutS" in capsys.readouterr().err
            assert _lead_meta("proj") == before

    def test_set_unknown_key_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "definitelyNotARealSetting", "x")
            assert exc.value.exit_code == 1

    def test_set_invalid_approval_mode_exits_1_and_leaves_meta_unchanged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            before = _lead_meta("proj")

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "approvalMode", "x")
            assert exc.value.exit_code == 1
            assert "approvalMode" in capsys.readouterr().err
            assert _lead_meta("proj") == before


class TestConfigUnset:
    def test_unset_falls_back_to_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "maxReworkCycles", "3")
            capsys.readouterr()
            _pod_settings.unset_setting("proj", "maxReworkCycles")
            capsys.readouterr()
            assert _settings.pod_max_rework_cycles("proj") == 1


_CUSTOM_PIPELINE = "name: custom-bound\nsteps:\n  - kickoff: lead\n  - assemble: implementer\n"


class TestConfigSetPipeline:
    """``pod config set/unset pipeline`` -- the CLI's validate-plan-store contract.
    See ``test_dispatch.py::TestBoundPipeline`` for the resolution/refusal behavior."""

    def test_set_validates_plans_and_binds_a_valid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            pipeline_file = tmp_path / "custom.yaml"
            pipeline_file.write_text(_CUSTOM_PIPELINE)

            _pod_settings.set_setting("proj", "pipeline", str(pipeline_file))
            capsys.readouterr()

            digest = _lead_meta("proj")["pipeline"]
            assert isinstance(digest, str) and len(digest) == 64
            stored = pod.bound_pipeline_path("proj")
            assert stored.read_text() == _CUSTOM_PIPELINE
            spec = _steps.effective_pipeline("proj", None)
            assert [step.id for step in spec.steps] == ["kickoff", "assemble"]

    def test_set_refuses_when_a_step_targets_a_role_the_pod_lacks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            pipeline_file = tmp_path / "needs-reviewer.yaml"
            pipeline_file.write_text("name: x\nsteps:\n  - r: reviewer\n")
            before = _lead_meta("proj")

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "pipeline", str(pipeline_file))
            assert exc.value.exit_code == 1
            assert "reviewer" in capsys.readouterr().err
            assert _lead_meta("proj") == before
            assert not pod.bound_pipeline_path("proj").exists()

    def test_set_refuses_over_a_stored_rework_setting(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "maxReworkCycles", "3")
            pipeline_file = tmp_path / "custom.yaml"
            pipeline_file.write_text(_CUSTOM_PIPELINE)
            capsys.readouterr()

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "pipeline", str(pipeline_file))
            assert exc.value.exit_code == 2
            assert "maxReworkCycles" in capsys.readouterr().err
            assert not pod.bound_pipeline_path("proj").exists()

    def test_set_refuses_on_an_invalid_pipeline_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            pipeline_file = tmp_path / "broken.yaml"
            pipeline_file.write_text("not: a valid\npipeline: [shape\n")

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "pipeline", str(pipeline_file))
            assert exc.value.exit_code == 1
            capsys.readouterr()

    def test_unset_removes_the_stored_copy_and_restores_the_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            pipeline_file = tmp_path / "custom.yaml"
            pipeline_file.write_text(_CUSTOM_PIPELINE)
            _pod_settings.set_setting("proj", "pipeline", str(pipeline_file))
            capsys.readouterr()

            _pod_settings.unset_setting("proj", "pipeline")
            capsys.readouterr()

            assert not pod.bound_pipeline_path("proj").exists()
            spec = _steps.effective_pipeline("proj", None)
            assert [step.role for step in spec.steps] == [
                "lead",
                "implementer",
                "reviewer",
                "tester",
            ]


class TestConfigSetSchedule:
    """``pod config set/unset schedule`` -- docket-schedules.json's own writer.
    See ``test_serve__scheduled_and_webhook_dispatch.py`` for the sweep firing on a spec set
    this way."""

    def test_set_validates_and_writes_the_schedules_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "schedule", "@every 30m")
            capsys.readouterr()

            from docket.pipeline.application import schedule as _sched

            schedules = _sched.load_schedules(current_home().schedule_file)
            assert schedules["proj"] == "@every 30m"
            assert _lead_meta("proj")["schedule"] == "@every 30m"

    def test_set_rejects_an_unrecognized_spec_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            before = _lead_meta("proj")

            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "schedule", "@every 3x")
            assert exc.value.exit_code == 1
            assert "schedule" in capsys.readouterr().err
            assert _lead_meta("proj") == before

            from docket.pipeline.application import schedule as _sched

            assert _sched.load_schedules(current_home().schedule_file) == {}

    def test_unset_removes_it_from_the_schedules_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "schedule", "@every 30m")
            capsys.readouterr()

            _pod_settings.unset_setting("proj", "schedule")
            capsys.readouterr()

            from docket.pipeline.application import schedule as _sched

            assert _sched.load_schedules(current_home().schedule_file) == {}
            assert pod_settings.PodSettings.load_for("proj").schedule is None

    def test_a_schedule_set_by_the_command_fires_under_the_serve_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Acceptance oracle: `config set schedule` writes exactly what
        `interfaces/http/server.py::check_schedules` reads -- no separate wiring needed for the sweep to
        pick it up."""
        import time as _time

        with _build(tmp_path):
            _pod_settings.set_setting("proj", "schedule", "@every 1s")
            capsys.readouterr()

            dispatched: list[str] = []
            monkeypatch.setattr(
                "docket.hops.application.sweep.dispatch_pod",
                lambda proj, **kw: dispatched.append(proj) or [],
            )
            _sweeps.check_schedules(_time.time())
            deadline = _time.time() + 2
            while not dispatched and _time.time() < deadline:
                _time.sleep(0.05)
            assert dispatched == ["proj"]


class TestBudgetSet:
    """`pod set budgetUsd` is the one budget writer; a new cap lifts the pause the old one set."""

    def test_budget_is_stored_on_the_lead(self, tmp_path: Path) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "budgetUsd", "5")
            assert _lead_meta("proj")["budgetUsd"] == 5.0

    def test_zero_removes_the_cap(self, tmp_path: Path) -> None:
        with _build(tmp_path):
            _pod_settings.set_setting("proj", "budgetUsd", "5")
            _pod_settings.set_setting("proj", "budgetUsd", "0")
            assert _settings.pod_budget("proj") == 0.0

    @pytest.mark.parametrize("bad", ["abc", "-1"])
    def test_a_bad_budget_exits_1_and_changes_nothing(self, tmp_path: Path, bad: str) -> None:
        with _build(tmp_path):
            with pytest.raises(typer.Exit) as exc:
                _pod_settings.set_setting("proj", "budgetUsd", bad)
            assert exc.value.exit_code == 1
            assert "budgetUsd" not in _lead_meta("proj")

    def test_a_new_cap_lifts_the_budget_pause(self, tmp_path: Path) -> None:
        with _build(tmp_path):
            lead = pod.member_id("proj", "lead")
            meta = _lead_meta("proj")
            meta.update({"paused": True, "pausedReason": "budget"})
            current_home().meta_path(lead).write_text(json.dumps(meta))

            _pod_settings.set_setting("proj", "budgetUsd", "10")

            assert _lead_meta("proj")["paused"] is False
            assert _lead_meta("proj")["pausedReason"] == ""

    @pytest.mark.parametrize("how", ["set-zero", "unset"])
    def test_removing_the_cap_lifts_the_budget_pause(self, tmp_path: Path, how: str) -> None:
        with _build(tmp_path):
            lead = pod.member_id("proj", "lead")
            meta = _lead_meta("proj")
            meta.update({"paused": True, "pausedReason": "budget"})
            current_home().meta_path(lead).write_text(json.dumps(meta))
            _queue.enqueue_task_once("proj", "held", channel="cli")

            if how == "set-zero":
                _pod_settings.set_setting("proj", "budgetUsd", "0")
            else:
                _pod_settings.unset_setting("proj", "budgetUsd")

            assert _lead_meta("proj")["paused"] is False
            assert _lead_meta("proj")["pausedReason"] == ""
            claim = _queue.claim_next_task("proj", resume=False)
            assert claim is not None

    def test_the_unblock_line_counts_every_task_it_requeues_and_says_so(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with _build(tmp_path):
            for desc in ("needs a file", "needs a file too"):
                _queue.enqueue_task_once("proj", desc, channel="cli")
            path = _settings.pod_task_list_path("proj")
            doc = _store.read_json(path)
            for task in doc["tasks"]:
                task["status"] = "blocked"
                task["blockedReason"] = "resources"
            _store.write_json(path, doc)
            capsys.readouterr()

            _pod_settings.set_setting("proj", "budgetUsd", "5")

            out = capsys.readouterr().out
            assert "Unblocked 2 blocked task(s)" in out
            assert "budget-blocked" not in out
