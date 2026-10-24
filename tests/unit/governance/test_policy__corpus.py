"""The baseline policies against a corpus of commands that differ in text but not in effect."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.agent.tools.registry import ToolContext
from docket.governance import policy as _policy
from docket.governance.gate import evaluate_tool_call
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.home import Home, use_home
from docket.teams.role_composer import registry_for_role

SUBJECT = "docket.governance.policy"

_CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "policy-corpus" / "corpus.yaml"
_ROWS: list[dict[str, Any]] = yaml.safe_load(_CORPUS.read_text(encoding="utf-8"))["rows"]

_STRENGTH = {"allowed": 0, "warned": 1, "redacted": 2, "asked": 3, "denied": 4}
_LIMITS = {
    "opaque-code",
    "variable",
    "script-name",
    "phrase-tripwire",
    "unlisted-secret-shape",
}


def _row_id(row: dict[str, Any]) -> str:
    return f"{row['policy']}|{row['isolation']}|{row['role']}|{row['command'][:60]!r}"


def _recorded(row: dict[str, Any]) -> str:
    """The measured outcome in the vocabulary of ``expected``."""
    if row["outcome"] != "allowed":
        return str(row["outcome"])
    return {"warn": "warned", "redact": "redacted"}.get(row["policy_action"], "allowed")


@pytest.fixture
def installed(tmp_path: Path) -> Any:
    home = Home(tmp_path / ".docket")
    with use_home(home):
        _policy.install_policies()
        yield tmp_path / "workspace"


def _measure(row: dict[str, Any], workspace: Path) -> str:
    if row["hook"] != "pre_tool_call":
        hit = _policy.policy_eval_detail(row["role"], row["hook"], row["command"])
        return {"allow": "allowed", "warn": "warned", "redact": "redacted"}[hit.action]
    tool = registry_for_role(builtin_registry(), row["role"]).get("bash")
    if tool is None:
        return "denied"  # the role never had the tool
    workspace.mkdir(exist_ok=True)
    ctx = ToolContext(
        role=row["role"],
        roots=(workspace,),
        sandbox="auto" if row["isolation"] == "on" else "off",
        approval_mode="refuse",
    )
    verdict = evaluate_tool_call(tool, {"command": row["command"]}, ctx)
    return {"allow": "allowed", "ask": "asked", "deny": "denied"}[verdict.decision]


@pytest.mark.parametrize("row", _ROWS, ids=_row_id)
def test_the_gate_answers_the_expected_outcome(row: dict[str, Any], installed: Path) -> None:
    assert _measure(row, installed) == row["expected"]


def test_no_expected_outcome_is_weaker_than_the_measured_one() -> None:
    weaker = [_row_id(r) for r in _ROWS if _STRENGTH[r["expected"]] < _STRENGTH[_recorded(r)]]

    assert weaker == []


def test_a_row_left_allowed_names_why_and_no_other_row_does() -> None:
    allowed = [r for r in _ROWS if r["expected"] == "allowed"]

    assert allowed
    assert all(r.get("limit") in _LIMITS for r in allowed)
    assert not [r for r in _ROWS if r["expected"] != "allowed" and "limit" in r]
