"""Pure-logic unit tests for core/harness.py: no filesystem, no committed artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docket.core import harness
from docket.core.models import AgentMeta
from docket.core.runtime_driver import TurnResult, UsageReport, UsageTotals

SUBJECT = "docket.core.harness"


# ── contract version ──────────────────────────────────────────────────────────


def test_an_unknown_contract_version_fails_closed() -> None:
    payload = {
        "v": "0.9.0",
        "token": "t1",
        "status": "ok",
        "model": {"requested": "", "served": ""},
        "usage": {},
    }
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessResult.model_validate(payload)


def test_the_shipped_version_validates() -> None:
    result = harness.HarnessResult(
        token="t1", status="ok", model=harness.ModelInfo(), usage=harness.UsageInfo()
    )
    assert result.v == harness.HARNESS_CONTRACT_VERSION


# ── preflight table ───────────────────────────────────────────────────────────


def _base_environ(tmp_path: Path) -> dict[str, str]:
    return {
        "DOCKET_HOME": str(tmp_path / "caller-home"),
        "DOCKET_LLM_BASE_URL": "http://127.0.0.1:8081/v1",
    }


def test_preflight_refuses_when_docket_home_is_unset(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    del environ["DOCKET_HOME"]
    refusal = harness.preflight(environ, tmp_path / "default-home", tmp_path / "workspace")
    assert refusal is not None
    assert "DOCKET_HOME" in refusal.reason


def test_preflight_refuses_the_default_home(tmp_path: Path) -> None:
    default_home = tmp_path / "default-home"
    environ = _base_environ(tmp_path)
    environ["DOCKET_HOME"] = str(default_home)
    refusal = harness.preflight(environ, default_home, tmp_path / "workspace")
    assert refusal is not None
    assert "default home" in refusal.reason


def test_preflight_refuses_a_missing_base_url(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    del environ["DOCKET_LLM_BASE_URL"]
    refusal = harness.preflight(environ, tmp_path / "default-home", tmp_path / "workspace")
    assert refusal is not None
    assert "DOCKET_LLM_BASE_URL" in refusal.reason


def test_preflight_refuses_when_trace_is_disabled(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    environ["DOCKET_NO_TRACE"] = "1"
    refusal = harness.preflight(environ, tmp_path / "default-home", tmp_path / "workspace")
    assert refusal is not None
    assert "DOCKET_NO_TRACE" in refusal.reason


def test_preflight_refuses_a_missing_workspace(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    refusal = harness.preflight(environ, tmp_path / "default-home", tmp_path / "missing")
    assert refusal is not None
    assert "workspace" in refusal.reason


def test_preflight_accepts_a_fully_satisfied_environment(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environ = _base_environ(tmp_path)
    refusal = harness.preflight(environ, tmp_path / "default-home", workspace)
    assert refusal is None


# ── result_from mapping table ─────────────────────────────────────────────────


def _usage(turns: int = 1) -> UsageReport:
    return UsageReport(
        totals=UsageTotals(
            input_tokens=100, output_tokens=20, cache_read=5, cache_write=0, turns=turns
        )
    )


def _run(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "run-1",
        "state": "succeeded",
        "variables": {"model": "local/qwen3-35b"},
    }
    record.update(overrides)
    return record


def test_result_from_maps_a_successful_turn_to_ok() -> None:
    turn = TurnResult(True, "done", 0.0, {"model": "local/qwen3-35b-a3b"})
    result = harness.result_from(turn, _usage(), _run())
    assert result.status == "ok"
    assert result.error == ""
    assert result.blocked is None
    assert result.model.requested == "local/qwen3-35b"
    assert result.model.served == "local/qwen3-35b-a3b"
    assert result.usage.input_tokens == 100
    assert result.usage.cached_tokens == 5
    assert result.token == "run-1"
    assert result.run_state == "succeeded"


def test_result_from_maps_run_cancelled_failure_kind_to_cancelled() -> None:
    turn = TurnResult(False, "", 0.0, {}, "run cancellation requested", "run_cancelled")
    result = harness.result_from(turn, _usage(), _run(state="cancelled"))
    assert result.status == "cancelled"
    assert result.stop_reason == "run_cancelled"
    assert result.blocked is None


def test_result_from_maps_an_approval_unavailable_error_to_blocked_with_the_parsed_rule() -> None:
    error = "tool='bash' call_id='call-9' policy_id='block-destructive' reason='no' approval_unavailable"
    turn = TurnResult(
        False, "", 0.0, {}, error, "invalid_output", stop_reason="approval_unavailable"
    )
    result = harness.result_from(turn, _usage(), _run(state="failed"))
    assert result.status == "blocked"
    assert result.stop_reason == "approval_unavailable"
    assert result.blocked is not None
    assert result.blocked.tool == "bash"
    assert result.blocked.call_id == "call-9"
    assert result.blocked.policy_id == "block-destructive"
    assert result.blocked.denial_kind == "approval_unavailable"


def test_result_from_maps_any_other_failure_to_failed() -> None:
    turn = TurnResult(False, "", 0.0, {}, "backend timed out", "timeout")
    result = harness.result_from(turn, _usage(), _run(state="failed"))
    assert result.status == "failed"
    assert result.stop_reason == "timeout"
    assert result.blocked is None


def test_stop_reason_is_the_loops_own_reason_and_falls_back_to_the_failure_kind() -> None:
    """The loop's stop reason names why the turn ended; `failure_kind` is only the coarse class."""
    turn = TurnResult(
        False, "", 0.0, {}, "no final message", "invalid_output", stop_reason="max_iterations"
    )
    assert harness.result_from(turn, _usage(), _run(state="failed")).stop_reason == "max_iterations"
    bare = TurnResult(False, "", 0.0, {}, "boom", "daemon_error")
    assert harness.result_from(bare, _usage(), _run(state="failed")).stop_reason == "daemon_error"
    ok = TurnResult(True, "done", 0.0, {}, stop_reason="final_message")
    assert harness.result_from(ok, _usage(), _run()).stop_reason == ""


# ── agent_meta_for ────────────────────────────────────────────────────────────


def test_agent_meta_for_round_trips_through_agent_meta_model_validate(tmp_path: Path) -> None:
    meta = harness.agent_meta_for("harness-1", tmp_path, "local/qwen3-35b")
    round_tripped = AgentMeta.model_validate(meta.model_dump(by_alias=True))
    assert round_tripped == meta
    assert meta.codebase == str(tmp_path)
    assert meta.role == "implementer"


def test_agent_meta_for_rejects_a_write_denied_role(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot write"):
        harness.agent_meta_for("harness-1", tmp_path, "local/qwen3-35b", role="reviewer")


# ── refusal_result ────────────────────────────────────────────────────────────


def test_refusal_result_carries_the_reason_with_no_token_and_empty_usage() -> None:
    result = harness.refusal_result("DOCKET_HOME is not set")
    assert result.status == "refused"
    assert result.token == ""
    assert result.error == "DOCKET_HOME is not set"
    assert result.blocked is None
    assert result.model == harness.ModelInfo()
    assert result.usage == harness.UsageInfo()
    assert result.cost_usd is None
    assert result.run_state == ""
    assert result.v == harness.HARNESS_CONTRACT_VERSION


# ── Contract 1.1 ─────────────────────────────────────────────────────────────


def test_refusal_result_can_stamp_the_v11_version() -> None:
    result = harness.refusal_result("DOCKET_HOME is not set", version=harness.HARNESS_CONTRACT_V11)
    assert isinstance(result, harness.HarnessResultV11)
    assert result.v == harness.HARNESS_CONTRACT_V11
    assert result.status == "refused"
    assert result.files == []
    assert result.task is None


def test_result_from_v11_reuses_result_froms_mapping() -> None:
    turn = TurnResult(True, "done", 0.0, {"model": "local/qwen3-35b-a3b"})
    result = harness.result_from_v11(turn, _usage(), _run())
    assert result.v == harness.HARNESS_CONTRACT_V11
    assert result.status == "ok"
    assert result.model.served == "local/qwen3-35b-a3b"
    assert result.usage.input_tokens == 100
    assert result.files == []
    assert result.task is None
    assert result.limits == harness.Limits()


def test_result_from_v11_carries_the_optional_files_and_task() -> None:
    turn = TurnResult(True, "done", 0.0, {})
    files = [harness.FileChange(path="a.py", op="write")]
    task = harness.HarnessTask(status="done", hops=[{"role": "implementer"}])
    result = harness.result_from_v11(turn, _usage(), _run(), files=files, task=task)
    assert result.files == files
    assert result.task == task


def test_a_v11_event_naming_the_v10_version_fails_closed() -> None:
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessEventV11(v="1.0.0", token="t1", seq=0, ts="", event={})


def test_answer_requires_exactly_one_target() -> None:
    with pytest.raises(Exception, match="exactly one"):
        harness.Answer(approvalToken="a", questionId="b", action="accept")
    with pytest.raises(Exception, match="exactly one"):
        harness.Answer(action="accept")
    ok = harness.Answer(approvalToken="a", action="accept")
    assert ok.questionId is None


# ── written files ─────────────────────────────────────────────────────────────


def _call(call_id: str, tool: str, arguments: str) -> dict[str, Any]:
    return {
        "event_type": "tool_call",
        "payload": {"tool": tool, "callId": call_id, "arguments": arguments},
    }


def _outcome(call_id: str, *, executed: bool, ok: bool) -> dict[str, Any]:
    return {
        "event_type": "tool_result",
        "payload": {"callId": call_id, "executed": executed, "ok": ok},
    }


def test_a_write_or_edit_call_is_a_file_change_and_others_are_not() -> None:
    write = harness.file_change_from_tool_call(
        {"tool": "write", "arguments": '{"path": "a.txt", "content": "x"}'}
    )
    edit = harness.file_change_from_tool_call(
        {"tool": "edit", "arguments": '{"path": "b.txt", "old_string": "a"}'}
    )
    assert write == harness.FileChange(path="a.txt", op="write")
    assert edit == harness.FileChange(path="b.txt", op="edit")
    assert harness.file_change_from_tool_call({"tool": "bash", "arguments": "{}"}) is None
    assert harness.file_change_from_tool_call({"tool": "write", "arguments": "not json"}) is None
    assert harness.file_change_from_tool_call({"tool": "write", "arguments": "{}"}) is None


def test_a_status_entry_maps_to_write_delete_or_unknown() -> None:
    assert harness.file_change_from_status("??", "n.txt") == harness.FileChange(
        path="n.txt", op="write"
    )
    assert harness.file_change_from_status(" D", "gone.txt") == harness.FileChange(
        path="gone.txt", op="delete"
    )
    assert harness.file_change_from_status(" M", "m.txt") == harness.FileChange(
        path="m.txt", op="unknown"
    )


def test_written_files_count_only_calls_whose_result_executed_and_ok() -> None:
    tracker = harness.WrittenFiles()
    for record in (
        _call("c1", "write", '{"path": "kept.txt"}'),
        _outcome("c1", executed=True, ok=True),
        _call("c2", "write", '{"path": "blocked.txt"}'),
        _outcome("c2", executed=False, ok=False),
        _call("c3", "edit", '{"path": "failed.txt"}'),
        _outcome("c3", executed=True, ok=False),
    ):
        tracker.observe(record)
    assert tracker.changes == [harness.FileChange(path="kept.txt", op="write")]


def test_merge_keeps_one_entry_per_path_and_the_first_op_named() -> None:
    merged = harness.merge_file_changes(
        [harness.FileChange(path="a.txt", op="edit")],
        [
            harness.FileChange(path="a.txt", op="unknown"),
            harness.FileChange(path="b.txt", op="write"),
        ],
    )
    assert merged == [
        harness.FileChange(path="a.txt", op="edit"),
        harness.FileChange(path="b.txt", op="write"),
    ]


# ── approvals ledger ──────────────────────────────────────────────────────────


def _trace_record(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event_type, "payload": payload}


def _requested(token: str, tool: str = "bash", call_id: str = "call-1") -> dict[str, Any]:
    return _trace_record(
        "approval_requested", {"token": token, "action": "x", "tool": tool, "callId": call_id}
    )


def test_a_ledger_with_no_requests_reports_nothing() -> None:
    assert harness.ApprovalLedger().finish(cancelled=False) == []


def test_an_answered_approval_keeps_its_call_and_the_answer_outcome() -> None:
    ledger = harness.ApprovalLedger()
    ledger.observe(_requested("apr-1"))
    ledger.observe(_trace_record("approval_denied", {"token": "apr-1"}))
    ledger.answered("apr-1", "decline")
    [entry] = ledger.finish(cancelled=False)
    assert entry.model_dump() == {
        "token": "apr-1",
        "tool": "bash",
        "callId": "call-1",
        "outcome": "declined",
    }


def test_a_denial_no_answer_produced_is_timed_out_unless_the_run_was_cancelled() -> None:
    ledger = harness.ApprovalLedger()
    ledger.observe(_requested("apr-1"))
    ledger.observe(_trace_record("approval_denied", {"token": "apr-1"}))
    [entry] = ledger.finish(cancelled=False)
    assert entry.outcome == "timed_out"

    cancelled = harness.ApprovalLedger()
    cancelled.observe(_requested("apr-2"))
    cancelled.observe(_trace_record("approval_denied", {"token": "apr-2"}))
    [entry] = cancelled.finish(cancelled=True)
    assert entry.outcome == "unanswered"


def test_a_denial_after_the_answer_stream_closed_is_unanswered_not_timed_out() -> None:
    ledger = harness.ApprovalLedger()
    ledger.observe(_requested("apr-1"))
    ledger.observe(_trace_record("approval_denied", {"token": "apr-1"}))
    ledger.observe(_requested("apr-2"))
    ledger.stream_closed()
    ledger.observe(_trace_record("approval_denied", {"token": "apr-2"}))
    before, after = ledger.finish(cancelled=False)
    assert before.outcome == "timed_out"
    assert after.outcome == "unanswered"


def test_a_pending_approval_at_the_end_is_unanswered() -> None:
    ledger = harness.ApprovalLedger()
    ledger.observe(_requested("apr-1"))
    [entry] = ledger.finish(cancelled=False)
    assert entry.outcome == "unanswered"


def test_a_lost_race_to_the_timeout_is_not_recorded_as_the_answer() -> None:
    # answered() is only called once approval_grant/deny succeeded; a deny that
    # lost to the timeout never reaches it, so the timeout's denial stands.
    ledger = harness.ApprovalLedger()
    ledger.observe(_requested("apr-1"))
    ledger.observe(_trace_record("approval_denied", {"token": "apr-1"}))
    [entry] = ledger.finish(cancelled=False)
    assert entry.outcome == "timed_out"


def test_result_from_v11_carries_the_approvals_and_defaults_to_none() -> None:
    turn = TurnResult(True, "done", 0.0, {"model": "m"}, "")
    result = harness.result_from_v11(turn, _usage(), _run())
    assert result.approvals == []
    entry = harness.ApprovalEntry(token="apr-1", tool="bash", callId="c", outcome="accepted")
    result = harness.result_from_v11(turn, _usage(), _run(), approvals=[entry])
    assert result.approvals == [entry]


# ── contract 1.2 ──────────────────────────────────────────────────────────────


def test_preflight_under_12_needs_no_base_url(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    del environ["DOCKET_LLM_BASE_URL"]
    (tmp_path / "workspace").mkdir()
    refusal = harness.preflight(
        environ,
        tmp_path / "default-home",
        tmp_path / "workspace",
        version=harness.HARNESS_CONTRACT_V12,
    )
    assert refusal is None


def test_preflight_under_12_still_refuses_an_unset_docket_home(tmp_path: Path) -> None:
    refusal = harness.preflight(
        {}, tmp_path / "default-home", tmp_path, version=harness.HARNESS_CONTRACT_V12
    )
    assert refusal is not None
    assert refusal.reason.startswith("DOCKET_HOME is not set")


def test_preflight_under_11_still_requires_the_base_url(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)
    del environ["DOCKET_LLM_BASE_URL"]
    refusal = harness.preflight(
        environ, tmp_path / "default-home", tmp_path, version=harness.HARNESS_CONTRACT_V11
    )
    assert refusal is not None and "DOCKET_LLM_BASE_URL" in refusal.reason


def test_a_v12_result_naming_another_version_fails_closed() -> None:
    payload = harness.refusal_result("x", version=harness.HARNESS_CONTRACT_V12).model_dump()
    payload["v"] = harness.HARNESS_CONTRACT_V11
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessResultV12.model_validate(payload)


def test_a_v12_refusal_is_stamped_120_with_an_empty_source() -> None:
    result = harness.refusal_result("nope", version=harness.HARNESS_CONTRACT_V12)
    assert isinstance(result, harness.HarnessResultV12)
    assert (result.v, result.status, result.model.source) == ("1.2.0", "refused", "")


def test_the_v12_result_records_how_the_model_was_chosen() -> None:
    turn = TurnResult(True, "done", 0.0, {"model": "stubby/served"}, "")
    usage = UsageReport(totals=UsageTotals())
    result = harness.result_from_v12(
        turn, usage, {"id": "run-1", "variables": {"model": "stubby/m1"}}, source="setup default"
    )
    assert result.v == "1.2.0"
    assert result.model.model_dump() == {
        "requested": "stubby/m1",
        "served": "stubby/served",
        "source": "setup default",
    }
