"""A backward ``on:`` route carries the routed gate's output into the target's next hop.

``until: verify`` re-runs the Implementer when its mechanical gate fails; the retry must see
why (the hop's redacted ``verify.outputTail``) under a ``--- GATE FAILED: <step id> ---``
section (pod-dispatch.spec.md "Bounded hop prompts" requirement 9). A forward route, an
unrouted gate and a verdict rework keep today's messages byte for byte.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off
from tests.fakes import FakeDriver

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pipeline as _pipeline
from docket.kernel.home import Home, use_home

SUBJECT = "docket.core"

MARKER = "zz-unique-gate-marker-4417"

_UNTIL_YAML = """\
name: retry
steps:
  - id: plan
    role: lead
  - build: implementer
    verify: true
    until: verify
    max: 2
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed(tmp_path: Path, verify_cmd: str) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        _fleet.meta_set("demo-implementer", "verifyCmd", verify_cmd)
        yield


def _spec(text: str) -> _pipeline.PipelineSpec:
    loaded = _pipeline.load_pipeline(text)
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


def _implementer_messages(driver: FakeDriver) -> list[str]:
    return [c[2] for c in driver.calls if c[0].endswith("-implementer")]


@contextmanager
def _run(tmp_path: Path, verify_cmd: str, yaml: str) -> Iterator[tuple[Any, FakeDriver]]:
    with _seed(tmp_path, verify_cmd):
        _dispatch.enqueue_task("demo", "Ship it", channel="cli")
        driver = FakeDriver()
        results = _dispatch.dispatch_pod("demo", runner=driver, spec=_spec(yaml))
        yield results[0], driver


def test_backward_route_carries_the_failed_gate_output_into_the_retry(tmp_path: Path) -> None:
    flag = tmp_path / "flag"
    cmd = f"test -f {flag} || {{ touch {flag}; echo {MARKER}; exit 1; }}"
    with _run(tmp_path, cmd, _UNTIL_YAML) as (res, driver):
        assert res.status == "done", res.reason
        messages = _implementer_messages(driver)
        assert len(messages) == 2
        assert MARKER not in messages[0]
        assert "--- GATE FAILED: build ---" in messages[1]
        assert MARKER in messages[1].split("--- GATE FAILED: build ---", 1)[1]


def test_gate_failed_section_is_recorded_in_the_composition() -> None:
    hop = _dispatch.HopResult(
        role="implementer",
        member_id="demo-implementer",
        ok=True,
        output="built",
        cost_usd=0.0,
        step_id="build",
        next_step="build",
        verify={"cmd": "x", "exitCode": 1, "durationS": 0.1, "outputTail": MARKER},
    )
    message, comp = _dispatch._hop_message(
        {"description": "d"}, "implementer", [hop], rework_hop=hop
    )
    assert f"--- GATE FAILED: build ---\n{MARKER}" in message
    assert [s["role"] for s in comp.sections][:1] == ["gate_failed"]
    # Unlike a verdict rework hop, the routed hop's own output stays in the generic carryover.
    assert "--- implementer output ---\nbuilt" in message
    assert message.count("--- GATE FAILED") == 1


def test_no_gate_failed_section_without_a_failure(tmp_path: Path) -> None:
    with _run(tmp_path, "echo fine", _UNTIL_YAML) as (res, driver):
        assert res.status == "done"
        messages = _implementer_messages(driver)
        assert len(messages) == 1
        assert "GATE FAILED" not in messages[0]


def test_hop_message_without_gate_failed_hop_is_unchanged() -> None:
    prior = [
        _dispatch.HopResult(
            role="lead", member_id="demo-lead", ok=True, output="Plan: X.", cost_usd=0.0
        )
    ]
    message, _ = _dispatch._hop_message({"description": "d"}, "implementer", prior)
    assert message == (
        "Task: d\n\n--- lead output ---\nPlan: X.\n\n"
        "You are the Implementer. Implement the change in the workspace."
    )


def test_resume_rebuilds_the_carryover_from_the_last_routed_gated_hop(tmp_path: Path) -> None:
    with _seed(tmp_path, "true"):
        steps, _ids, _instr = _dispatch._resolve_pipeline_steps("demo", _spec(_UNTIL_YAML))
        lead = _dispatch.HopResult(
            role="lead", member_id="demo-lead", ok=True, output="p", cost_usd=0.0, step_id="plan"
        )
        gated = _dispatch.HopResult(
            role="implementer",
            member_id="demo-implementer",
            ok=True,
            output="built",
            cost_usd=0.0,
            step_id="build",
            next_step="build",
            verify={"cmd": "x", "exitCode": 1, "durationS": 0.1, "outputTail": MARKER},
        )
        _prior, index, _rework, routes, pending = _dispatch._resolve_resume_state(
            steps, [lead, gated]
        )
        assert index == 1
        assert routes == {("build", "fail"): 1}
        assert pending == {1: gated}


def test_a_backward_route_out_of_a_passing_gate_carries_no_gate_failure() -> None:
    passed = {"cmd": "x", "exitCode": 0, "durationS": 0.1, "outputTail": MARKER}
    hop = _dispatch.HopResult(
        role="implementer",
        member_id="demo-implementer",
        ok=True,
        output="built",
        cost_usd=0.0,
        step_id="build",
        next_step="plan",
        verify=passed,
    )
    message, _ = _dispatch._hop_message({"description": "d"}, "implementer", [hop], rework_hop=hop)
    assert "GATE FAILED" not in message
