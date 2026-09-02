#!/usr/bin/env python3
"""Run the deterministic Wave 29 adversarial and recovery scenario matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("cases")
HARNESS = ROOT / "benchmarks" / "harness.py"
SCHEMA_VERSION = "1.0.0"
SCENARIO_VERSION = "1.0.0"
SEED = 29
BASELINE = b"baseline\n"
CHANGED = b"changed once\n"
MALFORMED_PRIMARY = b"{malformed-registry"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(_canonical(value) for value in values))


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _free_port(used: set[int]) -> int:
    port = 49_000 + len(used)
    if port == 8081 or port > 65_535:
        raise ValueError("scenario matrix exhausted its bounded port range")
    used.add(port)
    return port


def _public_cli(home: Path, workspace: Path, *args: str) -> None:
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DOCKET_LLM_API_KEY"):
        env.pop(key, None)
    env.update(
        {
            "DOCKET_HOME": str(home),
            "DOCKET_SERVICE_MANAGER": "none",
            "HOME": str(home / "operator"),
            "PYTHONPATH": "",
            "TMPDIR": str(home.parent / "tmp"),
            "UV_CACHE_DIR": str(home.parent / "cache"),
        }
    )
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    Path(env["UV_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"public CLI action {' '.join(args)!r} failed: {output}")


def _valid_hop(role: str = "lead") -> dict[str, Any]:
    return {
        "role": role,
        "member": f"demo-{role}",
        "ok": True,
        "output": "deterministic fixture output",
        "costUsd": 0.0,
        "error": "",
        "attempts": 1,
        "stepId": role,
        "artifact": {
            "summary": "deterministic fixture summary",
            "files_changed": [],
            "diff_ref": "fixture",
            "verdict": None,
            "notes": "",
        },
    }


def _trace(event_type: str, payload: dict[str, Any], *, tick: int) -> dict[str, Any]:
    return {
        "ts": f"2026-09-02T00:00:0{tick}Z",
        "project": "demo",
        "session_id": "agent:demo:task-one",
        "agent_role": "lead",
        "event_type": event_type,
        "payload": payload,
    }


def _prepare_public_pipeline(home: Path, workspace: Path) -> None:
    _write_json(home / "fleet.json", {"agents": [{"id": "demo-lead"}], "bindings": []})
    _write_json(
        home / "workspaces" / "projects" / "demo-lead" / ".docket-meta.json",
        {
            "schemaVersion": 1,
            "kind": "project",
            "scope": "project",
            "role": "lead",
            "name": "demo-lead",
            "codebase": str(workspace),
            "model": "fixture/deterministic",
            "modelSource": "policy",
            "sessionKey": "agent:demo:default",
            "projectKey": "default",
            "created": "2026-09-02T00:00:00+00:00",
        },
    )
    _public_cli(home, workspace, "pipeline", "run", "demo")


def _resolve_approval(home: Path, workspace: Path, state: str) -> None:
    token = "apr-c4-deterministic-fixture"
    approval_path = home / "approvals" / f"{token}.json"
    _write_json(
        approval_path,
        {
            "token": token,
            "project": "demo",
            "role": "lead",
            "action": "write deterministic target",
            "state": "pending",
            "created": "2026-09-02T00:00:00Z",
            "context": {"taskId": "task-one", "pipelineIndex": 0},
        },
    )
    command = "approve" if state == "granted" else "deny"
    _public_cli(home, workspace, command, token)

    audit = [
        json.loads(line)
        for line in (home / "audit.log").read_text(encoding="utf-8").splitlines()
        if line
    ]
    action = f"approval.{'grant' if state == 'granted' else 'deny'}"
    resolved = next(record for record in audit if record.get("action") == action)
    approval = _read_object(approval_path)
    approval["created"] = resolved["ts"]
    _write_json(approval_path, approval)


def _durable_records(home: Path, case: dict[str, Any]) -> dict[str, Any]:
    scenario_id = str(case["scenario_id"])
    completed = bool(case["completed"])
    malformed_handoff = bool(case["malformed_handoff"])
    recovery = bool(case["recovery"])

    retained_hop = _valid_hop()
    hops = [retained_hop]
    if malformed_handoff:
        hops = [
            {
                **_valid_hop("implementer"),
                "artifact": {"summary": 7, "unexpected": "invalid fixture handoff"},
            }
        ]
    elif recovery:
        hops.append(_valid_hop("implementer"))

    task = {
        "id": "task-one",
        "description": "deterministic adversarial benchmark fixture",
        "status": "done" if completed else "failed",
        "created": "2026-09-02T00:00:00+00:00",
        "startedAt": "2026-09-02T00:00:01+00:00",
        "completedAt": "2026-09-02T00:00:03+00:00",
        "source": "operator",
        "reason": "" if completed else "scenario stopped",
        "hops": hops,
        "costUsd": 0.0,
        "claimId": None,
        "claimedAt": "2026-09-02T00:00:01+00:00",
    }
    task_path = home / "workspaces" / "projects" / "demo-lead" / "TASK_LIST.json"
    _write_json(task_path, {"tasks": [task]})

    run = {
        "id": "run-one",
        "source": "cli",
        "project": "demo",
        "state": "succeeded" if completed else "failed",
        "taskIds": ["task-one"],
        "error": "" if completed else "scenario stopped",
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
    runs_doc = {"runs": [run]}
    runs_path = home / "docket-runs.json"
    malformed_hash: str | None = None
    if scenario_id == "corrupt-primary-recovery":
        _write_json(runs_path.with_suffix(".json.bak"), runs_doc)
        runs_path.write_bytes(MALFORMED_PRIMARY)
        _public_cli(home, home.parent / "workspace", "runs", "list", "--json")
        malformed_hash = _sha256(MALFORMED_PRIMARY)
    else:
        _write_json(runs_path, runs_doc)

    session_key = "agent:demo:task-one"
    _write_json(
        home / "sessions" / quote(session_key, safe="") / "session.json",
        {
            "sessionKey": session_key,
            "created": "2026-09-02T00:00:00Z",
            "updated": "2026-09-02T00:00:03Z",
            "messages": [],
            "usage": {"inputTokens": 8, "outputTokens": 3, "cachedTokens": 0, "turns": 1},
        },
    )

    trace = [_trace("session_start", {"task": "task-one"}, tick=0)]
    if recovery:
        trace.append(
            _trace(
                "stale_claim",
                {"task": "task-one", "claimedAt": "2026-09-01T23:00:00Z"},
                tick=1,
            )
        )
    trace.extend(
        [
            _trace(
                "tool_call",
                {"tool": "fixture_write", "callId": "call-one", "arguments": {}},
                tick=1,
            ),
            _trace(
                "tool_result",
                {
                    "tool": "fixture_write",
                    "callId": "call-one",
                    "decision": "allow" if completed else "deny",
                    "ok": completed,
                    "executed": completed,
                },
                tick=2,
            ),
        ]
    )
    if bool(case["prevented"]):
        trace.append(
            _trace(
                "guardrail_block",
                {"hook": "pre_tool", "policy": "fixture-denial", "action": "block"},
                tick=2,
            )
        )
    end_payload = {"status": "done"}
    if not completed:
        end_payload["stop_reason"] = str(case["stop_reason"])
    trace.append(_trace("session_end", end_payload, tick=3))
    _write_jsonl(home / "traces" / "demo" / f"{session_key}.jsonl", trace)
    (home / "audit.log").touch(exist_ok=True)

    recovery_path: str | None = None
    if recovery:
        recovery_path = "snapshots/stale-task.json"
        stale = {
            **task,
            "status": "failed",
            "completedAt": None,
            "failureKind": "stale_claim",
            "reason": "stale claim",
            "hops": [retained_hop],
        }
        _write_json(home / recovery_path, {"tasks": [stale]})

    return {
        "runs_doc": runs_doc,
        "malformed_primary_sha256": malformed_hash,
        "recovery_snapshot": recovery_path,
    }


def _scenario(case: dict[str, Any], recovery_snapshot: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": case["scenario_id"],
        "scenario_version": SCENARIO_VERSION,
        "seed": SEED,
        "measurement_class": "deterministic",
        "source": {"commit": "2" * 40, "artifact_sha256": "3" * 64},
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
                "session_key": "agent:demo:task-one",
                "recovery_snapshot": recovery_snapshot,
                "cost": None,
            }
        ],
    }


def _run_harness(home: Path, scenario: Path, jsonl: Path, aggregate: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "run",
            "--scenario",
            str(scenario),
            "--docket-home",
            str(home),
            "--jsonl",
            str(jsonl),
            "--aggregate",
            str(aggregate),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ""},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout + result.stderr).strip())


def _relative(output: Path, path: Path) -> str:
    return path.relative_to(output).as_posix()


def run_matrix(output: Path, repetitions: int) -> None:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    output.mkdir(parents=True, exist_ok=False)
    cases = [_read_object(path) for path in sorted(CASES.glob("*.json"))]
    used_ports: set[int] = set()
    entries: list[dict[str, Any]] = []

    for case in cases:
        scenario_id = str(case["scenario_id"])
        for repetition in range(1, repetitions + 1):
            run_root = output / "runs" / scenario_id / f"repetition-{repetition}"
            home = run_root / "home"
            workspace = run_root / "workspace"
            home.mkdir(parents=True)
            workspace.mkdir(parents=True)
            before = run_root / "before.txt"
            target = workspace / "target.txt"
            before.write_bytes(BASELINE)
            target.write_bytes(BASELINE)

            if scenario_id != "corrupt-primary-recovery":
                _prepare_public_pipeline(home, workspace)
            if scenario_id in {"approval-denied", "approval-granted"}:
                state = "granted" if scenario_id == "approval-granted" else "denied"
                _resolve_approval(home, workspace, state)

            records = _durable_records(home, case)
            if bool(case["mutates"]):
                target.write_bytes(CHANGED)

            scenario_path = run_root / "scenario.json"
            jsonl = run_root / "attempts.jsonl"
            aggregate = run_root / "aggregate.json"
            evidence_path = run_root / "evidence.json"
            _write_json(
                scenario_path,
                _scenario(case, records["recovery_snapshot"]),
            )
            _run_harness(home, scenario_path, jsonl, aggregate)

            evidence = {
                "scenario_id": scenario_id,
                "repetition": repetition,
                "public_actions": case["public_actions"],
                "write_count": 1 if bool(case["mutates"]) else 0,
                "before_sha256": _sha256(before.read_bytes()),
                "after_sha256": _sha256(target.read_bytes()),
                "malformed_primary_sha256": records["malformed_primary_sha256"],
            }
            _write_json(evidence_path, evidence)
            entries.append(
                {
                    "scenario_id": scenario_id,
                    "repetition": repetition,
                    "port": _free_port(used_ports),
                    "paths": {
                        "home": _relative(output, home),
                        "workspace": _relative(output, workspace),
                        "before": _relative(output, before),
                        "target": _relative(output, target),
                        "scenario": _relative(output, scenario_path),
                        "jsonl": _relative(output, jsonl),
                        "aggregate": _relative(output, aggregate),
                        "evidence": _relative(output, evidence_path),
                    },
                }
            )

    _write_json(
        output / "manifest.json",
        {"schema_version": SCHEMA_VERSION, "repetitions": repetitions, "entries": entries},
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_matrix(args.output, args.repetitions)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"scenario error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
