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
_DOC: dict[str, Any] = yaml.safe_load(_CORPUS.read_text(encoding="utf-8"))
_ROWS: list[dict[str, Any]] = _DOC["rows"]
_FALSE_POSITIVES: list[dict[str, Any]] = _DOC["false_positives"]

_STRENGTH = {"allowed": 0, "warned": 1, "asked": 3, "denied": 4}
_LIMITS = {"opaque-code", "variable", "script-name", "phrase-tripwire"}


def _row_id(row: dict[str, Any]) -> str:
    return f"{row['policy']}|{row['isolation']}|{row['role']}|{row['command'][:60]!r}"


def _recorded(row: dict[str, Any]) -> str:
    """The measured outcome in the vocabulary of ``expected``."""
    if row["outcome"] != "allowed":
        return str(row["outcome"])
    return "warned" if row["policy_action"] == "warn" else "allowed"


@pytest.fixture
def installed(tmp_path: Path) -> Any:
    home = Home(tmp_path / ".docket")
    with use_home(home):
        _policy.install_policies()
        yield tmp_path / "workspace"


def _measure(row: dict[str, Any], workspace: Path) -> str:
    if row["hook"] != "pre_tool_call":
        hit = _policy.policy_eval_detail(row["role"], row["hook"], row["command"])
        return {"allow": "allowed", "warn": "warned"}[hit.action]
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
    allowed = [r for r in _ROWS if r["expected"] == "allowed" and not r.get("benign")]

    assert allowed
    assert all(r.get("limit") in _LIMITS for r in allowed)
    assert not [r for r in _ROWS if r["expected"] != "allowed" and "limit" in r]


def _benign(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("benign")]


def _false_positives(rows: list[dict[str, Any]], workspace: Path) -> list[dict[str, Any]]:
    """The benign rows the gate does not allow."""
    return [r for r in _benign(rows) if _measure(r, workspace) != "allowed"]


def _table(benign: list[dict[str, Any]], missed: list[dict[str, Any]]) -> str:
    """False positives per policy, as `policy: n of m benign rows`, then each missed command."""
    lines = []
    for policy in sorted({r["policy"] for r in benign}):
        total = sum(1 for r in benign if r["policy"] == policy)
        hit = [r for r in missed if r["policy"] == policy]
        lines.append(f"{policy}: {len(hit)} of {total} benign rows asked or denied")
        lines += [f"    {r['isolation']:3} {r['command']!r}" for r in hit]
    return "\n".join(lines)


def test_no_benign_row_asks_or_denies(installed: Path) -> None:
    benign = _benign(_ROWS)
    everything = [*benign, *_FALSE_POSITIVES]
    standing = _false_positives(everything, installed)  # one measurement: the unit ceiling is 2 s
    missed = [row for row in standing if row in benign]
    print(
        "\nfalse positives per policy, rows and known false positives\n"
        + _table(everything, standing)
    )
    assert len(benign) >= 60
    assert missed == [], "false positives:\n" + _table(benign, missed)


def test_a_benign_row_that_asks_fails_naming_its_policy(installed: Path) -> None:
    asking = {**_benign(_ROWS)[0], "policy": "block-destructive", "command": "rm -rf build"}
    asking["isolation"] = "off"
    rows = [*_benign(_ROWS), asking]

    missed = _false_positives(rows, installed)

    assert missed == [asking]
    assert "block-destructive: 1 of" in _table(_benign(rows), missed)


@pytest.mark.parametrize("row", _FALSE_POSITIVES, ids=_row_id)
@pytest.mark.xfail(strict=True, reason="a measured false positive; the card that fixes it moves it")
def test_a_known_false_positive_is_still_one(row: dict[str, Any], installed: Path) -> None:
    assert row["benign"] and row["expected"] == "allowed" and row["why"]

    assert _measure(row, installed) == "allowed"


def test_the_false_positives_are_not_rows_and_the_rows_are_not_false_positives() -> None:
    known = {_row_id(r) for r in _FALSE_POSITIVES}

    assert known
    assert not known & {_row_id(r) for r in _ROWS}
