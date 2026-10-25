"""A model turn inside the jail: the team's work and check run jailed, and nothing escapes.

The whole product runs for real as ``python -m docket`` subprocesses over a real git repo; only
the model is faked. The module skips on a machine with no Landlock (Linux) or Seatbelt (macOS).
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

from docket.sandbox.landlock import landlock_available
from docket.sandbox.seatbelt import seatbelt_available
from tests.support import e2e_oracles as oracles
from tests.support.e2e import SENTINEL_TEXT, World
from tests.support.model_server import FakeModel, Reply, Request, calls, say

BACKEND = "seatbelt" if sys.platform == "darwin" else "landlock"
pytestmark = pytest.mark.skipif(
    not (seatbelt_available() if sys.platform == "darwin" else landlock_available()),
    reason=f"{BACKEND} is not available on this host",
)

CHECKED = """name: jailed-edit
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 1
"""

UNCHECKED = """name: jailed-probe
steps:
  - plan: lead
  - implement: implementer
"""


def jailed_pod(world: World, pipeline: str) -> None:
    """Provision the pod through ``docket init``, the command that records isolation on."""
    world.docket("init", world.pod, "--blueprint", "agentic-product")
    world.pipeline.write_text(pipeline, encoding="utf-8")


def test_a_jailed_team_edits_the_repo_and_its_check_runs_in_the_jail(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    results: list[str | None] = []

    def edit_and_check(request: Request) -> Reply:
        return calls(
            [
                ("write", {"path": "app.txt", "content": "fixed\n"}, "c1"),
                ("bash", {"command": "sh checks/verify.sh"}, "c2"),
            ]
        )

    def report(request: Request) -> Reply:
        results.append(request.tool_result("c2"))
        return say("app.txt now says fixed.")

    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [edit_and_check, report],
        }
    )
    w = world(model)
    jailed_pod(w, CHECKED)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    sandbox = w.docket("setup", "sandbox", "status", "--json").json()
    assert sandbox["isolationEnabled"] is True and sandbox["backend"] == BACKEND
    isolate = [r["detail"] for r in oracles.audit_rows(w) if r["action"] == "gates.isolate"]
    assert isolate == [f"on (detected {BACKEND})"]
    assert w.task(task_id)["task"]["status"] == "done"
    assert results and f"[sandbox: {BACKEND}]" in results[0]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("session_end", "lead", "done"),
    ]
    assert "+fixed" in w.docket("task", "diff", task_id).out
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_log_verifies(w)


def test_the_jail_keeps_the_turn_out_of_home_and_off_the_network(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    results: dict[str, str | None] = {}

    def probe(request: Request) -> Reply:
        fetch = f"import urllib.request as u; print(u.urlopen('{model.base_url}/models').read())"
        return calls(
            [
                ("bash", {"command": 'cat "$HOME/.e2e-sentinel"'}, "home"),
                ("bash", {"command": f"cat {w.sentinel}"}, "real-home"),
                ("bash", {"command": f'python3 -c "{fetch}"'}, "net"),
            ]
        )

    def report(request: Request) -> Reply:
        results.update({c: request.tool_result(c) for c in ("home", "real-home", "net")})
        return say("Nothing was readable and nothing was reachable.")

    model = fake_model(script={"lead": [say("Plan: probe.")], "implementer": [probe, report]})
    w = world(model)
    jailed_pod(w, UNCHECKED)
    task_id = w.add_task("Look around")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    assert set(results) == {"home", "real-home", "net"}
    for name, text in results.items():
        assert text is not None and text.startswith("ERROR: command exited"), name
        assert f"[sandbox: {BACKEND}]" in text and SENTINEL_TEXT.strip() not in text, name
    assert "e2e-model" not in (results["net"] or "")
    assert model.models_calls == 0
    assert w.task(task_id)["task"]["status"] == "done"
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "skipped"),
        ("session_end", "lead", "done"),
    ]
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_log_verifies(w)
