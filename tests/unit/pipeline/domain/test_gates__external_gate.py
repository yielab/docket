"""The ``external`` gate kind -- parse, short form, ``on:`` key validation, reachability and the
plan label. See specs/functional/pipeline-format.spec.md ("Gates" item 5, "Outcome routing")."""

from __future__ import annotations

from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.spec import PipelineSpec, load_pipeline

SUBJECT = "docket.pipeline.domain.gates"


def _load(text: str) -> PipelineSpec:
    loaded = load_pipeline(text)
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


_SHORT = """\
name: gated
steps:
  - id: plan
    role: lead
  - build: implementer
    gate: {external: "verify.sh --strict"}
    on:
      pass: stop
      fail: {goto: build, max: 2}
      needs_human: ask
  - id: ask
    input: {from: build}
    on:
      answered: {goto: build, max: 1}
      declined: fail
"""


def test_default_exit_map() -> None:
    gate = _gates.ExternalGate(command="v.sh")
    assert gate.type == "external"
    assert gate.exit_map == {"pass": [0], "fail": [1], "needs_human": [2]}
    assert gate.timeout is None


def test_short_form_builds_the_canonical_gate() -> None:
    spec = _load(_SHORT)
    gate = spec.steps[1].gate
    assert isinstance(gate, _gates.ExternalGate)
    assert gate.command == "verify.sh --strict"


def test_short_form_in_a_canonical_step() -> None:
    spec = _load(
        "name: g\nsteps:\n  - id: build\n    role: implementer\n    gate: {external: 'v.sh'}\n"
    )
    assert isinstance(spec.steps[0].gate, _gates.ExternalGate)


def test_canonical_form_with_exit_map_and_timeout() -> None:
    spec = _load(
        """\
name: g
steps:
  - id: build
    role: implementer
    gate:
      type: external
      command: v.sh
      timeout: 30
      exitMap: {pass: [0, 3], fail: [1], needs_human: [2, 4]}
"""
    )
    gate = spec.steps[0].gate
    assert isinstance(gate, _gates.ExternalGate)
    assert gate.timeout == 30
    assert gate.exit_map["pass"] == [0, 3]


def test_plan_label_names_the_command() -> None:
    gate = _gates.ExternalGate(command="v.sh --x")
    assert _orch._gate_label(gate) == "external(v.sh --x)"
