"""W-7: pod blueprints — the format itself (`core/blueprints.py`).

Covers the registry (five built-ins as of ROADMAP Phase 21 P21-5), the closed
`workspace_kind` enum, the structural validation `PodBlueprint.__post_init__`
enforces, and the cross-check that every gated step in a blueprint's
`default_pipeline` matches the gated role's own archetype `gateContract.kind`
exactly (no drift between "the roster" and "the pipeline" — see
`core/blueprints.py`'s module docstring). Provisioning end-to-end (workspace
files, `.docket-meta.json`, `--from spec.yaml`, `docket doctor`) is covered
by test_w7_provisioning.py.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from docket.core import archetypes as _arch
from docket.core import blueprints as bp
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod


class TestRegistry:
    def test_five_builtins_registered(self) -> None:
        names = set(bp.load_registry().names())
        assert names == {"software", "research", "content", "ops", "agentic-product"}

    def test_default_blueprint_is_software(self) -> None:
        assert bp.DEFAULT_BLUEPRINT == "software"

    def test_get_blueprint_unknown_raises_with_valid_list(self) -> None:
        with pytest.raises(bp.BlueprintError, match="unknown blueprint"):
            bp.get_blueprint("wizard-pod")
        try:
            bp.get_blueprint("wizard-pod")
        except bp.BlueprintError as exc:
            for name in ("software", "research", "content", "ops", "agentic-product"):
                assert name in str(exc)

    def test_get_blueprint_known_roundtrips(self) -> None:
        for name in bp.load_registry().names():
            assert bp.get_blueprint(name).name == name


class TestWorkspaceKind:
    @pytest.mark.parametrize("name", ["software", "agentic-product"])
    def test_codebase_blueprints_are_codebase(self, name: str) -> None:
        assert bp.get_blueprint(name).workspace_kind == "codebase"

    @pytest.mark.parametrize("name", ["research", "content", "ops"])
    def test_non_software_are_workdir(self, name: str) -> None:
        assert bp.get_blueprint(name).workspace_kind == "workdir"

    def test_workspace_kinds_is_closed_pair(self) -> None:
        assert frozenset({"codebase", "workdir"}) == bp.WORKSPACE_KINDS


class TestRosterInvariants:
    @pytest.mark.parametrize("name", ["software", "research", "content", "ops", "agentic-product"])
    def test_lead_is_first_and_only(self, name: str) -> None:
        roles = bp.get_blueprint(name).roles
        assert roles[0] == "lead"
        assert roles.count("lead") == 1

    def test_software_roster_matches_pod_default(self) -> None:
        assert bp.get_blueprint("software").roles == _pod.DEFAULT_POD_ROLES

    @pytest.mark.parametrize("name", ["software", "research", "content", "ops", "agentic-product"])
    def test_every_role_is_a_registered_archetype(self, name: str) -> None:
        registry = _arch.load_registry()
        for role in bp.get_blueprint(name).roles:
            assert role in registry, f"{name}: role {role!r} is not a registered archetype"


class TestValidation:
    def _valid_kwargs(self) -> dict[str, object]:
        return {
            "name": "producer",
            "version": 1,
            "workspace_kind": "workdir",
            "roles": ("lead", "writer"),
            "default_pipeline": _pipeline.PipelineSpec(
                name="producer-default", steps=[_pipeline.Step(id="lead", role="lead")]
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
    """Every gated step in a blueprint's default_pipeline matches its role's
    own archetype gateContract.kind exactly — no separate 'default gates'
    field to drift from the pipeline (see core/blueprints.py's docstring).
    """

    _GATE_TYPE_FOR_KIND: ClassVar[dict[str, str]] = {
        "mechanical": "mechanical",
        "verdict": "verdict",
        "approval": "approval",
    }

    @pytest.mark.parametrize("name", ["software", "research", "content", "ops", "agentic-product"])
    def test_gates_match_archetype_gate_contract(self, name: str) -> None:
        registry = _arch.load_registry()
        blueprint = bp.get_blueprint(name)

        def _walk(steps: list[_pipeline.Step]) -> list[_pipeline.Step]:
            out: list[_pipeline.Step] = []
            for s in steps:
                if s.parallel:
                    out.extend(_walk(s.parallel))
                else:
                    out.append(s)
            return out

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

    def test_software_pipeline_is_the_core_pipeline_default(self) -> None:
        # Byte-for-byte the same object core/dispatch.py's hardcoded pipeline
        # mirrors (core/pipeline.py's own zero-migration contract) — the
        # software blueprint doesn't hand-roll a second copy.
        expected = _pipeline.default_pipeline()
        actual = bp.get_blueprint("software").default_pipeline
        assert [s.id for s in actual.steps] == [s.id for s in expected.steps]
        assert actual.model_dump() == expected.model_dump()


class TestAgenticProduct:
    """ROADMAP Phase 21 P21-5: `agentic-product` is a fifth row of data, not
    new machinery — same `default_pipeline()` object `software` attaches, a
    `codebase` workspace kind, and the one deliberate difference from
    `software`: a full (Lead, Implementer, Reviewer, Tester) roster so the
    Reviewer/Tester gates already present in `default_pipeline()` actually
    engage at dispatch time instead of going unreached.
    """

    def test_roster_is_full_pod_roles(self) -> None:
        assert bp.get_blueprint("agentic-product").roles == _pod.FULL_POD_ROLES

    def test_workspace_kind_is_codebase(self) -> None:
        assert bp.get_blueprint("agentic-product").workspace_kind == "codebase"

    def test_no_default_budget_cap(self) -> None:
        # Matches `software`, the other codebase-kind blueprint: an ongoing
        # project pod gets no preset spend ceiling, unlike the three
        # task-shaped workdir blueprints (research/content/ops).
        assert bp.get_blueprint("agentic-product").default_budget_usd is None

    def test_pipeline_is_the_same_object_as_software(self) -> None:
        # No new pipeline/gate design for this card: agentic-product reuses
        # core.pipeline.default_pipeline() verbatim, the same as software.
        software_pipeline = bp.get_blueprint("software").default_pipeline
        agentic_pipeline = bp.get_blueprint("agentic-product").default_pipeline
        assert agentic_pipeline.model_dump() == software_pipeline.model_dump()

    def test_description_names_docket_runtime(self) -> None:
        assert "docket-runtime" in bp.get_blueprint("agentic-product").description
