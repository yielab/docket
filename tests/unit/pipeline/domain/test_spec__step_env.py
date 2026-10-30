"""A ``run`` command step's ``env:`` -- shape validation, short form, planning, and the
environment the command actually sees. See specs/functional/pipeline-format.spec.md
("Conditional steps and command steps") and pod-dispatch.spec.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.support.pods import unit_context as _unit_context
from tests.support.roles import ROLE_NAMES

from docket.hops.application import compose as _compose_c
from docket.hops.application import executor as _executor_c
from docket.hops.application import runner as _runner
from docket.hops.application import steps as _steps
from docket.hops.gates import post_hop as _post_hop_c
from docket.hops.gates import pre_hop as _pre_hop_c
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain.short_form import normalize_pipeline
from docket.pipeline.domain.spec import load_pipeline
from docket.tasks.application import actions as _actions_c
from docket.tasks.application import queue as _queue_c
from docket.tasks.application import record as _record
from docket.teams import roles as _archetypes
from docket.teams import settings as _settings

SUBJECT = "docket.pipeline.domain.spec"


class TestLoading:
    def test_run_step_forms_carry_env(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - a:\n      run: echo a\n      env: {FOO: bar}\n"
            "  - b: {run: echo b, env: {BAZ: qux}}\n"
        )
        result = load_pipeline(text, roles=ROLE_NAMES)
        assert result.spec is not None, result.errors
        assert [s.env for s in result.spec.steps] == [{"FOO": "bar"}, {"BAZ": "qux"}]

    def test_the_planned_unit_carries_env_and_a_reserved_name_fails_validation(self) -> None:
        loaded = load_pipeline(
            "name: p\nsteps:\n  - a:\n      run: echo a\n      env: {FOO: bar}\n", roles=ROLE_NAMES
        )
        assert loaded.spec is not None
        plan = _orch.resolve_plan(loaded.spec, {}, registry=_archetypes.load_registry())
        unit = plan.nodes[0]
        assert isinstance(unit, _orch.PlannedUnit)
        assert unit.env == {"FOO": "bar"}
        bad = load_pipeline(
            "name: p\nsteps:\n  - a:\n      run: echo a\n      env: {DOCKET_BASE_COMMIT: x}\n",
            roles=ROLE_NAMES,
        )
        assert bad.spec is None and "DOCKET_BASE_COMMIT" in "; ".join(bad.errors)

    def test_normalize_keeps_env_and_round_trips_through_yaml(self) -> None:
        doc = normalize_pipeline(
            {"name": "p", "steps": [{"b": {"run": "echo b", "env": {"BAZ": "qux"}}}]}, ROLE_NAMES
        )
        again = yaml.safe_load(yaml.safe_dump(doc))
        assert _pipeline.PipelineSpec.model_validate(again).steps[0].env == {"BAZ": "qux"}


class TestExecution:
    def test_the_command_sees_env_and_coordinates_win(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        events: list[tuple[Any, ...]] = []
        monkeypatch.setattr(_runner, "when_cwd", lambda ctx, prior: str(tmp_path))
        monkeypatch.setattr(_steps, "when_cwd", lambda ctx, prior: str(tmp_path))
        monkeypatch.setattr(_executor_c, "when_cwd", lambda ctx, prior: str(tmp_path))
        monkeypatch.setattr(_record, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_compose_c, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_runner, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_pre_hop_c, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_post_hop_c, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_steps, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(_executor_c, "trace_locked", lambda *a, **k: events.append(a))
        monkeypatch.setattr(
            _settings, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        monkeypatch.setattr(
            _actions_c, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        monkeypatch.setattr(
            _queue_c, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        monkeypatch.setattr(
            _compose_c, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        monkeypatch.setattr(
            _pre_hop_c, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
        )
        monkeypatch.setattr(
            _post_hop_c,
            "load_pod_settings",
            lambda project: type("S", (), {"allow_commands": []})(),
        )
        monkeypatch.setattr(
            _steps, "load_pod_settings", lambda project: type("S", (), {"allow_commands": []})()
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
        outcome = _steps._run_command_step(_unit_context(), node, [], 0)
        assert outcome.kind == "advance"
        assert "foo=bar-value task=task-1" in outcome.hops[0].output
        payloads = json.dumps([e[-1] for e in events])
        assert "bar-value" not in payloads
