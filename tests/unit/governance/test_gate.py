"""`govern`: how one gated call ends. The verdict is stubbed, so each route is one short case."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _pregrant
from docket.governance import audit as _audit
from docket.governance import gate as _gate
from docket.kernel.gate import GateCall, GateDecision
from docket.operator.contract import canonical_args_digest

SUBJECT = "docket.governance.gate"


@dataclass(frozen=True)
class _Tool:
    name: str = "write"
    kind: str = "write"


@dataclass(frozen=True)
class _Grant:
    token: str
    tool: str
    args_digest: str


@dataclass
class _Ctx:
    agent_id: str = "a1"
    role: str = "implementer"
    project: str = "demo"
    roots: tuple[Path, ...] = ()
    sandbox: str = "off"
    allow_commands: tuple[str, ...] = ()
    approval_mode: str = "wait"
    pregrants: tuple[_Grant, ...] = field(default_factory=tuple)
    approval_expires_at: str | None = None
    approval_timeout: int | None = None
    cancellation_check: Any = None
    rationale: str = ""
    task_id: str = ""


ARGS = {"path": "a.txt", "content": "x"}
CALL = GateCall(_Tool(), "call-1", ARGS)


def _verdict(
    monkeypatch: pytest.MonkeyPatch, decision: str, reason: str = "because", policy_id: str = "p1"
) -> None:
    monkeypatch.setattr(
        _gate,
        "evaluate_tool_call",
        lambda _t, _a, _c: _gate.ToolVerdict(decision, reason, policy_id=policy_id),  # type: ignore[arg-type]
    )


def test_an_allowed_call_carries_no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "allow", reason="")

    assert _gate.govern(CALL, _Ctx()) == GateDecision("allow")


def test_a_denied_call_is_audited_and_names_its_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "deny", reason="no writes")

    decision = _gate.govern(CALL, _Ctx())

    assert decision == GateDecision(
        "deny", "no writes", policy_id="p1", denial_kind="gate_denied", error="no writes"
    )
    assert any(e.get("action") == "tool.deny" for e in _audit.read_audit())


def test_an_ask_in_refuse_mode_asks_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "ask", reason="needs a human")

    decision = _gate.govern(CALL, _Ctx(approval_mode="refuse"))

    assert (decision.decision, decision.denial_kind) == ("deny", "approval_unavailable")
    assert decision.reason == decision.error == "needs a human"
    assert not _approval.list_pending()


def test_an_ask_in_park_mode_records_the_call_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "ask")

    decision = _gate.govern(CALL, _Ctx(approval_mode="park", task_id="t-1"))

    assert (decision.decision, decision.denial_kind) == ("deny", "approval_parked")
    assert decision.approval_token and decision.approval_token in decision.reason
    record = _approval.approval_get(decision.approval_token)
    assert record["context"]["taskId"] == "t-1"
    assert record["context"]["argsDigest"] == canonical_args_digest("write", ARGS)


def test_a_matching_pregrant_lets_the_call_run_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "ask")
    digest = canonical_args_digest("write", ARGS)
    token = _pregrant.create_pregrant("demo", "implementer", "write", digest, channel="cli")
    ctx = _Ctx(approval_mode="refuse", pregrants=(_Grant(token, "write", digest),))

    first = _gate.govern(CALL, ctx)
    second = _gate.govern(CALL, ctx)

    assert (first.decision, first.approval_token) == ("allow", token)
    assert first.reason == f"pre-granted (token={token})"
    assert second.decision == "deny"  # consumed: the same grant does not run a second call


def test_a_pregrant_for_other_arguments_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _verdict(monkeypatch, "ask")
    other = canonical_args_digest("write", {"path": "b.txt", "content": "x"})
    ctx = _Ctx(approval_mode="refuse", pregrants=(_Grant("tok", "write", other),))

    assert _gate.govern(CALL, ctx).decision == "deny"
