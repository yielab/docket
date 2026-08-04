"""`core/orchestrator.py` — the pipeline executor's planning layer.

Covers: `resolve_plan`'s determinism contract (same spec + roster + registry
=> a byte-identical `ExecutionPlan`, independent of wall clock, dict
construction order, or which thread calls it), gate resolution (a step's own
`gate` always wins; only an omitted one falls back to its archetype's
`gateContract`), `parse_verdict`'s generic marker matching, `run_group`'s join
semantics (every child observed before returning, declaration-order results,
contextvars propagated into worker threads), and `render_plan`'s shape.

dispatch.py-level integration — a real parallel group and a real pipeline
`approval` step executed through the R-1 state machine, and gate genericity
for a non-built-in archetype — is covered by `test_w8_generalized_gates.py`,
not repeated here. Cancellation and the `docket pipeline`/`docket runs
cancel` CLI surface have their own test files.
"""

from __future__ import annotations

import contextvars
import threading
import time

import pytest

from docket.core import archetypes as _archetypes
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline


def _sample_spec() -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="sample",
        steps=[
            _pipeline.Step(id="plan", role="lead"),
            _pipeline.Step(
                id="fanout",
                parallel=[
                    _pipeline.Step(id="impl-a", agent="demo-implementer"),
                    _pipeline.Step(id="impl-b", agent="demo-implementer-2"),
                ],
            ),
            _pipeline.Step(
                id="review",
                role="reviewer",
                gate=_pipeline.VerdictGate(pattern=r"^(APPROVE|REJECT)\b", pass_values=["approve"]),
            ),
        ],
    )


def _unit(step_id: str) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role=None,
        agent=step_id,
        archetype=None,
        member_id=step_id,
        gate=None,
        retries=None,
        timeout=None,
    )


# ── determinism contract ──────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_inputs_produce_identical_plan(self) -> None:
        spec = _sample_spec()
        roster = {"lead": "demo-lead", "reviewer": "demo-reviewer"}
        registry = _archetypes.load_registry()
        first = _orch.resolve_plan(spec, roster, registry=registry)
        second = _orch.resolve_plan(spec, roster, registry=registry)
        assert first == second

    def test_determinism_holds_across_threads(self) -> None:
        spec = _sample_spec()
        roster = {"lead": "demo-lead", "reviewer": "demo-reviewer"}
        registry = _archetypes.load_registry()
        results: list[_orch.ExecutionPlan | None] = [None] * 8

        def _worker(i: int) -> None:
            results[i] = _orch.resolve_plan(spec, roster, registry=registry)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert all(r == results[0] for r in results)

    def test_not_sensitive_to_roster_dict_construction_order(self) -> None:
        spec = _sample_spec()
        registry = _archetypes.load_registry()
        roster_a = {"lead": "demo-lead", "reviewer": "demo-reviewer"}
        roster_b = {"reviewer": "demo-reviewer", "lead": "demo-lead"}
        assert _orch.resolve_plan(spec, roster_a, registry=registry) == _orch.resolve_plan(
            spec, roster_b, registry=registry
        )


# ── resolve_plan ──────────────────────────────────────────────────────────────


class TestResolvePlan:
    def test_role_step_skipped_when_pod_lacks_the_role(self) -> None:
        spec = _sample_spec()
        plan = _orch.resolve_plan(spec, {"lead": "demo-lead"})  # no reviewer
        review_node = next(n for n in plan.nodes if n.step_id == "review")
        assert isinstance(review_node, _orch.PlannedUnit)
        assert review_node.skipped is True
        assert review_node.member_id is None
        assert review_node not in plan.runnable_nodes()

    def test_agent_targeted_step_never_skipped(self) -> None:
        spec = _pipeline.PipelineSpec(
            name="s", steps=[_pipeline.Step(id="x", agent="some-agent-not-in-roster")]
        )
        plan = _orch.resolve_plan(spec, {})
        node = plan.nodes[0]
        assert isinstance(node, _orch.PlannedUnit)
        assert node.skipped is False
        assert node.member_id == "some-agent-not-in-roster"

    def test_parallel_group_resolves_each_child(self) -> None:
        spec = _sample_spec()
        plan = _orch.resolve_plan(spec, {"lead": "demo-lead", "reviewer": "demo-reviewer"})
        group = next(n for n in plan.nodes if n.step_id == "fanout")
        assert isinstance(group, _orch.PlannedGroup)
        assert [c.member_id for c in group.children] == ["demo-implementer", "demo-implementer-2"]

    def test_runnable_nodes_preserves_group_and_unit_order(self) -> None:
        spec = _sample_spec()
        plan = _orch.resolve_plan(spec, {"lead": "demo-lead", "reviewer": "demo-reviewer"})
        assert [n.step_id for n in plan.runnable_nodes()] == ["plan", "fanout", "review"]


# ── resolve_gate: W-8's generalization point ─────────────────────────────────


class TestResolveGate:
    def test_steps_own_gate_wins_over_archetype(self) -> None:
        registry = _archetypes.load_registry()
        step = _pipeline.Step(
            id="s", role="implementer", gate=_pipeline.ApprovalGate(message="ship?")
        )
        gate = _orch.resolve_gate(step, registry)
        assert isinstance(gate, _pipeline.ApprovalGate)

    def test_falls_back_to_archetype_gate_contract_when_step_has_none(self) -> None:
        registry = _archetypes.load_registry()
        step = _pipeline.Step(id="s", role="implementer")  # no gate declared
        gate = _orch.resolve_gate(step, registry)
        assert isinstance(gate, _pipeline.MechanicalGate)
        assert gate.command is None

    def test_lead_role_with_no_gate_resolves_to_none(self) -> None:
        registry = _archetypes.load_registry()
        step = _pipeline.Step(id="s", role="lead")
        assert _orch.resolve_gate(step, registry) is None

    def test_unknown_archetype_name_and_no_gate_resolves_to_none(self) -> None:
        registry = _archetypes.load_registry()
        step = _pipeline.Step(id="s", agent="some-agent")  # no role/archetype at all
        assert _orch.resolve_gate(step, registry) is None

    def test_starter_archetype_gate_contract_resolves(self) -> None:
        """A step targeting a non-legacy (starter-library) role with no gate
        of its own still resolves a real gate from that archetype's
        gateContract — the whole point of W-8's generalization."""
        registry = _archetypes.load_registry()
        step = _pipeline.Step(id="s", role="critic")
        gate = _orch.resolve_gate(step, registry)
        assert isinstance(gate, _pipeline.VerdictGate)
        assert gate.pass_values == ["APPROVE"]  # first regex = pass, per convention
        assert _orch.parse_verdict(gate, "approve\nfine") == "approve"
        assert _orch.parse_verdict(gate, "reject\nno") == "reject"

    def test_archetype_gate_contract_never_carries_rework(self) -> None:
        """An archetype's gateContract is descriptive marker data only — no
        rework edge. A pipeline step wanting bounded rework must declare its
        own VerdictGate with an explicit `rework` edge."""
        registry = _archetypes.load_registry()
        step = _pipeline.Step(id="s", role="reviewer")  # no gate of its own
        gate = _orch.resolve_gate(step, registry)
        assert isinstance(gate, _pipeline.VerdictGate)
        assert gate.rework is None


# ── parse_verdict ──────────────────────────────────────────────────────────────


class TestParseVerdict:
    def test_case_insensitive_by_default(self) -> None:
        gate = _pipeline.VerdictGate(pattern=r"^(APPROVE|REJECT)\b", pass_values=["approve"])
        assert _orch.parse_verdict(gate, "approve\nfine") == "approve"

    def test_case_sensitive_gate_respects_case(self) -> None:
        gate = _pipeline.VerdictGate(
            pattern=r"^(APPROVE|REJECT)\b", pass_values=["APPROVE"], case_sensitive=True
        )
        assert _orch.parse_verdict(gate, "approve\nfine") is None  # wrong case -> unparseable
        assert _orch.parse_verdict(gate, "APPROVE\nfine") == "APPROVE"

    def test_unparseable_first_line_returns_none_even_if_a_later_line_matches(self) -> None:
        gate = _pipeline.VerdictGate(pattern=r"^(APPROVE|REJECT)\b", pass_values=["approve"])
        assert _orch.parse_verdict(gate, "not a verdict\nAPPROVE") is None

    def test_leading_blank_lines_are_skipped(self) -> None:
        gate = _pipeline.VerdictGate(pattern=r"^(APPROVE|REJECT)\b", pass_values=["approve"])
        assert _orch.parse_verdict(gate, "\n\nAPPROVE\nfine") == "approve"


# ── run_group: bounded pool, join semantics ───────────────────────────────────


class TestRunGroup:
    def test_empty_children_returns_empty_list(self) -> None:
        assert _orch.run_group((), lambda c: c.step_id) == []

    def test_results_preserve_declaration_order_not_completion_order(self) -> None:
        order: list[str] = []
        lock = threading.Lock()

        def _run(unit: _orch.PlannedUnit) -> str:
            if unit.step_id == "c0":
                time.sleep(0.05)  # c0 finishes LAST despite being declared first
            with lock:
                order.append(unit.step_id)
            return unit.step_id

        children = tuple(_unit(f"c{i}") for i in range(3))
        results = _orch.run_group(children, _run, max_workers=3)
        assert results == ["c0", "c1", "c2"]  # declaration order, not completion order
        assert order[0] != "c0"  # proves c1/c2 actually finished first (real concurrency)

    def test_all_children_are_joined_even_when_one_raises(self) -> None:
        joined: list[str] = []
        lock = threading.Lock()

        def _run(unit: _orch.PlannedUnit) -> str:
            time.sleep(0.02)
            with lock:
                joined.append(unit.step_id)
            if unit.step_id == "c1":
                raise RuntimeError("boom")
            return unit.step_id

        children = tuple(_unit(f"c{i}") for i in range(3))
        with pytest.raises(RuntimeError, match="boom"):
            _orch.run_group(children, _run, max_workers=3)
        assert sorted(joined) == ["c0", "c1", "c2"]  # every child ran to completion

    def test_contextvar_propagates_into_worker_threads(self) -> None:
        probe: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="")
        token = probe.set("outer-value")
        try:
            seen: list[str] = []
            lock = threading.Lock()

            def _run(unit: _orch.PlannedUnit) -> None:
                with lock:
                    seen.append(probe.get())

            children = tuple(_unit(f"c{i}") for i in range(3))
            _orch.run_group(children, _run, max_workers=3)
        finally:
            probe.reset(token)
        assert seen == ["outer-value", "outer-value", "outer-value"]

    def test_max_workers_is_bounded_by_child_count(self) -> None:
        # A single child never spins up more than one worker (no crash, no
        # over-allocation) -- max_workers is a *cap*, not a fixed pool size.
        assert _orch.run_group((_unit("solo"),), lambda u: u.step_id, max_workers=8) == ["solo"]


# ── render_plan: the one and only `docket pipeline plan` renderer ────────────


class TestRenderPlan:
    def test_render_plan_shows_every_node_and_gate(self) -> None:
        spec = _sample_spec()
        plan = _orch.resolve_plan(spec, {"lead": "demo-lead", "reviewer": "demo-reviewer"})
        text = _orch.render_plan(plan)
        assert "Pipeline: sample" in text
        assert "[plan]" in text
        assert "[fanout] parallel:" in text
        assert "demo-implementer" in text
        assert "demo-implementer-2" in text
        assert "[review]" in text
        assert "verdict(approve)" in text

    def test_render_plan_flags_a_skipped_step(self) -> None:
        spec = _sample_spec()
        plan = _orch.resolve_plan(spec, {"lead": "demo-lead"})  # no reviewer
        text = _orch.render_plan(plan)
        assert "skipped" in text
