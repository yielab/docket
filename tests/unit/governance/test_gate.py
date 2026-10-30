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
from docket.governance.secrets import redact as _redact
from docket.kernel.gate import GateCall, GateDecision
from docket.kernel.operator_contract import canonical_args_digest

SUBJECT = "docket.governance.gate"


@dataclass(frozen=True)
class _Tool:
    name: str = "write"
    kind: str = "write"
    deletes: bool = False


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
    assert decision.approval_token and decision.approval_token not in decision.reason
    assert decision.reason.startswith("because; a person must approve this call")
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


SEND_TOOL = _Tool(name="mcp__outbox__send", kind="send")
TOKEN_TEXT = "sk-" + "a1b2c3d4" * 4
SEND_ARGS = {
    "to": "ana@example.com",
    "phone": "+57 300 1234567",
    "headers": {"Authorization": f"Bearer {TOKEN_TEXT}"},
    "body": "hello " * 500,
}
SEND_CALL = GateCall(SEND_TOOL, "call-send", SEND_ARGS)


def _audit_actions() -> list[str]:
    return [str(e.get("action")) for e in _audit.read_audit()]


class TestASendCall:
    def test_any_send_tool_asks_without_a_policy(self) -> None:
        verdict = _gate.evaluate_tool_call(_Tool("mcp__other__post", "send"), {}, _Ctx())

        assert verdict.decision == "ask"
        assert "outside the machine" in verdict.reason

    def test_a_non_send_tool_without_a_policy_still_allows(self) -> None:
        assert _gate.evaluate_tool_call(_Tool("write", "write"), {}, _Ctx()).decision == "allow"

    def test_an_ask_keeps_the_whole_call_with_only_credentials_removed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _verdict(monkeypatch, "ask")

        decision = _gate.govern(SEND_CALL, _Ctx(approval_mode="park", task_id="t-1"))

        record = _approval.approval_get(decision.approval_token)
        call = record["call"]
        assert len(call) > 3000
        assert "ana@example.com" in call and "+57 300 1234567" in call
        assert TOKEN_TEXT not in call
        assert call == _redact(_gate.render_tool_call(SEND_TOOL.name, SEND_ARGS), personal=False)
        assert len(record["action"]) <= 1000 and "ana@example.com" not in record["action"]

    def test_an_ask_on_bash_keeps_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _verdict(monkeypatch, "ask")

        decision = _gate.govern(
            GateCall(_Tool("bash", "exec"), "c", {"command": "ls"}),
            _Ctx(approval_mode="park"),
        )

        assert "call" not in _approval.approval_get(decision.approval_token)

    def test_an_allowed_send_writes_tool_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _verdict(monkeypatch, "allow", reason="", policy_id="")

        assert _gate.govern(SEND_CALL, _Ctx()).decision == "allow"

        entries = [e for e in _audit.read_audit() if e.get("action") == "tool.send"]
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "tool=mcp__outbox__send" in detail and "decision=allow" in detail
        assert "ana@example.com" not in detail and TOKEN_TEXT not in detail

    def test_a_send_row_carries_the_audit_detail_the_call_brings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _verdict(monkeypatch, "allow", reason="", policy_id="")
        call = GateCall(SEND_TOOL, "c", {}, audit_detail="method=POST host='api.example.com'")

        _gate.govern(call, _Ctx())

        (entry,) = [e for e in _audit.read_audit() if e["action"] == "tool.send"]
        assert "method=POST host='api.example.com'" in entry["detail"]

    @pytest.mark.parametrize("kind", ["service_not_allowed", "service_bad_request"])
    def test_a_service_refusal_names_the_kind_method_and_host_only(self, kind: str) -> None:
        call = GateCall(
            SEND_TOOL,
            "c",
            {"id": 1, "q": "secret-query"},
            audit_detail="method=GET host='api.example.com'",
        )

        _gate.audit_refusal(call, _Ctx(), kind)

        (entry,) = [e for e in _audit.read_audit() if e["action"] == "tool.refused"]
        assert f"kind={kind} method=GET host='api.example.com'" in entry["detail"]
        assert "secret-query" not in entry["detail"]

    def test_a_denied_send_writes_tool_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _verdict(monkeypatch, "deny", reason="no sending")

        _gate.govern(SEND_CALL, _Ctx())

        sent = [e for e in _audit.read_audit() if e["action"] == "tool.send"]
        assert len(sent) == 1 and "decision=deny" in sent[0]["detail"]

    def test_a_parked_send_is_not_settled_until_it_is_reissued(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _verdict(monkeypatch, "ask")
        digest = canonical_args_digest(SEND_TOOL.name, SEND_ARGS)

        _gate.govern(SEND_CALL, _Ctx(approval_mode="park"))
        assert "tool.send" not in _audit_actions()

        token = _pregrant.create_pregrant(
            "demo", "implementer", SEND_TOOL.name, digest, channel="cli"
        )
        ctx = _Ctx(approval_mode="park", pregrants=(_Grant(token, SEND_TOOL.name, digest),))
        assert _gate.govern(SEND_CALL, ctx).decision == "allow"
        assert _audit_actions().count("tool.send") == 1

    def test_an_allowed_write_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _verdict(monkeypatch, "allow", reason="", policy_id="")

        _gate.govern(CALL, _Ctx())

        assert not [a for a in _audit_actions() if a.startswith("tool.")]
