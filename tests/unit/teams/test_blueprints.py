"""Pod blueprints — the format itself (`teams/blueprints.py`).

Covers the registry (the four built-ins, one per pipeline shape), the closed `workspace_kind` enum,
`PodBlueprint.__post_init__`'s structural validation, and the cross-check
that every gated step in a `default_pipeline` matches its role's own
archetype `gateContract.kind` exactly.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _plan
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.teams import blueprints as bp
from docket.teams import pod as _pod
from docket.teams import roles as _arch

SUBJECT = "docket.teams.blueprints"


SHAPES = ["build", "respond", "operate", "routine"]


def _walk(steps: list[_step.Step]) -> list[_step.Step]:
    out: list[_step.Step] = []
    for s in steps:
        if s.parallel:
            out.extend(_walk(s.parallel))
        else:
            out.append(s)
    return out


class TestRegistry:
    def test_the_registry_is_exactly_the_four_shapes(self) -> None:
        assert bp.load_registry().names() == tuple(SHAPES)

    def test_default_blueprint_is_build(self) -> None:
        assert bp.DEFAULT_BLUEPRINT == "build"

    def test_get_blueprint_unknown_raises_with_valid_list(self) -> None:
        with pytest.raises(bp.BlueprintError, match="unknown blueprint"):
            bp.get_blueprint("wizard-pod")
        try:
            bp.get_blueprint("wizard-pod")
        except bp.BlueprintError as exc:
            for name in SHAPES:
                assert name in str(exc)

    @pytest.mark.parametrize("gone", ["software", "content"])
    def test_a_retired_name_is_unknown_and_the_error_names_the_four(self, gone: str) -> None:
        with pytest.raises(bp.BlueprintError) as raised:
            bp.get_blueprint(gone)
        assert all(name in str(raised.value) for name in SHAPES)

    def test_get_blueprint_known_roundtrips(self) -> None:
        for name in bp.load_registry().names():
            assert bp.get_blueprint(name).name == name


class TestWorkspaceKind:
    def test_build_is_codebase(self) -> None:
        assert bp.get_blueprint("build").workspace_kind == "codebase"

    @pytest.mark.parametrize("name", ["respond", "operate", "routine"])
    def test_the_other_shapes_are_workdir(self, name: str) -> None:
        assert bp.get_blueprint(name).workspace_kind == "workdir"

    def test_workspace_kinds_is_closed_pair(self) -> None:
        assert frozenset({"codebase", "workdir"}) == bp.WORKSPACE_KINDS


class TestRosters:
    @pytest.mark.parametrize("name", SHAPES)
    def test_lead_is_first_and_only(self, name: str) -> None:
        roles = bp.get_blueprint(name).roles
        assert roles[0] == "lead"
        assert roles.count("lead") == 1

    @pytest.mark.parametrize("name", SHAPES)
    def test_every_role_is_a_registered_archetype(self, name: str) -> None:
        registry = _arch.load_registry()
        for role in bp.get_blueprint(name).roles:
            assert role in registry, f"{name}: role {role!r} is not a registered archetype"

    @pytest.mark.parametrize(
        ("name", "roles"),
        [
            ("build", ("lead", "implementer", "reviewer")),
            ("respond", ("lead", "researcher", "writer", "reviewer", "actor")),
            ("operate", ("lead", "monitor", "operator", "reviewer")),
            ("routine", ("lead", "analyst", "writer", "reviewer")),
        ],
    )
    def test_the_roster_of_each_shape(self, name: str, roles: tuple[str, ...]) -> None:
        assert bp.get_blueprint(name).roles == roles

    def test_build_roster_is_the_full_pod(self) -> None:
        assert bp.get_blueprint("build").roles == _pod.FULL_POD_ROLES


class TestEachShapesPipeline:
    @pytest.mark.parametrize("name", SHAPES)
    def test_every_steps_role_is_in_the_roster_and_the_plan_skips_nothing(self, name: str) -> None:
        blueprint = bp.get_blueprint(name)
        for step in _walk(blueprint.default_pipeline.steps):
            assert step.role in blueprint.roles, f"{name}/{step.id}: {step.role!r} not in roster"
        roster = {role: f"demo-{role}" for role in blueprint.roles}
        plan = _plan.resolve_plan(
            blueprint.default_pipeline, roster, registry=_arch.load_registry()
        )
        assert [n for n in plan.nodes if getattr(n, "skipped", False)] == []

    def test_respond_runs_intake_research_draft_review_act_and_the_actor_acts(self) -> None:
        steps = bp.get_blueprint("respond").default_pipeline.steps
        assert [(s.id, s.role) for s in steps] == [
            ("intake", "lead"),
            ("research", "researcher"),
            ("draft", "writer"),
            ("review", "reviewer"),
            ("act", "actor"),
        ]
        act = next(s for s in steps if s.id == "act")
        assert act.role == "actor"
        review = next(s for s in steps if s.id == "review")
        assert isinstance(review.gate, _gates.VerdictGate)
        assert review.gate.rework is not None and review.gate.rework.to == "draft"

    def test_operate_watches_proposes_behind_approval_acts_mechanically_and_reviews(self) -> None:
        steps = bp.get_blueprint("operate").default_pipeline.steps
        assert [(s.id, s.role) for s in steps] == [
            ("watch", "lead"),
            ("propose", "monitor"),
            ("act", "operator"),
            ("review", "reviewer"),
        ]
        assert isinstance(steps[1].gate, _gates.ApprovalGate)
        assert isinstance(steps[2].gate, _gates.MechanicalGate)
        assert isinstance(steps[3].gate, _gates.VerdictGate)

    def test_routine_compiles_drafts_and_reviews(self) -> None:
        steps = bp.get_blueprint("routine").default_pipeline.steps
        assert [(s.id, s.role) for s in steps] == [
            ("compile", "analyst"),
            ("draft", "writer"),
            ("review", "reviewer"),
        ]
        review = steps[2]
        assert isinstance(review.gate, _gates.VerdictGate)
        assert review.gate.rework is not None and review.gate.rework.to == "draft"

    def test_build_is_the_core_pipeline_default(self) -> None:
        expected = _pipeline.default_pipeline()
        actual = bp.get_blueprint("build").default_pipeline
        assert actual.model_dump() == expected.model_dump()


class TestBudgets:
    def test_build_has_no_default_budget_cap(self) -> None:
        assert bp.get_blueprint("build").default_budget_usd is None

    @pytest.mark.parametrize("name", ["respond", "operate", "routine"])
    def test_task_shaped_workdir_blueprints_carry_a_cap(self, name: str) -> None:
        cap = bp.get_blueprint(name).default_budget_usd
        assert cap is not None and cap > 0


class TestValidation:
    def _valid_kwargs(self) -> dict[str, object]:
        return {
            "name": "producer",
            "version": 1,
            "workspace_kind": "workdir",
            "roles": ("lead", "writer"),
            "default_pipeline": _pipeline.PipelineSpec(
                name="producer-default", steps=[_step.Step(id="lead", role="lead")]
            ),
        }

    def test_invalid_name_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["name"] = "Producer Pod"
        with pytest.raises(bp.BlueprintError, match="invalid blueprint name"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_non_positive_version_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["version"] = 0
        with pytest.raises(bp.BlueprintError, match="version must be a positive integer"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_unknown_workspace_kind_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["workspace_kind"] = "container"
        with pytest.raises(bp.BlueprintError, match="unknown workspaceKind"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_empty_roles_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["roles"] = ()
        with pytest.raises(bp.BlueprintError, match="roles must not be empty"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_roles_not_starting_with_lead_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["roles"] = ("writer", "lead")
        with pytest.raises(bp.BlueprintError, match="first role must be 'lead'"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_duplicate_lead_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["roles"] = ("lead", "lead", "writer")
        with pytest.raises(bp.BlueprintError, match="only one lead"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_negative_budget_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["default_budget_usd"] = -5.0
        with pytest.raises(bp.BlueprintError, match="default_budget_usd must be >= 0"):
            bp.PodBlueprint(**kwargs)  # type: ignore[arg-type]

    def test_valid_blueprint_constructs(self) -> None:
        assert bp.PodBlueprint(**self._valid_kwargs()).name == "producer"  # type: ignore[arg-type]


class TestPipelineGateFidelity:
    """Every step in a blueprint's default_pipeline carries the gate its role's own archetype
    gateContract.kind names -- no separate 'default gates' field to drift from the pipeline."""

    _GATE_TYPE_FOR_KIND: ClassVar[dict[str, str]] = {
        "mechanical": "mechanical",
        "verdict": "verdict",
        "approval": "approval",
    }

    @pytest.mark.parametrize("name", SHAPES)
    def test_gates_match_archetype_gate_contract(self, name: str) -> None:
        registry = _arch.load_registry()
        blueprint = bp.get_blueprint(name)
        for step in _walk(blueprint.default_pipeline.steps):
            if step.role is None:
                continue
            arch = registry.get(step.role)
            assert arch is not None, f"{name}: step {step.id!r} references unknown role"
            expected_kind = arch.gate_contract.kind
            if expected_kind == "none":
                assert step.gate is None, f"{name}/{step.id}: expected no gate"
            else:
                assert step.gate is not None, f"{name}/{step.id}: expected a {expected_kind} gate"
                assert step.gate.type == self._GATE_TYPE_FOR_KIND[expected_kind], (
                    f"{name}/{step.id}: gate type {step.gate.type!r} != "
                    f"archetype gateContract.kind {expected_kind!r}"
                )


class TestLeadStepInstructions:
    """respond and operate name their own next role on the Lead step, since neither has an
    Implementer for the built-in `lead` archetype's generic instruction to point at; build declares
    no override and keeps that generic text."""

    def _lead_step(self, blueprint_name: str) -> _step.Step:
        pipeline = bp.get_blueprint(blueprint_name).default_pipeline
        (lead_step,) = [s for s in pipeline.steps if s.role == "lead"]
        return lead_step

    @pytest.mark.parametrize(
        ("name", "next_role"), [("respond", "Researcher"), ("operate", "Monitor")]
    )
    def test_the_lead_names_the_role_that_follows(self, name: str, next_role: str) -> None:
        step = self._lead_step(name)
        assert step.instructions is not None
        assert next_role in step.instructions
        assert "Implementer" not in step.instructions

    def test_build_leaves_the_lead_step_unset(self) -> None:
        assert self._lead_step("build").instructions is None
