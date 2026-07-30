"""R-7: bounded hop prompts — the stopgap safety cap ahead of Phase 17's context compiler.

``core/dispatch.py``'s ``_hop_message`` used to concatenate every prior hop's
*full* raw output into the next hop's prompt with no cap. This suite pins:

  * TestHopCarryoverBudget / TestTruncateCarryover — the two pure helpers in
    isolation (budget allocation by recency; head+tail truncation mechanics).
  * TestHopMessageCap      — ``_hop_message`` itself: small tasks unchanged,
    the task description never truncated (even when huge), truncation kicks
    in once a prior hop's output exceeds its budget, newest-hop-least-
    truncated, and the aggregate carryover never exceeds the configured cap
    even with several large prior outputs (the pathological case).
  * TestContextComposedTrace — the ``context_composed`` trace event emitted
    per hop by ``dispatch_task``, end to end through a real (lean) pod.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import runtime_driver as _rd
from docket.edges.adapters import openclaw as _oc

# ── hermetic environment (mirrors test_dispatch.py / test_cd2_verify.py) ─────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register/unregister mutate agents.list directly (no real openclaw)."""
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    (oc_dir / "openclaw.json").write_text(
        json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}})
    )
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return oc_dir


def _hop(role: str, output: str, member_id: str = "") -> _dispatch.HopResult:
    return _dispatch.HopResult(
        role=role, member_id=member_id or f"demo-{role}", ok=True, output=output, cost_usd=0.0
    )


# ── pure helper: per-hop recency budget ───────────────────────────────────────────


class TestHopCarryoverBudget:
    def test_most_recent_hop_gets_half_the_total(self) -> None:
        assert _dispatch._hop_carryover_budget(0, 32_000) == 16_000

    def test_each_older_rank_halves_again(self) -> None:
        assert _dispatch._hop_carryover_budget(1, 32_000) == 8_000
        assert _dispatch._hop_carryover_budget(2, 32_000) == 4_000
        assert _dispatch._hop_carryover_budget(3, 32_000) == 2_000

    def test_sum_across_any_number_of_ranks_never_reaches_total(self) -> None:
        total = 32_768
        for n in (1, 2, 3, 10, 50):
            budgets = [_dispatch._hop_carryover_budget(r, total) for r in range(n)]
            assert sum(budgets) < total


# ── pure helper: head+tail truncation ─────────────────────────────────────────────


class TestTruncateCarryover:
    def test_output_within_budget_is_returned_unchanged(self) -> None:
        text, truncated, sent = _dispatch._truncate_carryover("short output", 1000)
        assert text == "short output"
        assert truncated is False
        assert sent == len(b"short output")

    def test_output_over_budget_is_truncated_with_marker(self) -> None:
        big = "X" * 1000
        text, truncated, sent = _dispatch._truncate_carryover(big, 100)
        assert truncated is True
        assert "[... truncated" in text
        assert "bytes ...]" in text
        assert len(text.encode("utf-8")) <= 100
        assert sent == len(text.encode("utf-8"))

    def test_marker_records_exact_omitted_byte_count(self) -> None:
        big = "Y" * 500
        text, _truncated, _sent = _dispatch._truncate_carryover(big, 100)
        # Head + tail kept plus the marker == original length.
        marker_n = int(text.split("truncated ")[1].split(" bytes")[0])
        kept = len(text.encode("utf-8")) - len(f"\n[... truncated {marker_n} bytes ...]\n")
        assert marker_n + kept == 500

    def test_zero_budget_still_bounded_and_deterministic(self) -> None:
        text, truncated, sent = _dispatch._truncate_carryover("Z" * 50, 0)
        assert truncated is True
        assert sent <= 0 or "[... truncated" in text


# ── _hop_message: the composed prompt itself ──────────────────────────────────────


class TestHopMessageCap:
    def test_small_task_byte_identical_to_pre_cap_behaviour(self) -> None:
        """Regression pin: below-budget content composes exactly as before R-7."""
        task = {"description": "Fix the bug"}
        prior = [_hop("lead", "Plan: do X.")]
        message, comp = _dispatch._hop_message(task, "implementer", prior)

        expected = "\n".join(
            [
                "Task: Fix the bug",
                "",
                "--- lead output ---\nPlan: do X.\n",
                "You are the Implementer. Implement the change in the workspace.",
            ]
        )
        assert message == expected
        assert comp.truncated is False
        assert comp.sections == [
            {
                "role": "lead",
                "original_bytes": len(b"Plan: do X."),
                "sent_bytes": len(b"Plan: do X."),
                "truncated": False,
            }
        ]
        assert comp.description_bytes == len(b"Fix the bug")
        assert comp.total_bytes == len(message.encode("utf-8"))

    def test_lead_hop_message_unaffected_by_cap(self) -> None:
        """The lead hop has no prior output to cap — its message is untouched."""
        task = {"description": "Ship it"}
        message, comp = _dispatch._hop_message(task, "lead", [])
        assert message == (
            "You are the pod Lead. Decompose this task into a concrete plan for "
            "the Implementer (you never edit code yourself):\n\nShip it"
        )
        assert comp.sections == []
        assert comp.truncated is False

    def test_task_description_never_truncated_even_when_huge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "HOP_CARRYOVER_BYTES", 200)
        huge_desc = "D" * 500_000
        task = {"description": huge_desc}

        lead_message, _lead_comp = _dispatch._hop_message(task, "lead", [])
        assert huge_desc in lead_message

        message, comp = _dispatch._hop_message(task, "implementer", [_hop("lead", "small")])
        assert f"Task: {huge_desc}" in message
        assert comp.description_bytes == len(huge_desc.encode("utf-8"))

    def test_prior_output_over_budget_is_truncated_with_marker_in_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "HOP_CARRYOVER_BYTES", 100)
        task = {"description": "task"}
        prior = [_hop("lead", "L" * 5000)]
        message, comp = _dispatch._hop_message(task, "implementer", prior)
        assert "[... truncated" in message
        assert comp.truncated is True
        assert comp.sections[0]["truncated"] is True
        assert comp.sections[0]["original_bytes"] == 5000
        assert comp.sections[0]["sent_bytes"] < 5000

    def test_newest_hop_is_truncated_least(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "HOP_CARRYOVER_BYTES", 32_768)
        task = {"description": "task"}
        prior = [
            _hop("lead", "A" * 20_000),
            _hop("implementer", "B" * 20_000),
            _hop("reviewer", "C" * 20_000),
        ]
        _message, comp = _dispatch._hop_message(task, "tester", prior)
        assert [s["role"] for s in comp.sections] == ["lead", "implementer", "reviewer"]
        sent = {s["role"]: s["sent_bytes"] for s in comp.sections}
        # Chronological order is oldest -> newest; the most recent (reviewer)
        # gets the biggest share, each older hop strictly less.
        assert sent["lead"] < sent["implementer"] < sent["reviewer"]
        assert all(s["truncated"] for s in comp.sections)

    def test_pathological_many_large_prior_outputs_never_exceed_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Several large prior outputs (well beyond a normal 4-role pipeline) —
        the aggregate carryover must still respect the configured cap."""
        cap = 32_768
        monkeypatch.setattr(_cfg, "HOP_CARRYOVER_BYTES", cap)
        task = {"description": "task"}
        prior = [_hop(f"hop-{i}", "Q" * 100_000) for i in range(8)]
        message, comp = _dispatch._hop_message(task, "tester", prior)

        total_carryover = sum(s["sent_bytes"] for s in comp.sections)
        assert total_carryover < cap
        assert all(s["truncated"] for s in comp.sections)
        # The description plus a small fixed per-hop wrapper overhead is all
        # that's added on top of the bounded carryover.
        assert len(message.encode("utf-8")) < cap + len(task["description"]) + 2000

    def test_small_multi_hop_task_unchanged_no_truncation(self) -> None:
        """No regression for the common (small-output) multi-hop case either."""
        task = {"description": "Small task"}
        prior = [_hop("lead", "short plan"), _hop("implementer", "small diff")]
        message, comp = _dispatch._hop_message(task, "reviewer", prior)
        expected = "\n".join(
            [
                "Task: Small task",
                "",
                "--- lead output ---\nshort plan\n",
                "--- implementer output ---\nsmall diff\n",
                "You are the Reviewer. Review the diff (read-only). Your reply's first "
                "non-blank line must be exactly APPROVE or REQUEST-CHANGES "
                "(case-insensitive), followed by your reasons.",
            ]
        )
        assert message == expected
        assert comp.truncated is False
        assert all(not s["truncated"] for s in comp.sections)


# ── integration: context_composed trace event ─────────────────────────────────────


class _BigOutputRunner:
    """Always returns a large fixed output, to force carryover truncation."""

    def __init__(self, size: int = 50_000) -> None:
        self.size = size

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        return _rd.TurnResult(True, "Z" * self.size, 0.0, {"output": "x"})


class TestContextComposedTrace:
    def test_context_composed_emitted_per_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Trace the context")
        _dispatch.dispatch_pod("demo", runner=_BigOutputRunner())

        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        assert len(trace_files) == 1
        events: list[dict[str, Any]] = [
            json.loads(line) for line in trace_files[0].read_text().splitlines()
        ]
        composed = [e for e in events if e["event_type"] == "context_composed"]
        assert len(composed) == 2  # one per hop: lead, implementer

        lead_payload = composed[0]["payload"]
        assert lead_payload["hop"] == "lead"
        assert lead_payload["sections"] == []
        assert lead_payload["truncated"] is False

        impl_payload = composed[1]["payload"]
        assert impl_payload["hop"] == "implementer"
        assert len(impl_payload["sections"]) == 1
        section = impl_payload["sections"][0]
        assert section["role"] == "lead"
        assert section["original_bytes"] == 50_000
        assert section["truncated"] is True
        assert section["sent_bytes"] < 50_000
        assert impl_payload["truncated"] is True

    def test_context_composed_not_truncated_for_small_outputs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Small trace")

        class _SmallRunner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                return _rd.TurnResult(True, "tiny output", 0.0, {})

        _dispatch.dispatch_pod("demo", runner=_SmallRunner())
        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
        composed = [e for e in events if e["event_type"] == "context_composed"]
        assert len(composed) == 2
        assert all(e["payload"]["truncated"] is False for e in composed)
