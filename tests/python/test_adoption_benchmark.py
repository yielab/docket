"""Behavioral contract for W29-C3's adoption benchmark harness.

The suite invokes the repository-local harness as a public subprocess and builds only
documented, durable Docket artifacts under a temporary home.  It deliberately does not import a
future harness helper: successful parsing without the public command would not prove the card.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "benchmarks" / "harness.py"
SCHEMA = ROOT / "benchmarks" / "schema.json"
SCHEMA_VERSION = "1.0.0"

RAW_PROMPT = "RAW_PROMPT_SENTINEL keep the operator's private request"
RAW_SECRET = "sk-fixture-secret-abcdefghijklmnopqrstuvwxyz"
RAW_ARGUMENT = "RAW_TOOL_ARGUMENT_SENTINEL"
RAW_HOME = "/home/alice/private-worktree"
APPROVAL_TOKEN = "apr-private-token-00000000"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(_canonical(value) + b"\n" for value in values))


def _require_red_targets() -> None:
    missing = [str(path.relative_to(ROOT)) for path in (SCHEMA, HARNESS) if not path.is_file()]
    assert not missing, "RED: benchmark contract files are not implemented: " + ", ".join(missing)


def _audit_entry(
    seq: int,
    ts: str,
    action: str,
    detail: str,
    *,
    prev_hash: str,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": ts,
        "user": "Alice Private",
        "pid": 4242,
        "action": action,
        "detail": detail,
        "prev_hash": prev_hash,
    }


def _trace(event_type: str, ts: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": ts,
        "project": "demo",
        "session_id": "agent:demo:task-one",
        "agent_role": "implementer",
        "event_type": event_type,
        "payload": payload,
    }


def _valid_hop(role: str, *, attempts: int, summary: str) -> dict[str, Any]:
    return {
        "role": role,
        "member": f"demo-{role}",
        "ok": True,
        "output": summary,
        "costUsd": 0.0,
        "error": "",
        "attempts": attempts,
        "stepId": role,
        "artifact": {
            "summary": summary,
            "files_changed": [RAW_HOME + "/changed.py"],
            "diff_ref": RAW_HOME,
            "verdict": None,
            "notes": RAW_SECRET,
        },
    }


@dataclass(frozen=True)
class BenchmarkFixture:
    home: Path
    scenario_path: Path
    scenario: dict[str, Any]
    trace_path: Path
    task_path: Path
    recovery_path: Path


def _build_fixture(tmp_path: Path) -> BenchmarkFixture:
    home = tmp_path / "docket-home"
    home.mkdir()

    retained_hop = _valid_hop(
        "lead",
        attempts=2,
        summary=f"{RAW_PROMPT}; secret={RAW_SECRET}; checkout={RAW_HOME}",
    )
    invalid_handoff_hop = {
        "role": "implementer",
        "member": "demo-implementer",
        "ok": True,
        "output": RAW_PROMPT,
        "costUsd": 0.0,
        "error": RAW_SECRET,
        "attempts": 1,
        "stepId": "implementer",
        # HandoffArtifact is extra-forbid and requires a string summary.  This is a measured
        # handoff failure, not permission to copy the invalid artifact into benchmark output.
        "artifact": {"summary": 7, "unexpected": RAW_ARGUMENT},
    }
    final_task = {
        "id": "task-one",
        "description": RAW_PROMPT,
        "status": "done",
        "created": "2026-09-02T00:00:00+00:00",
        "startedAt": "2026-09-02T00:00:01+00:00",
        "completedAt": "2026-09-02T00:00:03+00:00",
        "source": "operator",
        "reason": "",
        "hops": [retained_hop, invalid_handoff_hop],
        "costUsd": 0.0,
        "claimId": None,
        "claimedAt": "2026-09-02T00:00:02+00:00",
    }
    task_path = home / "workspaces" / "projects" / "demo-lead" / "TASK_LIST.json"
    _write_json(task_path, {"tasks": [final_task]})

    _write_json(
        home / "docket-runs.json",
        {
            "runs": [
                {
                    "id": "run-one",
                    "source": "cli",
                    "project": "demo",
                    "state": "succeeded",
                    "taskIds": ["task-one"],
                    "error": "",
                    "created": "2026-09-02T00:00:00+00:00",
                    "startedAt": "2026-09-02T00:00:01+00:00",
                    "finishedAt": "2026-09-02T00:00:03+00:00",
                    "pids": [],
                    "variables": {},
                    "cancellation": {
                        "requestedAt": None,
                        "observedAt": None,
                        "stoppedAt": None,
                        "reason": "",
                        "source": "",
                    },
                }
            ]
        },
    )

    session_key = "agent:demo:task-one"
    session_path = home / "sessions" / quote(session_key, safe="") / "session.json"
    _write_json(
        session_path,
        {
            "sessionKey": session_key,
            "created": "2026-09-02T00:00:00Z",
            "updated": "2026-09-02T00:00:03Z",
            "messages": [{"role": "user", "content": RAW_PROMPT}],
            "usage": {"inputTokens": 12, "outputTokens": 5, "cachedTokens": 0, "turns": 2},
        },
    )
    # A reader that calls driver.usage(agent) instead of selecting the fresh attempt session would
    # incorrectly add this unrelated cumulative usage.
    _write_json(
        home / "sessions" / quote("agent:demo:noise", safe="") / "session.json",
        {
            "sessionKey": "agent:demo:noise",
            "created": "2026-09-01T00:00:00Z",
            "updated": "2026-09-01T00:00:01Z",
            "messages": [],
            "usage": {
                "inputTokens": 10_000,
                "outputTokens": 20_000,
                "cachedTokens": 0,
                "turns": 1,
            },
        },
    )

    recovery_path = home / "snapshots" / "stale-task.json"
    _write_json(
        recovery_path,
        {
            "tasks": [
                {
                    **final_task,
                    "status": "failed",
                    "completedAt": None,
                    "failureKind": "stale_claim",
                    "reason": "stale claim — dispatcher likely crashed mid-task",
                    "hops": [retained_hop],
                }
            ]
        },
    )

    trace_path = home / "traces" / "demo" / f"{session_key}.jsonl"
    _write_jsonl(
        trace_path,
        [
            _trace("session_start", "2026-09-02T00:00:00Z", {"task": "task-one"}),
            _trace(
                "stale_claim",
                "2026-09-02T00:00:01Z",
                {"task": "task-one", "claimedAt": "2026-09-01T23:00:00Z"},
            ),
            _trace(
                "tool_call",
                "2026-09-02T00:00:01Z",
                {
                    "tool": "dangerous_write",
                    "callId": "call-denied",
                    "arguments": {"content": RAW_ARGUMENT, "secret": RAW_SECRET},
                },
            ),
            _trace(
                "tool_result",
                "2026-09-02T00:00:01Z",
                {
                    "tool": "dangerous_write",
                    "callId": "call-denied",
                    "decision": "deny",
                    "ok": False,
                    "executed": False,
                },
            ),
            _trace(
                "tool_call",
                "2026-09-02T00:00:02Z",
                {"tool": "read", "callId": "call-allowed", "arguments": {"path": RAW_HOME}},
            ),
            _trace(
                "tool_result",
                "2026-09-02T00:00:02Z",
                {
                    "tool": "read",
                    "callId": "call-allowed",
                    "decision": "allow",
                    "ok": True,
                    "executed": True,
                },
            ),
            _trace(
                "guardrail_block",
                "2026-09-02T00:00:02Z",
                {"hook": "pre_output", "policy": "no-secret-output", "action": "block"},
            ),
            _trace(
                "approval_requested",
                "2026-09-02T00:00:02Z",
                {"token": APPROVAL_TOKEN, "action": RAW_ARGUMENT},
            ),
            _trace("session_end", "2026-09-02T00:00:03Z", {"status": "done"}),
        ],
    )

    _write_json(
        home / "approvals" / f"{APPROVAL_TOKEN}.json",
        {
            "token": APPROVAL_TOKEN,
            "project": "demo",
            "role": "implementer",
            "action": f"approve {RAW_ARGUMENT}",
            "state": "granted",
            "created": "2026-09-02T00:00:00.250000Z",
            "context": {"taskId": "task-one", "pipelineIndex": 1},
        },
    )
    deny = _audit_entry(
        1,
        "2026-09-02T00:00:00.500000Z",
        "tool.deny",
        "agent=demo-implementer role=implementer project=demo "
        "policy_id='deny-dangerous' policy_action='block' tool=dangerous_write "
        f"reason={RAW_SECRET}",
        prev_hash="0" * 64,
    )
    bare_deny = _audit_entry(
        2,
        "2026-09-02T00:00:00.750000Z",
        "tool.deny",
        "agent=demo-implementer role=implementer project=demo tool=bash reason=classifier",
        prev_hash=hashlib.sha256(_canonical(deny)).hexdigest(),
    )
    grant = _audit_entry(
        3,
        "2026-09-02T00:00:01.250000Z",
        "approval.grant",
        f"token={APPROVAL_TOKEN} project=demo channel=cli",
        prev_hash=hashlib.sha256(_canonical(bare_deny)).hexdigest(),
    )
    _write_jsonl(home / "audit.log", [deny, bare_deny, grant])

    scenario = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": "governed-recovery",
        "scenario_version": "1.0.0",
        "seed": 29,
        "measurement_class": "deterministic",
        "source": {"commit": "a" * 40, "artifact_sha256": "b" * 64},
        "runtime": {
            "name": "docket",
            "version": "0.2.0-beta.1",
            "configuration": {
                "adapter": "fixed",
                "model": "fixture/deterministic",
                "token_budget": 100,
                "max_tool_calls": 4,
            },
        },
        "attempts": [
            {
                "ordinal": 1,
                "run_id": "run-one",
                "project": "demo",
                "task_id": "task-one",
                "session_key": session_key,
                "recovery_snapshot": "snapshots/stale-task.json",
                "cost": None,
            }
        ],
    }
    scenario_path = tmp_path / "scenario.json"
    _write_json(scenario_path, scenario)
    return BenchmarkFixture(home, scenario_path, scenario, trace_path, task_path, recovery_path)


def _invoke_run(
    fixture: BenchmarkFixture, jsonl: Path, aggregate: Path
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": ""}
    return subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "run",
            "--scenario",
            str(fixture.scenario_path),
            "--docket-home",
            str(fixture.home),
            "--jsonl",
            str(jsonl),
            "--aggregate",
            str(aggregate),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _invoke_aggregate(jsonl: Path, aggregate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "aggregate",
            "--jsonl",
            str(jsonl),
            "--aggregate",
            str(aggregate),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ""},
        text=True,
        capture_output=True,
        check=False,
    )


def _attempt_id(scenario: dict[str, Any], ordinal: int) -> str:
    identity = {
        "attempt_ordinal": ordinal,
        "measurement_class": scenario["measurement_class"],
        "runtime": scenario["runtime"],
        "scenario": {
            "id": scenario["scenario_id"],
            "version": scenario["scenario_version"],
            "seed": scenario["seed"],
        },
        "source": scenario["source"],
    }
    return "sha256:" + hashlib.sha256(_canonical(identity)).hexdigest()


def test_schema_is_a_closed_versioned_attempt_and_aggregate_contract() -> None:
    _require_red_targets()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["version"] == SCHEMA_VERSION
    assert {"scenario", "attempt", "aggregate", "cost", "recovery", "locators"} <= set(
        schema["$defs"]
    )
    for definition in ("scenario", "attempt", "aggregate"):
        assert schema["$defs"][definition]["additionalProperties"] is False


def test_run_joins_public_records_and_emits_deterministic_private_output(tmp_path: Path) -> None:
    _require_red_targets()
    fixture = _build_fixture(tmp_path)
    first_jsonl = tmp_path / "first.jsonl"
    first_aggregate = tmp_path / "first.json"
    second_jsonl = tmp_path / "second.jsonl"
    second_aggregate = tmp_path / "second.json"

    first = _invoke_run(fixture, first_jsonl, first_aggregate)
    second = _invoke_run(fixture, second_jsonl, second_aggregate)
    assert first.returncode == 0, first.stderr or first.stdout
    assert second.returncode == 0, second.stderr or second.stdout
    assert first_jsonl.read_bytes() == second_jsonl.read_bytes()
    assert first_aggregate.read_bytes() == second_aggregate.read_bytes()

    lines = first_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    attempt = json.loads(lines[0])
    assert attempt["schema_version"] == SCHEMA_VERSION
    assert attempt["record_type"] == "attempt"
    assert attempt["attempt_id"] == _attempt_id(fixture.scenario, 1)
    assert attempt["scenario"] == {"id": "governed-recovery", "version": "1.0.0", "seed": 29}
    assert attempt["source"] == {"commit": "a" * 40, "artifact_sha256": "b" * 64}
    assert attempt["measurement_class"] == "deterministic"
    assert attempt["attempt_ordinal"] == 1
    assert attempt["attempts"] == 3
    assert attempt["completed"] is True
    assert attempt["usage"] == {
        "basis": "provider_reported",
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
    }
    assert attempt["tool_calls"] == {"total": 2, "executed": 1}
    assert attempt["prevented_policy_violations"] == 2
    assert attempt["approval_latency_ms"] == 1000
    assert attempt["recovery"] == {
        "stale_claim_observed": True,
        "retained_hops": 1,
        "resumed_to_terminal": True,
    }
    assert attempt["handoff_failures"] == 1
    assert attempt["stop_reason"] == "final_message"
    assert attempt["cost"] is None

    locators = attempt["locators"]
    assert locators["run"] == "docket-runs.json#run-one"
    assert locators["task"].endswith("TASK_LIST.json#task-one")
    assert locators["session"].endswith("session.json")
    assert locators["trace"].endswith(".jsonl")
    assert locators["audit"] == ["audit.log#seq=1", "audit.log#seq=3"]
    assert locators["recovery_snapshot"] == "snapshots/stale-task.json#task-one"
    assert all(
        not Path(value.split("#", 1)[0]).is_absolute()
        for value in locators.values()
        if isinstance(value, str)
    )

    combined = first_jsonl.read_text(encoding="utf-8") + first_aggregate.read_text(encoding="utf-8")
    for forbidden in (
        RAW_PROMPT,
        RAW_SECRET,
        RAW_ARGUMENT,
        RAW_HOME,
        APPROVAL_TOKEN,
        "Alice Private",
        '"pid"',
        '"arguments"',
        str(fixture.home),
    ):
        assert forbidden not in combined

    rebuilt = tmp_path / "rebuilt.json"
    replay = _invoke_aggregate(first_jsonl, rebuilt)
    assert replay.returncode == 0, replay.stderr or replay.stdout
    assert rebuilt.read_bytes() == first_aggregate.read_bytes()


def test_explicit_cost_is_always_an_estimate_with_versioned_provenance(tmp_path: Path) -> None:
    _require_red_targets()
    fixture = _build_fixture(tmp_path)
    cost = {
        "usd": "0.001230",
        "estimate": True,
        "pricing": {
            "source": "fixture-pricing",
            "version": "2026-09-02",
            "assumption": "input and output tokens priced independently",
        },
    }
    scenario = copy.deepcopy(fixture.scenario)
    scenario["attempts"][0]["cost"] = cost
    _write_json(fixture.scenario_path, scenario)

    output = tmp_path / "priced.jsonl"
    result = _invoke_run(fixture, output, tmp_path / "priced.json")
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["cost"] == cost


Mutation = Callable[[BenchmarkFixture], None]


def _mismatch_run_join(fixture: BenchmarkFixture) -> None:
    _write_json(
        fixture.home / "docket-runs.json",
        {"runs": [{"id": "run-one", "state": "succeeded", "taskIds": ["different-task"]}]},
    )


def _orphan_tool_call(fixture: BenchmarkFixture) -> None:
    records = [
        json.loads(line) for line in fixture.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    records = [
        record
        for record in records
        if not (
            record["event_type"] == "tool_result"
            and record.get("payload", {}).get("callId") == "call-allowed"
        )
    ]
    _write_jsonl(fixture.trace_path, records)


def _duplicate_ordinal(fixture: BenchmarkFixture) -> None:
    scenario = copy.deepcopy(fixture.scenario)
    scenario["attempts"].append(copy.deepcopy(scenario["attempts"][0]))
    _write_json(fixture.scenario_path, scenario)


def _reuse_session(fixture: BenchmarkFixture) -> None:
    scenario = copy.deepcopy(fixture.scenario)
    second = copy.deepcopy(scenario["attempts"][0])
    second["ordinal"] = 2
    second["run_id"] = "run-two"
    second["task_id"] = "task-two"
    scenario["attempts"].append(second)
    _write_json(fixture.scenario_path, scenario)


def _unlabelled_cost(fixture: BenchmarkFixture) -> None:
    scenario = copy.deepcopy(fixture.scenario)
    scenario["attempts"][0]["cost"] = {
        "usd": "0.00",
        "estimate": False,
        "pricing": {"source": "", "version": "", "assumption": ""},
    }
    _write_json(fixture.scenario_path, scenario)


def _secret_pricing(fixture: BenchmarkFixture) -> None:
    scenario = copy.deepcopy(fixture.scenario)
    scenario["attempts"][0]["cost"] = {
        "usd": "0.001000",
        "estimate": True,
        "pricing": {
            "source": "fixture-pricing",
            "version": "2026-09-02",
            "assumption": RAW_SECRET,
        },
    }
    _write_json(fixture.scenario_path, scenario)


def _escaping_snapshot(fixture: BenchmarkFixture) -> None:
    scenario = copy.deepcopy(fixture.scenario)
    scenario["attempts"][0]["recovery_snapshot"] = "../../private.json"
    _write_json(fixture.scenario_path, scenario)


@pytest.mark.parametrize(
    "mutate",
    [
        _mismatch_run_join,
        _orphan_tool_call,
        _duplicate_ordinal,
        _reuse_session,
        _unlabelled_cost,
        _secret_pricing,
        _escaping_snapshot,
    ],
    ids=[
        "mismatched-run-task",
        "partial-tool-pair",
        "duplicate-attempt",
        "reused-session",
        "unlabelled-dollar",
        "secret-pricing",
        "path-escape",
    ],
)
def test_invalid_or_mismatched_input_preserves_both_prior_outputs(
    tmp_path: Path, mutate: Mutation
) -> None:
    _require_red_targets()
    fixture = _build_fixture(tmp_path)
    mutate(fixture)
    jsonl = tmp_path / "attempts.jsonl"
    aggregate = tmp_path / "aggregate.json"
    jsonl.write_bytes(b"PRIOR JSONL\n")
    aggregate.write_bytes(b"PRIOR AGGREGATE\n")

    result = _invoke_run(fixture, jsonl, aggregate)

    assert result.returncode != 0
    assert jsonl.read_bytes() == b"PRIOR JSONL\n"
    assert aggregate.read_bytes() == b"PRIOR AGGREGATE\n"


def test_jsonl_only_aggregate_rejects_duplicates_without_overwrite(tmp_path: Path) -> None:
    _require_red_targets()
    fixture = _build_fixture(tmp_path)
    valid_jsonl = tmp_path / "valid.jsonl"
    valid_aggregate = tmp_path / "valid.json"
    generated = _invoke_run(fixture, valid_jsonl, valid_aggregate)
    assert generated.returncode == 0, generated.stderr or generated.stdout

    duplicate_jsonl = tmp_path / "duplicate.jsonl"
    line = valid_jsonl.read_bytes()
    duplicate_jsonl.write_bytes(line + line)
    target = tmp_path / "existing.json"
    target.write_bytes(b"PRIOR AGGREGATE\n")

    result = _invoke_aggregate(duplicate_jsonl, target)

    assert result.returncode != 0
    assert target.read_bytes() == b"PRIOR AGGREGATE\n"
