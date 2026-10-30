"""A ``wait`` step: its duration grammar, the keys it refuses, its ``timeout`` route and its plan.
See specs/functional/pipeline-format.spec.md ("Wait steps")."""

from __future__ import annotations

import pytest

from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.spec import load_pipeline
from docket.pipeline.domain.step import Step, WaitUntil, parse_duration
from docket.teams import roles as _archetypes

SUBJECT = "docket.pipeline.domain.step"


def _load(steps: str) -> tuple[object, list[str]]:
    result = load_pipeline(f"name: p\nsteps:\n{steps}")
    return result.spec, result.errors


def _errors(steps: str) -> str:
    spec, errors = _load(steps)
    assert spec is None, "expected a validation error"
    return "; ".join(errors)


class TestDuration:
    @pytest.mark.parametrize(
        ("text", "seconds"),
        [("1s", 1), ("90s", 90), ("15m", 900), ("72h", 259200), ("3d", 259200)],
    )
    def test_a_duration_is_a_count_and_a_unit(self, text: str, seconds: int) -> None:
        assert parse_duration(text) == seconds

    @pytest.mark.parametrize("text", ["", "5", "0s", "-1m", "1.5h", "1w", "h", " 5m", "5m "])
    def test_anything_else_is_refused(self, text: str) -> None:
        with pytest.raises(ValueError, match="duration"):
            parse_duration(text)


class TestShape:
    def test_a_timer_parses_from_the_short_form(self) -> None:
        spec, errors = _load("  - writer: writer\n  - hold: {wait: 72h}\n  - reviewer: reviewer\n")
        assert errors == []
        step = spec.steps[1]  # type: ignore[attr-defined]
        assert (step.id, step.wait, step.until) == ("hold", "72h", None)

    def test_a_probe_parses_with_its_timeout_route(self) -> None:
        spec, errors = _load(
            "  - writer: writer\n"
            "  - hold:\n"
            "      wait: 1h\n"
            "      until: {run: 'test -f ready', every: 15m}\n"
            "      on: {timeout: fail}\n"
            "  - reviewer: reviewer\n"
        )
        assert errors == []
        step = spec.steps[1]  # type: ignore[attr-defined]
        assert step.until == WaitUntil(run="test -f ready", every="15m")
        assert step.on == {"timeout": "fail"}

    def test_until_without_wait_names_the_step(self) -> None:
        message = _errors("  - hold: {until: {run: 'true', every: 1m}}\n")
        assert "hold" in message

    @pytest.mark.parametrize("duration", ["''", "5", "0s", "soon"])
    def test_a_wait_without_a_duration_names_the_step(self, duration: str) -> None:
        message = _errors(f"  - writer: writer\n  - hold: {{wait: {duration}}}\n")
        assert "hold" in message
        assert "duration" in message

    def test_a_bare_wait_key_names_the_step(self) -> None:
        message = _errors("  - hold: {wait: }\n")
        assert "hold" in message

    @pytest.mark.parametrize("until", ["{run: '', every: 1m}", "{run: 'true', every: never}"])
    def test_a_probe_needs_a_command_and_an_interval(self, until: str) -> None:
        message = _errors(f"  - hold: {{wait: 1h, until: {until}}}\n")
        assert "hold" in message

    def test_a_probe_with_an_unknown_key_is_refused(self) -> None:
        message = _errors("  - hold: {wait: 1h, until: {run: 'true', every: 1m, tries: 3}}\n")
        assert "tries" in message

    @pytest.mark.parametrize(
        "extra",
        [
            {"role": "writer"},
            {"run": "true"},
            {"gate": {"type": "approval"}},
            {"timeout": 5},
            {"retries": 1},
            {"instructions": "x"},
            {"env": {"A": "b"}},
        ],
    )
    def test_a_wait_step_carries_no_hop_fields(self, extra: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="hold"):
            Step.model_validate({"id": "hold", "wait": "1h", **extra})

    def test_a_wait_step_and_an_input_step_are_exclusive(self) -> None:
        with pytest.raises(ValueError, match="hold"):
            Step.model_validate({"id": "hold", "wait": "1h", "input": {"from": "a"}})

    def test_a_wait_step_may_carry_a_when(self) -> None:
        spec, errors = _load(
            "  - writer: writer\n  - hold: {wait: 1h, when: {var: go, is: 'yes'}}\n"
        )
        assert errors == []
        assert spec.steps[1].when is not None  # type: ignore[attr-defined]

    def test_a_parallel_child_cannot_wait(self) -> None:
        message = _errors("  - fan:\n      parallel:\n        - a: {wait: 1h}\n")
        assert "wait" in message


class TestTimeoutRoute:
    def test_only_the_timeout_key_is_allowed(self) -> None:
        message = _errors(
            "  - hold:\n      wait: 1h\n      until: {run: 'true', every: 1m}\n"
            "      on: {answered: stop}\n"
        )
        assert "hold" in message
        assert "timeout" in message

    def test_a_timeout_route_needs_a_probe(self) -> None:
        message = _errors("  - hold: {wait: 1h, on: {timeout: fail}}\n  - reviewer: reviewer\n")
        assert "hold" in message

    def test_a_backward_timeout_route_needs_max(self) -> None:
        message = _errors(
            "  - writer: writer\n  - hold:\n      wait: 1h\n"
            "      until: {run: 'true', every: 1m}\n      on: {timeout: writer}\n"
        )
        assert "max" in message


class TestPlan:
    def _plan(self, steps: str) -> _orch.ExecutionPlan:
        spec, errors = _load(steps)
        assert errors == []
        return _orch.resolve_plan(
            spec,  # type: ignore[arg-type]
            {"writer": "pod-writer", "reviewer": "pod-reviewer"},
            registry=_archetypes.load_registry(),
        )

    def test_a_wait_step_is_planned_without_a_member_and_is_never_skipped(self) -> None:
        plan = self._plan("  - hold: {wait: 90s}\n  - reviewer: reviewer\n")
        unit = plan.runnable_nodes()[0]
        assert isinstance(unit, _orch.PlannedUnit)
        assert (unit.wait, unit.member_id, unit.skipped) == ("90s", None, False)

    def test_the_rendering_names_the_wait_and_the_probe(self) -> None:
        plan = self._plan(
            "  - hold: {wait: 1h, until: {run: 'test -f ready', every: 5m}}\n"
            "  - quiet: {wait: 30s}\n"
        )
        text = _orch.render_plan(plan)
        assert "waits up to 1h, probing 'test -f ready' every 5m" in text
        assert "waits 30s" in text
