"""``hops.application.interruptions`` -- the interruption forecast and pre-grants from intake
(ADR 0016 SS10).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import bind_pipeline_2 as _bind_pipeline
from tests.support.pods import seed_pod as _seed_pod

from docket.agent.ports import ToolCall
from docket.agent.tools import registry as core_tools
from docket.hops.application import builtin_tools
from docket.hops.application import interruptions as _interruptions
from docket.kernel import operator_contract as _oc
from docket.kernel.home import current_home, use_home
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.interruptions"

_GATED_PIPELINE_YAML = """\
name: gated
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
    gate:
      type: approval
      message: "Ready to deploy?"
"""


class TestForecast:
    def test_a_clean_pod_has_nothing_to_ask(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            items = _interruptions.forecast("demo")

            askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
            assert askers == []
            kinds = {i.kind for i in items}
            assert "high_risk_class" in kinds
            assert "mode" in kinds
            assert "channel" in kinds  # console is enabled by default

    def test_a_pod_scoped_require_approval_policy_is_forecast(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            policies_dir = current_home().pod_config_dir("demo") / "policies"
            policies_dir.mkdir(parents=True)
            (policies_dir / "prod-approval.yaml").write_text(
                "kind: policy\n"
                "name: prod-approval-high-risk\n"
                "appliesTo: [implementer]\n"
                "when:\n"
                "  tool: bash\n"
                "  matches: 'terraform\\s+apply'\n"
                "then: ask\n"
            )

            items = _interruptions.forecast("demo")

            policies = [i for i in items if i.kind == "policy"]
            assert len(policies) == 1
            assert policies[0].detail == "prod-approval-high-risk"
            assert "terraform" not in policies[0].description
            assert "\\" not in policies[0].description
            assert policies[0].description == (
                "policy 'prod-approval-high-risk' asks on: tool bash, commands matching its pattern"
            )

    def test_a_structured_policy_is_described_by_its_predicate_kinds(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            policies_dir = current_home().pod_config_dir("demo") / "policies"
            policies_dir.mkdir(parents=True)
            (policies_dir / "src-edits.yaml").write_text(
                "kind: policy\n"
                "name: src-edits\n"
                "appliesTo: [implementer]\n"
                "when:\n"
                "  tool: write\n"
                "  path: 'src/**'\n"
                "then: ask\n"
            )

            policies = [i for i in _interruptions.forecast("demo") if i.kind == "policy"]

            assert (
                policies[0].description == "policy 'src-edits' asks on: tool write on path src/**"
            )

    def test_pipeline_approval_and_input_steps_are_forecast(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_pipeline("demo", _GATED_PIPELINE_YAML)

            items = _interruptions.forecast("demo")

            gates = {i.detail for i in items if i.kind == "pipeline_gate"}
            assert gates == {"ask", "implementer"}

    def test_mode_resolves_through_caller_default_when_unset(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            waiting = next(
                i
                for i in _interruptions.forecast("demo", caller_default="wait")
                if i.kind == "mode"
            )
            parking = next(
                i
                for i in _interruptions.forecast("demo", caller_default="park")
                if i.kind == "mode"
            )

            assert waiting.detail == "wait"
            assert parking.detail == "park"

    def test_an_explicit_pod_approval_mode_wins_over_the_caller_default(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _fleet.meta_set("demo-lead", "approvalMode", "refuse")

            mode_item = next(
                i
                for i in _interruptions.forecast("demo", caller_default="wait")
                if i.kind == "mode"
            )

            assert mode_item.detail == "refuse"


class TestRecordPregrant:
    def test_refuses_a_task_in_another_pod(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), pytest.raises(_interruptions.InterruptionsError):
            _interruptions.record_pregrant(
                "demo", "no-such-task", "git push origin main", channel="cli"
            )

    def test_records_the_same_shape_a_live_park_grant_appends(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]

            token = _interruptions.record_pregrant(
                "demo", task["id"], "git push origin main", channel="cli", actor="tester"
            )

            stored = _queue.read_tasks("demo")[0]
            expected_digest = _oc.canonical_args_digest("bash", {"command": "git push origin main"})
            assert stored["pregrants"] == [
                {"token": token, "tool": "bash", "argsDigest": expected_digest}
            ]

    def test_collapses_whitespace_before_digesting(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]

            _interruptions.record_pregrant(
                "demo", task["id"], "git   push  origin\tmain", channel="cli"
            )

            stored = _queue.read_tasks("demo")[0]
            expected_digest = _oc.canonical_args_digest("bash", {"command": "git push origin main"})
            assert stored["pregrants"][0]["argsDigest"] == expected_digest

    def test_custom_tool_changes_the_digest(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]

            _interruptions.record_pregrant("demo", task["id"], "hello", tool="write", channel="cli")

            stored = _queue.read_tasks("demo")[0]
            assert stored["pregrants"][0]["tool"] == "write"
            assert stored["pregrants"][0]["argsDigest"] == _oc.canonical_args_digest(
                "write", {"command": "hello"}
            )


class TestPregrantAtTheChokepoint:
    """The acceptance criterion: a pre-granted call passes the real chokepoint once; a
    rephrased one still asks (ADR 0016 SS10's exact-after-whitespace-collapse limit)."""

    def _pregrants_for(self, task: dict[str, Any]) -> tuple[core_tools.Pregrant, ...]:
        return tuple(
            core_tools.Pregrant(token=g["token"], tool=g["tool"], args_digest=g["argsDigest"])
            for g in task.get("pregrants", [])
        )

    def test_the_named_command_passes_once_a_rephrased_one_still_asks(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)),
        ):
            task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]
            _interruptions.record_pregrant(
                "demo", task["id"], "git push origin main", channel="cli"
            )
            stored = _queue.read_tasks("demo")[0]
            ctx = core_tools.ToolContext(
                agent_id="demo-implementer",
                roots=(tmp_path,),
                pregrants=self._pregrants_for(stored),
            )

            granted = core_tools.dispatch_tool(
                ToolCall(
                    id="c1", name="bash", arguments=json.dumps({"command": "git push origin main"})
                ),
                ctx,
                builtin_tools.builtin_registry(),
            )
            assert granted.decision == "allow"
            assert granted.executed

            forced = core_tools.dispatch_tool(
                ToolCall(
                    id="c2",
                    name="bash",
                    arguments=json.dumps({"command": "git push origin main --force"}),
                ),
                ctx,
                builtin_tools.builtin_registry(),
            )
            assert forced.decision == "deny"

            # Single-use: an identical second call no longer matches either.
            again = core_tools.dispatch_tool(
                ToolCall(
                    id="c3", name="bash", arguments=json.dumps({"command": "git push origin main"})
                ),
                ctx,
                builtin_tools.builtin_registry(),
            )
            assert again.decision == "deny"
