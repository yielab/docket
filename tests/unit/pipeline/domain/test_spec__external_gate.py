"""The ``external`` gate kind -- parse, short form, ``on:`` key validation, reachability and the
plan label. See specs/functional/pipeline-format.spec.md ("Gates" item 5, "Outcome routing")."""

from __future__ import annotations

from typing import Any

import pytest
from tests.support.pods import load as _load

from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.pipeline.domain.spec import load_pipeline

SUBJECT = "docket.pipeline.domain.spec"


def _errors(text: str) -> str:
    loaded = load_pipeline(text)
    assert not loaded.ok
    return "\n".join(loaded.errors)


@pytest.mark.parametrize(
    ("gate", "needle"),
    [
        ("{type: external, command: '  '}", "command"),
        ("{type: external}", "command"),
        ("{external: 'v.sh', timeout: 3}", "external"),
        (
            "{type: external, command: v.sh, exitMap: {pass: [0], fail: [0], needs_human: [2]}}",
            "exitMap",
        ),
        (
            "{type: external, command: v.sh, exitMap: {pass: [], fail: [1], needs_human: [2]}}",
            "exitMap",
        ),
        ("{type: external, command: v.sh, exitMap: {pass: [0], fail: [1], bogus: [2]}}", "exitMap"),
        ("{type: external, command: v.sh, timeout: 0}", "timeout"),
    ],
)
def test_invalid_external_gate_is_a_validation_error(gate: str, needle: str) -> None:
    text = f"name: g\nsteps:\n  - id: build\n    role: implementer\n    gate: {gate}\n"
    assert needle in _errors(text)


def test_on_keys_are_checked_for_an_external_gated_step() -> None:
    text = """\
name: g
steps:
  - id: build
    role: implementer
    gate: {external: v.sh}
    on:
      APPROVE: fail
"""
    message = _errors(text)
    assert "build" in message
    assert "needs_human" in message


def test_on_keys_are_case_insensitive_for_an_external_gate() -> None:
    spec = _load(
        "name: g\nsteps:\n  - id: build\n    role: implementer\n    gate: {external: v.sh}\n"
        "    on:\n      FAIL: stop\n      Needs_Human: stop\n      ERROR: stop\n"
    )
    assert spec.steps[0].on is not None


def test_default_edge_is_reachable_until_pass_and_fail_are_both_routed() -> None:
    gated: dict[str, Any] = {"id": "build", "role": "implementer"}

    def step(on: dict[str, Any] | None) -> _step.Step:
        return _step.Step.model_validate(
            {**gated, "gate": {"type": "external", "command": "v"}, "on": on}
        )

    assert _pipeline._default_edge_reachable(step(None))
    assert _pipeline._default_edge_reachable(step({"fail": "stop"}))
    assert not _pipeline._default_edge_reachable(step({"pass": "stop", "fail": "stop"}))


def test_a_step_after_a_fully_routed_external_gate_is_unreachable() -> None:
    text = """\
name: g
steps:
  - id: build
    role: implementer
    gate: {external: v.sh}
    on: {pass: stop, fail: stop}
  - id: after
    role: reviewer
"""
    assert "not reachable" in _errors(text)


def test_a_short_form_input_step_keeps_an_unquoted_on_map() -> None:
    # YAML reads a bare `on:` key as the boolean True; the input short form must still route.
    spec = _load(
        "name: p\nsteps:\n  - id: build\n    role: implementer\n"
        "    gate: {external: verify}\n    on: {pass: stop, needs_human: ask}\n"
        "  - ask:\n      input: {from: build}\n      on: {answered: {goto: build, max: 1}}\n"
    )
    ask = next(s for s in spec.steps if s.id == "ask")
    assert ask.on == {"answered": {"goto": "build", "max": 1}}


def test_routing_a_label_to_the_next_input_step_requires_routing_pass() -> None:
    # Without `pass:`, a passing gate takes the default edge into the input step and parks again.
    body = (
        "name: p\nsteps:\n  - id: build\n    role: implementer\n"
        "    gate: {external: verify}\n    on: {needs_human: ask}\n"
        "  - id: ask\n    input: {from: build}\n    on: {answered: {goto: build, max: 1}}\n"
    )
    errors = _errors(body)
    assert "build" in errors and "pass" in errors and "ask" in errors


def test_routing_pass_explicitly_satisfies_the_input_step_rule() -> None:
    _load(
        "name: p\nsteps:\n  - id: build\n    role: implementer\n"
        "    gate: {external: verify}\n    on: {pass: stop, needs_human: ask}\n"
        "  - id: ask\n    input: {from: build}\n    on: {answered: {goto: build, max: 1}}\n"
    )


@pytest.mark.parametrize(
    ("sugar", "named"),
    [
        ("    verify: true\n    gate: {external: ./ci.sh}\n", "verify, gate"),
        ("    verdict: [APPROVE]\n    approval: ship it?\n", "verdict, approval"),
        ("    verify: make check\n    verdict: [PASS]\n", "verdict, verify"),
    ],
    ids=["verify+external", "verdict+approval", "verify+verdict"],
)
def test_two_gates_on_one_short_step_are_refused_naming_both(sugar: str, named: str) -> None:
    errors = _errors("name: p\nsteps:\n  - build: implementer\n" + sugar)
    assert f"step 'build': one gate per step (got {named})" in errors
