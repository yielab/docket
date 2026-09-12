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
    turn = TurnResult(False, "", 0.0, {}, error, "invalid_output")
    result = harness.result_from(turn, _usage(), _run(state="failed"))
    assert result.status == "blocked"
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
