"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import bind_one_step_pipeline as _bind_one_step_pipeline
from tests.support.pods import planned_unit as _planned_unit
from tests.support.pods import seed_lean_pod as _seed_lean_pod
from tests.support.pods import unit_context as _unit_context
from tests.support.pods import write_meta as _write_meta
from tests.support.tasks import put_task as _put_task
from tests.support.tasks import put_tasks
from tests.support.tasks import task as _make_task

from docket.agent import ports as _rd
from docket.hops.application import compose as _compose
from docket.hops.application import runner as _runner
from docket.hops.application import steps as _steps
from docket.hops.application import sweep as _sweep
from docket.hops.gates import pre_hop as _pre_hop
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.tasks.domain.options import TaskGate
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import roles as _archetypes

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.hops.application.steps"


# ── fixtures ──────────────────────────────────────────────────────────────────


# ── execute_unit, lifted out of dispatch_task's closure (W31-C8b) ────────────


_UNPRICED = "ai-gateway/acme/model-x"


def _budget_warnings() -> list[dict[str, Any]]:
    tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
    events = _trace.read_trace(tf) if tf.exists() else []
    return [e["payload"] for e in events if e["event_type"] == "budget_warning"]


def _run_one_hop(cap: float, node: _orch.PlannedUnit) -> _record.UnitOutcome:
    ctx = _unit_context(cap=cap, run=lambda *a, **k: _rd.TurnResult(True, "done", 0.0, {}))
    return _runner.execute_unit(
        ctx, node, prior_snapshot=[], rework_hop=None, check_approval=True, index_for_context=0
    )


class TestUnpricedModelUnderABudget:
    """A budget cannot stop spend it cannot price: dispatch warns and runs the hop."""

    @pytest.fixture(autouse=True)
    def _nothing_spent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_pre_hop, "pod_gating_cost", lambda project: (0.0, False))

    def test_an_unpriced_member_model_warns_and_still_runs(self, pod_home: Path) -> None:
        _write_meta("myapp-implementer", {"model": _UNPRICED})
        outcome = _run_one_hop(5.0, _planned_unit("myapp-implementer"))
        assert outcome.kind == "advance"
        [warning] = _budget_warnings()
        assert warning["action"] == "unpriced_model"
        assert _UNPRICED in warning["reason"] and "$5.00" in warning["reason"]

    def test_a_step_model_is_the_one_checked(self, pod_home: Path) -> None:
        _write_meta("myapp-implementer")
        node = dataclasses.replace(_planned_unit("myapp-implementer"), model=_UNPRICED)
        _run_one_hop(5.0, node)
        assert [w["action"] for w in _budget_warnings()] == ["unpriced_model"]

    @pytest.mark.parametrize(
        ("cap", "model"),
        [(5.0, "anthropic/claude-haiku-4-5"), (5.0, "local/local-model"), (0.0, _UNPRICED)],
    )
    def test_no_warning_when_priced_local_or_uncapped(
        self, pod_home: Path, cap: float, model: str
    ) -> None:
        _write_meta("myapp-implementer", {"model": model})
        _run_one_hop(cap, _planned_unit("myapp-implementer"))
        assert _budget_warnings() == []

    def test_the_pod_lists_its_unpriced_models_only_under_a_budget(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"model": "local/local-model"})
        _write_meta("myapp-implementer", {"model": _UNPRICED})
        assert _steps.unpriced_budget_models("myapp") == []
        _write_meta("myapp-lead", {"model": "local/local-model", "budgetUsd": 3})
        assert _steps.unpriced_budget_models("myapp") == [_UNPRICED]


class TestEffectivePipelineBlueprint:
    """``effective_pipeline(project, None)`` resolves the Lead's ``blueprint`` meta through
    ``teams/blueprints.py::get_blueprint`` before falling back to the built-in default -- see
    pod-dispatch.spec.md "Pipeline order and participation"."""

    def test_respond_pod_runs_its_blueprint_pipeline(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"blueprint": "respond"})
        for role in ("researcher", "writer", "reviewer", "actor"):
            _write_meta(f"myapp-{role}")

        spec = _steps.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "researcher",
            "writer",
            "reviewer",
            "actor",
        ]

    def test_respond_pod_lead_message_names_the_researcher_not_the_implementer(
        self, pod_home: Path
    ) -> None:
        # A respond pod has no Implementer -- its Lead must not tell the model
        # to plan for one. The respond blueprint's `intake` step declares its
        # own `instructions` naming the Researcher, and `_hop_message` honors a
        # step override for `role: lead` (see role-archetypes.spec.md "Hop
        # instructions"), so this pipeline's Lead hop message never invents a
        # role the pod doesn't have.
        _write_meta("myapp-lead", {"blueprint": "respond"})
        for role in ("researcher", "writer", "reviewer", "actor"):
            _write_meta(f"myapp-{role}")

        spec = _steps.effective_pipeline("myapp", None)
        raw_step_instructions = _pipeline.step_instructions_by_id(spec)
        lead_instructions = raw_step_instructions.get("intake", "")

        message, _ = _compose._hop_message(
            TaskRecord(description="scan the market"),
            "lead",
            [],
            step_instructions=lead_instructions,
            project="myapp",
        )

        assert "Researcher" in message
        assert "Implementer" not in message

    def test_build_pod_is_unaffected(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        spec = _steps.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
        ]

    def test_absent_blueprint_meta_falls_back_to_the_built_in_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        spec = _steps.effective_pipeline("myapp", None)

        assert spec == _pipeline.default_pipeline()

    def test_unknown_blueprint_falls_back_without_raising(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"blueprint": "nope"})
        _write_meta("myapp-implementer")

        spec = _steps.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
        ]

    def test_pod_rework_budget_patches_the_blueprint_pipeline_rework_edge(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"blueprint": "routine", "maxReworkCycles": "3"})
        for role in ("analyst", "writer", "reviewer"):
            _write_meta(f"myapp-{role}")

        spec = _steps.effective_pipeline("myapp", None)

        reviewer_step = next(step for step in spec.steps if step.id == "review")
        assert isinstance(reviewer_step.gate, _gates.VerdictGate)
        assert reviewer_step.gate.rework is not None
        assert reviewer_step.gate.rework.max_cycles == 3

    def test_operate_pod_dispatch_reaches_waiting_approval_at_the_approval_step(
        self, pod_home: Path
    ) -> None:
        """The ``operate`` blueprint's Monitor step is gated by an ``ApprovalGate`` -- with a
        caller-spec-free dispatch resolving the blueprint pipeline, an operate pod runs the
        Lead's watch and then stops for sign-off, instead of running only the Lead."""
        _write_meta("myapp-lead", {"blueprint": "operate"})
        for role in ("monitor", "operator", "reviewer"):
            _write_meta(f"myapp-{role}")

        def _run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, f"done by {member_id}", 0.0, {})

        _queue.enqueue_task_once("myapp", "roll it out", channel="cli")
        results = _sweep.dispatch_pod("myapp", runner=_run, spec=None)

        assert len(results) == 1
        assert results[0].status == "waiting_approval"


class TestBoundPipeline:
    """``PodSettings.pipeline`` binds a pipeline file as a pod's default for every
    caller-spec-free trigger, not only an explicit ``--file`` -- see
    pod-dispatch.spec.md, "Pipeline order and participation"."""

    _CUSTOM_YAML = (
        "name: custom-bound\n"
        "steps:\n"
        "  - kickoff: lead\n"
        "  - assemble: implementer\n"
        "    verify: true\n"
    )

    def _bind(self, project: str, text: str | None = None) -> str:
        """Seed a bound pipeline directly -- the docket-owned copy plus its Lead-meta hash --
        exactly what ``docket pod set pipeline <file>`` produces. Bypasses
        the CLI setter itself, which has its own integration coverage."""
        text = self._CUSTOM_YAML if text is None else text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = _pod.bound_pipeline_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _fleet.meta_set(_pod.member_id(project, "lead"), "pipeline", digest)
        return digest

    def test_effective_pipeline_resolves_the_bound_file_not_the_builtin_default(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")

        spec = _steps.effective_pipeline("myapp", None)

        assert [step.id for step in spec.steps] == ["kickoff", "assemble"]

    def test_a_serve_sweep_or_mcp_shaped_dispatch_runs_the_bound_files_steps(
        self, pod_home: Path
    ) -> None:
        """The exact call ``serve.py``'s sweep/schedule and ``interfaces/cli/commands/mcp.py``'s dispatch tool
        both make -- ``dispatch_pod(project, ...)`` with no ``spec=`` kwarg -- so binding a
        pipeline changes every unattended trigger with zero changes to either caller."""
        _seed_lean_pod("myapp")
        self._bind("myapp")

        def _run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, f"done by {member_id}", 0.0, {})

        _queue.enqueue_task_once("myapp", "ship it", channel="cli")
        results = _sweep.dispatch_pod("myapp", runner=_run, spec=None)

        assert len(results) == 1
        assert results[0].status == "done"
        assert [h.step_id for h in results[0].hops] == ["kickoff", "assemble"]

    def test_unset_restores_the_blueprint_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")

        _fleet.meta_set(_pod.member_id("myapp", "lead"), "pipeline", None)

        spec = _steps.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
        ]

    def test_a_hash_mismatch_refuses_loudly_instead_of_falling_back(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")
        _pod.bound_pipeline_path("myapp").write_text("name: tampered\nsteps: []\n")

        with pytest.raises(_task.DispatchError, match="no longer matches"):
            _steps.effective_pipeline("myapp", None)

    def test_a_missing_copy_refuses_loudly_instead_of_falling_back(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")
        _pod.bound_pipeline_path("myapp").unlink()

        with pytest.raises(_task.DispatchError, match="unreadable"):
            _steps.effective_pipeline("myapp", None)

    def test_bound_pipelines_own_rework_config_is_never_patched_by_pod_max_rework_cycles(
        self, pod_home: Path
    ) -> None:
        """A bound file's own rework config wins; the Lead's ``maxReworkCycles``
        patch applies only to the blueprint/built-in default."""
        _write_meta("myapp-lead", {"maxReworkCycles": "9"})
        _write_meta("myapp-implementer")
        custom = (
            "name: custom-rework\n"
            "steps:\n"
            "  - build: implementer\n"
            "  - check: implementer\n"
            "    verdict: [APPROVE, REQUEST-CHANGES]\n"
            "    on: {REQUEST-CHANGES: {goto: build, max: 2}}\n"
        )
        self._bind("myapp", custom)

        spec = _steps.effective_pipeline("myapp", None)

        check_step = next(s for s in spec.steps if s.id == "check")
        assert isinstance(check_step.gate, _gates.VerdictGate)
        assert check_step.gate.rework is not None
        assert check_step.gate.rework.max_cycles == 2  # untouched -- never patched to 9

    def test_effective_pipeline_source_names_the_bound_file(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        digest = self._bind("myapp")

        assert (
            _steps.effective_pipeline_source("myapp") == f"bound pipeline (hash {digest[:12]}...)"
        )

    def test_effective_pipeline_source_names_the_blueprint_when_unbound(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"blueprint": "respond"})
        for role in ("researcher", "writer", "reviewer", "actor"):
            _write_meta(f"myapp-{role}")

        assert _steps.effective_pipeline_source("myapp") == "blueprint 'respond'"

    def test_effective_pipeline_source_names_the_built_in_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        assert _steps.effective_pipeline_source("myapp") == "built-in default"


_TWO_STEP_YAML = "name: two\nsteps:\n  - kickoff: lead\n  - assemble: implementer\n"


def _write_pod_pipeline(project: str, name: str, text: str) -> None:
    target = current_home().pod_config_dir(project) / "pipelines"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.yaml").write_text(text, encoding="utf-8")


def _queue_task(project: str, **extra: Any) -> None:
    _put_task(project, _make_task(id="task-1", **extra))


class TestTaskPipeline:
    """A task's own ``pipeline`` and ``gate`` are resolved at claim, per task."""

    def test_task_pipeline_name_selects_a_pod_local_pipeline(self, pod_home: Path) -> None:
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        _write_pod_pipeline("myapp", "two", _TWO_STEP_YAML)
        _queue_task("myapp", pipeline="two")

        results = _sweep.dispatch_pod("myapp", runner=FakeDriver())

        assert [h.step_id for h in results[0].hops] == ["kickoff", "assemble"]
        assert TaskRepository.for_pod("myapp").list()[0].pipeline_source == "pod:two"

    def test_a_task_without_a_pipeline_runs_the_pods_default(self, pod_home: Path) -> None:
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        _write_pod_pipeline("myapp", "two", _TWO_STEP_YAML)
        _queue_task("myapp")

        results = _sweep.dispatch_pod("myapp", runner=FakeDriver())

        assert [h.step_id for h in results[0].hops] == ["kickoff"]
        stored = TaskRepository.for_pod("myapp").list()[0]
        assert stored.pipeline_source == "default"
        assert stored.gate_applied is False

    def test_a_shipped_recipe_name_resolves_its_pipeline(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        default = _steps.effective_pipeline("myapp", None)

        spec, source = _steps._task_pipeline(
            "myapp", TaskRecord(description="x", pipeline="tdd"), default
        )

        assert source == "recipe:tdd"
        assert spec.name == "tdd"

    def test_a_pod_local_pipeline_beats_a_recipe_of_the_same_name(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _write_pod_pipeline("myapp", "tdd", _TWO_STEP_YAML.replace("name: two", "name: mine"))
        default = _steps.effective_pipeline("myapp", None)

        spec, source = _steps._task_pipeline(
            "myapp", TaskRecord(description="x", pipeline="tdd"), default
        )

        assert (source, spec.name) == ("pod:tdd", "mine")

    @pytest.mark.parametrize("name", ["nope", "../etc", "/etc", "a/b", "UPPER", "policies-only"])
    def test_an_unresolvable_name_is_refused(self, pod_home: Path, name: str) -> None:
        _seed_lean_pod("myapp")
        default = _steps.effective_pipeline("myapp", None)

        with pytest.raises(_task.DispatchError):
            _steps._task_pipeline("myapp", TaskRecord(description="x", pipeline=name), default)

    def test_an_unknown_pipeline_fails_the_task_before_any_hop(self, pod_home: Path) -> None:
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _queue_task("myapp", pipeline="nope")
        driver = FakeDriver()

        results = _sweep.dispatch_pod("myapp", runner=driver)

        stored = TaskRepository.for_pod("myapp").list()[0]
        assert driver.calls == []
        assert [r.status for r in results] == ["failed"]
        assert stored.status == "failed"
        assert stored.failure_kind == "pipeline"
        assert "nope" in stored.reason
        assert stored.hops == []
        assert stored.claim_pid is None
        tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
        refused = [e for e in _trace.read_trace(tf) if e["event_type"] == "dispatch_refused"]
        assert len(refused) == 1
        assert "nope" in refused[0]["payload"]["reason"]

    def test_a_refused_task_does_not_stop_the_next_one(self, pod_home: Path) -> None:
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        put_tasks(
            "myapp",
            _make_task(id="task-1", priority="high", pipeline="nope"),
            _make_task(id="task-2", description="y"),
        )

        results = _sweep.dispatch_pod("myapp", runner=FakeDriver())

        assert [(r.task_id, r.status) for r in results] == [
            ("task-1", "failed"),
            ("task-2", "done"),
        ]

    def test_a_pipeline_refusal_is_not_resumable(self, pod_home: Path) -> None:
        assert "pipeline" not in _state.RESUMABLE_FAILURE_KINDS

    def test_a_pipeline_with_unresolved_variables_refuses_the_task(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _write_pod_pipeline(
            "myapp",
            "needs",
            "name: needs\nvariables:\n  ticket: {required: true}\nsteps:\n"
            "  - kickoff: lead\n    instructions: work on ${ticket}\n",
        )
        _queue_task("myapp", pipeline="needs")

        _sweep.dispatch_pod("myapp", runner=lambda *a, **k: _rd.TurnResult(True, "x", 0.0, {}))

        assert TaskRepository.for_pod("myapp").list()[0].failure_kind == "pipeline"


class TestTaskGate:
    def test_the_gate_maps_exit_codes_over_the_defaults(self) -> None:
        gate = _steps._task_gate(
            TaskRecord(
                description="x",
                gate=TaskGate(command="x", timeoutS=9, map={"3": "needs_human", "5": "fail"}),
            )
        )

        assert gate is not None
        assert gate.timeout == 9
        assert [gate.label_for(c) for c in (0, 1, 2, 3, 5, 4)] == [
            "pass",
            "fail",
            "needs_human",
            "needs_human",
            "fail",
            "error",
        ]

    def test_no_gate_is_none(self) -> None:
        assert _steps._task_gate(TaskRecord(description="x")) is None

    def test_a_gate_mapping_to_an_unknown_label_is_refused(self) -> None:
        task = TaskRecord(description="x", gate=TaskGate(command="x", map={"0": "weird"}))

        with pytest.raises(_task.DispatchError):
            _steps._task_gate(task)

    def test_the_gate_attaches_to_the_last_implementer_step(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="p",
            steps=[
                _step.Step(id="a", role="implementer"),
                _step.Step(id="lead", role="lead"),
                _step.Step(id="b", role="implementer"),
                _step.Step(id="c", role="lead"),
            ],
        )
        plan = _orch.resolve_plan(
            spec, _pod.pod_full_roster("myapp"), registry=_archetypes.load_registry()
        )

        assert _steps._task_gate_step_id(plan.runnable_nodes()) == "b"

    def test_without_an_implementer_the_gate_attaches_to_the_last_agent_step(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="p",
            steps=[_step.Step(id="a", role="lead"), _step.Step(id="r", run="true")],
        )
        plan = _orch.resolve_plan(
            spec, _pod.pod_full_roster("myapp"), registry=_archetypes.load_registry()
        )

        assert _steps._task_gate_step_id(plan.runnable_nodes()) == "a"


class TestTaskPipelineScopes:
    """`_task_pipeline_file` reads `Home.scopes("pipelines", project)`, then the recipes."""

    def _put(self, directory: Path, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.yaml").write_text("name: x\n")

    def test_the_operators_pipeline_resolves_with_its_scope_in_the_label(self) -> None:
        self._put(current_home().pipelines_dir, "fast")

        found = _steps._task_pipeline_file("demo", "fast")

        assert found is not None and found[1] == "operator:fast"

    def test_the_pod_overlay_beats_the_operator(self) -> None:
        self._put(current_home().pipelines_dir, "fast")
        self._put(current_home().pod_config_dir("demo") / "pipelines", "fast")

        found = _steps._task_pipeline_file("demo", "fast")

        assert found is not None and found[1] == "pod:fast"
        other = _steps._task_pipeline_file("other", "fast")
        assert other is not None and other[1] == "operator:fast"

    def test_a_recipe_still_resolves_after_the_scopes(self) -> None:
        found = _steps._task_pipeline_file("demo", "secure-build")

        assert found is not None and found[1] == "recipe:secure-build"
