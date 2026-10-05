"""A ``run`` command step's ``env:`` -- shape validation, short form, planning, and the
environment the command actually sees. See specs/functional/pipeline-format.spec.md
("Conditional steps and command steps") and pod-dispatch.spec.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import secrets as _secrets
from docket.core.pipeline import Step, load_pipeline, normalize_pipeline

from .test_dispatch import _unit_context

SUBJECT = "docket.core.pipeline"


def _errors(**kw: Any) -> str:
    with pytest.raises(ValueError) as info:
        Step(id="check", run="echo hi", **kw)
    return str(info.value)


class TestShape:
    def test_a_run_step_carries_env(self) -> None:
        step = Step(id="check", run="echo hi", env={"FOO": "bar"})
        assert step.env == {"FOO": "bar"}

    def test_env_on_a_role_step_is_refused(self) -> None:
        with pytest.raises(ValueError, match="env"):
            Step(id="build", role="implementer", env={"FOO": "bar"})

    @pytest.mark.parametrize(
        "name",
        ["PATH", "LD_PRELOAD", "PYTHONPATH", "BASH_ENV", "ENV", "DOCKET_BASE_COMMIT", "DOCKET_X"],
    )
    def test_reserved_names_are_refused(self, name: str) -> None:
        assert name in _errors(env={name: "x"})

    @pytest.mark.parametrize("name", ["foo", "1A", "A-B", ""])
    def test_malformed_names_are_refused(self, name: str) -> None:
        assert "env" in _errors(env={name: "x"})

    def test_non_string_values_are_refused(self) -> None:
        with pytest.raises(ValueError):
            Step(id="check", run="echo hi", env={"FOO": 1})  # type: ignore[dict-item]

    def test_a_credential_name_is_refused(self) -> None:
        assert "credential" in _errors(env={"TELEGRAM_BOT_TOKEN": "x"})

    def test_a_secret_store_name_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_secrets, "secrets_keys", lambda: ["MY_STORED_KEY"])
        assert "credential" in _errors(env={"MY_STORED_KEY": "x"})


class TestLoading:
    def test_canonical_and_short_form_carry_env(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: a\n    run: echo a\n    env: {FOO: bar}\n"
            "  - b: {run: echo b, env: {BAZ: qux}}\n"
        )
        result = load_pipeline(text)
        assert result.spec is not None, result.errors
        assert [s.env for s in result.spec.steps] == [{"FOO": "bar"}, {"BAZ": "qux"}]

    def test_the_planned_unit_carries_env_and_a_reserved_name_fails_validation(self) -> None:
        loaded = load_pipeline("name: p\nsteps:\n  - id: a\n    run: echo a\n    env: {FOO: bar}\n")
        assert loaded.spec is not None
        plan = _orch.resolve_plan(loaded.spec, {})
        unit = plan.nodes[0]
        assert isinstance(unit, _orch.PlannedUnit)
        assert unit.env == {"FOO": "bar"}
        bad = load_pipeline(
            "name: p\nsteps:\n  - id: a\n    run: echo a\n    env: {DOCKET_BASE_COMMIT: x}\n"
        )
        assert bad.spec is None and "DOCKET_BASE_COMMIT" in "; ".join(bad.errors)

    def test_normalize_keeps_env_and_round_trips_through_yaml(self) -> None:
        doc = normalize_pipeline(
            {"name": "p", "steps": [{"b": {"run": "echo b", "env": {"BAZ": "qux"}}}]}
        )
        again = yaml.safe_load(yaml.safe_dump(doc))
        assert _pipeline.PipelineSpec.model_validate(again).steps[0].env == {"BAZ": "qux"}


class TestExecution:
    def test_the_command_sees_env_and_coordinates_win(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        events: list[tuple[Any, ...]] = []
        monkeypatch.setattr(_dispatch, "_when_cwd", lambda ctx, prior: str(tmp_path))
        monkeypatch.setattr(_dispatch, "_trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(
            _dispatch, "_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        node = _orch.PlannedUnit(
            step_id="check",
            role=None,
            agent=None,
            archetype=None,
            member_id=None,
            gate=None,
            retries=None,
            timeout=None,
            run='echo "foo=$FOO task=$DOCKET_TASK_ID"',
            env={"FOO": "bar-value", "DOCKET_TASK_ID": "spoofed"},
        )
        outcome = _dispatch._run_command_step(_unit_context(), node, [], 0)
        assert outcome.kind == "advance"
        assert "foo=bar-value task=task-1" in outcome.hops[0].output
        payloads = json.dumps([e[-1] for e in events])
        assert "bar-value" not in payloads
