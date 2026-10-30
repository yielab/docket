"""The pipeline spec: zero migration, loading, outcome routing, input steps and refused shapes."""

from __future__ import annotations

import sys

import pytest
from tests.support.roles import ROLE_NAMES

from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.gates import MechanicalGate, VerdictGate
from docket.pipeline.domain.spec import (
    PipelineSpec,
    default_pipeline,
    load_pipeline,
)
from docket.pipeline.domain.step import Step
from docket.teams import pod as _pod
from docket.teams import roles as _archetypes

SUBJECT = "docket.pipeline.domain.spec"


_HEAD = "name: p\nsteps:\n"


_UNIT_A = "  - a: lead\n"


_UNIT_B = "  - b: implementer\n"


_CHILD = "      - c: reviewer\n"


def _refused(body: str, *needles: str) -> None:
    result = load_pipeline(_HEAD + body, roles=ROLE_NAMES)
    assert not result.ok, "the loader accepted a shape the executor cannot run"
    joined = " | ".join(result.errors)
    for needle in needles:
        assert needle in joined, joined


class TestZeroMigration:
    """Absence of a pipeline file MUST mean today's built-in dispatch order,
    byte-identical -- drift-guarded against ``core/dispatch.py``'s own
    constants, not a hand-copied literal, so real drift fails this suite."""

    def test_no_text_returns_builtin_source(self) -> None:
        result = load_pipeline(None, roles=ROLE_NAMES)
        assert result.source == "builtin"
        assert result.ok

    def test_builtin_role_order_matches_dispatch_pipeline_order(self) -> None:
        spec = default_pipeline()
        assert tuple(s.role for s in spec.steps) == _pod.PIPELINE_ORDER

    def test_builtin_lead_has_no_gate(self) -> None:
        spec = default_pipeline()
        lead = next(s for s in spec.steps if s.id == "lead")
        assert lead.gate is None

    def test_builtin_implementer_gate_defers_to_verify_cmd(self) -> None:
        spec = default_pipeline()
        implementer = next(s for s in spec.steps if s.id == "implementer")
        assert isinstance(implementer.gate, MechanicalGate)
        assert implementer.gate.command is None

    def test_builtin_reviewer_pattern_matches_archetype_resolved_gate(self) -> None:
        """Gate execution reads a step's resolved gate generically, not a
        dispatch-private regex constant: checks the format's hardcoded
        default agrees with the archetype registry's ``gateContract``."""
        spec = default_pipeline()
        reviewer = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer.gate, VerdictGate)
        registry = _archetypes.load_registry()
        bare_step = Step(id="probe", role="reviewer")  # no gate of its own
        resolved = _orch.resolve_gate(bare_step, registry)
        assert isinstance(resolved, VerdictGate)
        assert reviewer.gate.pattern == resolved.pattern
        # Both sides are case_sensitive=False, so only case-insensitive
        # agreement is required — the pipeline default happens to spell its
        # passValues lowercase, the archetype's regexes upper-case.
        assert [v.lower() for v in reviewer.gate.pass_values] == [
            v.lower() for v in resolved.pass_values
        ]
        assert reviewer.gate.pass_values == ["approve"]

    def test_builtin_reviewer_rework_targets_implementer_default_one_cycle(self) -> None:
        spec = default_pipeline()
        reviewer = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer.gate, VerdictGate)
        assert reviewer.gate.rework is not None
        assert reviewer.gate.rework.to == "implementer"
        assert reviewer.gate.rework.when == ["request-changes"]
        assert reviewer.gate.rework.max_cycles == 1

    def test_builtin_pipeline_ends_at_the_reviewer(self) -> None:
        assert [s.id for s in default_pipeline().steps] == ["lead", "implementer", "reviewer"]

    def test_builtin_pipeline_itself_is_valid(self) -> None:
        # default_pipeline() must satisfy every validator PipelineSpec enforces
        # for a hand-authored file — it is not exempt from its own rules.
        dumped = default_pipeline().model_dump(by_alias=True)
        PipelineSpec.model_validate(dumped)  # raises on failure


class TestLoadPipeline:
    def test_yaml_parse_error(self) -> None:
        result = load_pipeline("name: test\nsteps:\n  - {\n", roles=ROLE_NAMES)
        assert not result.ok
        assert result.spec is None
        assert any("YAML parse error" in e for e in result.errors)

    def test_empty_document_is_an_error(self) -> None:
        result = load_pipeline("", roles=ROLE_NAMES)
        assert not result.ok
        assert result.source == "file"

    def test_non_mapping_document_is_an_error(self) -> None:
        result = load_pipeline("- just\n- a\n- list\n", roles=ROLE_NAMES)
        assert not result.ok
        assert any("mapping" in e for e in result.errors)

    def test_missing_name_rejected(self) -> None:
        result = load_pipeline("steps:\n  - s1: lead\n", roles=ROLE_NAMES)
        assert not result.ok

    def test_missing_steps_rejected(self) -> None:
        result = load_pipeline("name: p\n", roles=ROLE_NAMES)
        assert not result.ok

    def test_missing_pyyaml_gives_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "yaml", None)
        result = load_pipeline("name: p\nsteps:\n  - s1: lead\n", roles=ROLE_NAMES)
        assert not result.ok
        assert any("pyyaml" in e.lower() for e in result.errors)


class TestOutcomeRouting:
    def test_until_verify_sugar_normalises_to_bounded_fail_route_and_loads(self) -> None:
        # On the base this rejects outright: `until`/`max` were not yet
        # recognized short-form sugar keys, so the step entry was left as an
        # invalid canonical mapping ("build"/"until"/"max" all read as
        # unknown `Step` fields alongside a missing `id`).
        text = """\
name: p
steps:
  - plan: lead
  - build: implementer
    verify: true
    until: verify
    max: 2
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert result.ok, result.errors
        assert result.spec is not None
        build = result.spec.steps[1]
        assert build.on == {"fail": {"goto": "build", "max": 2}}
        assert build.gate == MechanicalGate()

    def test_unreachable_step_is_a_load_error_naming_it(self) -> None:
        # On the base this also rejects, but for an unrelated reason: `Step`
        # had no `on` field at all yet, and PyYAML's bare `on:` key resolves
        # to the boolean `True`, which pydantic refuses outright ("Keys
        # should be strings") long before any notion of reachability exists.
        text = """\
name: p
steps:
  - plan: lead
  - build: implementer
    verify: true
    on:
      pass: stop
      fail: stop
  - dead: implementer
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert not result.ok
        assert len(result.errors) == 1
        assert "dead" in result.errors[0]


class TestInputSteps:
    def test_valid_input_step_parses_and_renders(self) -> None:
        text = """\
name: p
steps:
  - triage: lead
  - ask:
      input:
        from: triage
        message: "Confirm the approach?"
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert result.ok, result.errors
        assert result.spec is not None
        ask = result.spec.steps[1]
        assert ask.input is not None
        assert ask.input.from_ == "triage"
        assert ask.input.message == "Confirm the approach?"

        plan = _orch.resolve_plan(result.spec, {}, registry=_archetypes.load_registry())
        assert "asks the operator (from triage)" in _orch.render_plan(plan)

    def test_input_step_cannot_also_set_role(self) -> None:
        text = """\
name: p
steps:
  - triage: lead
  - ask: implementer
    input:
      from: triage
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert not result.ok
        assert len(result.errors) == 1
        assert "'ask'" in result.errors[0]
        assert "'input'" in result.errors[0]

    def test_input_step_from_references_nonexistent_step(self) -> None:
        text = """\
name: p
steps:
  - triage: lead
  - ask:
      input:
        from: no_such_step
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert not result.ok
        assert len(result.errors) == 1
        assert "ask" in result.errors[0]
        assert "no_such_step" in result.errors[0]

    def test_input_step_from_references_later_step(self) -> None:
        text = """\
name: p
steps:
  - triage: lead
  - ask:
      input:
        from: plan
  - plan: implementer
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert not result.ok
        assert len(result.errors) == 1
        assert "ask" in result.errors[0]
        assert "plan" in result.errors[0]
        assert "earlier" in result.errors[0]

    def test_input_step_on_keys_must_be_subset_of_answered_declined(self) -> None:
        text = """\
name: p
steps:
  - triage: lead
  - ask:
      input:
        from: triage
      on:
        answered: pass
        unknown_key: fail
"""
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert not result.ok
        assert len(result.errors) == 1
        assert "ask" in result.errors[0]
        assert "unknown_key" in result.errors[0]


class TestRefusedShapes:
    """A shape the executor cannot run is a load error naming the field, not silence."""

    @pytest.mark.parametrize(
        "field_yaml",
        [
            "      run: echo hi\n",
            "      input:\n        from: a\n",
            "      when:\n        memberPresent: lead\n",
            "      archetype: reviewer\n",
        ],
    )
    def test_parallel_group_carries_only_its_children(self, field_yaml: str) -> None:
        body = _UNIT_A + "  - g:\n" + field_yaml + "      parallel:\n" + _CHILD
        _refused(body, "'g'", "parallel group carries only 'parallel'")

    def test_step_with_run_and_input_refused(self) -> None:
        body = _UNIT_A + "  - ask:\n      run: echo hi\n      input:\n        from: a\n"
        _refused(body, "'ask'", "'run'", "'input'")

    @pytest.mark.parametrize("bad_max", ["0", "-1", "x", "true", "1.5"])
    def test_forward_route_with_invalid_max_refused(self, bad_max: str) -> None:
        body = (
            "  - a: implementer\n    verify: true\n"
            f"    on:\n      fail: {{goto: b, max: {bad_max}}}\n" + _UNIT_B
        )
        _refused(body, "'a'", "'max'")

    def test_forward_route_with_valid_max_accepted(self) -> None:
        body = (
            "  - a: implementer\n    verify: true\n"
            "    on:\n      fail: {goto: b, max: 2}\n" + _UNIT_B
        )
        assert load_pipeline(_HEAD + body, roles=ROLE_NAMES).ok

    @pytest.mark.parametrize(
        ("child_yaml", "field"),
        [
            ("      - c:\n          run: echo hi\n", "run"),
            ("      - c:\n          input:\n            from: a\n", "input"),
            ("      - c: reviewer\n        when:\n          memberPresent: lead\n", "when"),
            ("      - c: reviewer\n        on:\n          fail: stop\n", "on"),
            ('      - c: reviewer\n        "on":\n          fail: stop\n', "on"),
        ],
    )
    def test_parallel_child_refuses_a_field_the_group_never_runs(
        self, child_yaml: str, field: str
    ) -> None:
        # The group's children run through `execute_unit`, which acts on none of these.
        body = _UNIT_A + "  - g:\n      parallel:\n" + child_yaml
        _refused(body, "'c'", f"'{field}'", "parallel")

    def test_parallel_child_with_executed_fields_accepted(self) -> None:
        body = (
            _UNIT_A
            + "  - g:\n      parallel:\n"
            + _CHILD
            + "        retries: 1\n        timeout: 30\n        model: cheap\n"
            + "        archetype: reviewer\n        verify: true\n"
        )
        assert load_pipeline(_HEAD + body, roles=ROLE_NAMES).ok
