"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

import pytest
from tests.support.pods import unit as _unit

from docket.hops.application import executor as _executor_c
from docket.hops.gates import pre_hop as _pre_hop
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

SUBJECT = "docket.hops.gates.pre_hop"


def test_every_command_a_task_runs_as_a_check_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_pod, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_pre_hop, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_executor_c, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_fleet, "meta_get", lambda *a, **k: "make verify")
    steps = (
        _unit("build", gate=_gates.MechanicalGate(command="bash scripts/check.sh")),
        _orch.PlannedGroup(
            step_id="par",
            children=(
                _unit("a", gate=_gates.ExternalGate(command="./verify.sh")),
                _unit("b", run="node lint.js"),
                _unit("c", gate=_gates.VerdictGate(pattern="x", passValues=["x"])),
            ),
        ),
    )
    task = {"gate": {"command": "python gate.py"}}

    assert _pre_hop._checked_commands("demo", task, steps) == [
        "make verify",
        "bash scripts/check.sh",
        "./verify.sh",
        "node lint.js",
        "python gate.py",
    ]
