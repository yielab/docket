#!/usr/bin/env python3
"""Deterministic adoption benchmark over public, durable Docket artifacts."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import quote

from docket.core.handoff import HandoffArtifact

SCHEMA_VERSION = "1.0.0"
MAX_INPUT_BYTES = 16 * 1024 * 1024
GENESIS_HASH = "0" * 64

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_HEX_40_64 = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_USD = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{6}$")
_PUBLIC_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+()%\-]{0,199}$")
_SECRET = re.compile(
    r"(?:api[_-]?key|secret|token|bearer|authorization)\s*[=:]\s*"
    r"[A-Za-z0-9/_\-+.]{12,}|\b(?:sk|pk)-(?:ant|live|proj|test|fixture)-"
    r"[A-Za-z0-9/_\-+.]{12,}",
    re.IGNORECASE,
)
_POLICY_ID = re.compile(r"(?:^|\s)policy_id='([^']+)'(?:\s|$)")
_POLICY_ACTION = re.compile(r"(?:^|\s)policy_action='([^']+)'(?:\s|$)")
_PROJECT = re.compile(r"(?:^|\s)project=(?:'([^']+)'|\"([^\"]+)\"|(\S+))")
_TOKEN = re.compile(r"(?:^|\s)token=(?:'([^']+)'|\"([^\"]+)\"|(\S+))")

_SCENARIO_KEYS = {
    "schema_version",
    "scenario_id",
    "scenario_version",
    "seed",
    "measurement_class",
    "source",
    "runtime",
    "attempts",
}
_SOURCE_KEYS = {"commit", "artifact_sha256"}
_RUNTIME_KEYS = {"name", "version", "configuration"}
_CONFIG_KEYS = {"adapter", "model", "token_budget", "max_tool_calls"}
_COORDINATE_KEYS = {
    "ordinal",
    "run_id",
    "project",
    "task_id",
    "session_key",
    "recovery_snapshot",
    "cost",
}
_COST_KEYS = {"usd", "estimate", "pricing"}
_PRICING_KEYS = {"source", "version", "assumption"}

_ATTEMPT_KEYS = {
    "schema_version",
    "record_type",
    "attempt_id",
    "scenario",
    "source",
    "runtime",
    "measurement_class",
    "attempt_ordinal",
    "attempts",
    "completed",
    "usage",
    "tool_calls",
    "prevented_policy_violations",
    "approval_latency_ms",
    "recovery",
    "handoff_failures",
    "stop_reason",
    "cost",
    "locators",
}
_SCENARIO_COORDINATE_KEYS = {"id", "version", "seed"}
_USAGE_KEYS = {"basis", "input_tokens", "output_tokens", "total_tokens"}
_TOOL_COUNT_KEYS = {"total", "executed"}
_RECOVERY_KEYS = {"stale_claim_observed", "retained_hops", "resumed_to_terminal"}
_LOCATOR_KEYS = {"run", "task", "session", "trace", "audit", "recovery_snapshot"}

_AGGREGATE_KEYS = {
    "schema_version",
    "record_type",
    "aggregate_id",
    "jsonl_sha256",
    "scenario",
    "source",
    "runtime",
    "measurement_class",
    "attempts",
    "completions",
    "completion_rate",
    "usage",
    "tool_calls",
    "prevented_policy_violations",
    "approval_latency_ms",
    "recovery",
    "handoff_failures",
    "stop_reasons",
    "cost",
}

_STOP_REASONS = {
    "final_message",
    "max_iterations",
    "max_tool_calls",
    "timeout",
    "token_budget",
    "truncated",
    "backend_error",
    "compaction_failed",
    "context_fit",
    "tool_denials",
    "run_cancelled",
}


class BenchmarkError(ValueError):
    """One invalid or inconsistent benchmark input."""


def _fail(message: str) -> NoReturn:
    raise BenchmarkError(message)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail(f"value is not canonical JSON: {exc}")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expect_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        _fail(f"{label} fields mismatch (missing={missing}, unknown={unknown})")
    return value


def _expect_string(value: object, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _fail(f"{label} must be a{' non-empty' if nonempty else ''} string")
    return value


def _expect_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{label} must be a Boolean")
    return value


def _expect_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _expect_safe_id(value: object, label: str) -> str:
    text = _expect_string(value, label)
    if not _SAFE_ID.fullmatch(text):
        _fail(f"{label} is not a safe identifier")
    return text


def _expect_public_text(value: object, label: str) -> str:
    text = _expect_string(value, label)
    if not _PUBLIC_TEXT.fullmatch(text) or _SECRET.search(text):
        _fail(f"{label} is not bounded public provenance text")
    return text


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        size = path.stat().st_size
        if size > MAX_INPUT_BYTES:
            _fail(f"{label} exceeds {MAX_INPUT_BYTES} bytes")
        return path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {label}: {exc}")


def _read_json(path: Path, label: str) -> Any:
    raw = _read_bytes(path, label)
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")


def _read_jsonl(path: Path, label: str, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    raw = _read_bytes(path, label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(f"invalid UTF-8 in {label}: {exc}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            _fail(f"blank line {line_number} in {label}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"invalid JSON on line {line_number} of {label}: {exc}")
        if not isinstance(value, dict):
            _fail(f"line {line_number} of {label} must be an object")
        records.append(value)
    if not records and not allow_empty:
        _fail(f"{label} has no records")
    return records


def _relative_path(home: Path, raw: object, label: str) -> tuple[Path, str]:
    text = _expect_string(raw, label)
    candidate = Path(text)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        _fail(f"{label} must be a non-escaping path relative to Docket home")
    try:
        resolved = (home / candidate).resolve(strict=True)
        relative = resolved.relative_to(home)
    except (OSError, ValueError) as exc:
        _fail(f"invalid {label}: {exc}")
    return resolved, relative.as_posix()


def _derived_path(home: Path, relative: Path, label: str) -> tuple[Path, str]:
    try:
        path = (home / relative).resolve(strict=True)
        safe = path.relative_to(home).as_posix()
    except (OSError, ValueError) as exc:
        _fail(f"invalid {label}: {exc}")
    return path, safe


def _validate_cost(value: object, label: str = "cost") -> dict[str, Any] | None:
    if value is None:
        return None
    cost = _expect_object(value, _COST_KEYS, label)
    usd = _expect_string(cost["usd"], f"{label}.usd")
    if not _USD.fullmatch(usd):
        _fail(f"{label}.usd must be a canonical non-negative decimal with six places")
    try:
        amount = Decimal(usd)
    except InvalidOperation:
        _fail(f"{label}.usd is not a decimal")
    if not amount.is_finite() or amount < 0:
        _fail(f"{label}.usd must be finite and non-negative")
    if cost["estimate"] is not True:
        _fail(f"{label}.estimate must be true")
    pricing = _expect_object(cost["pricing"], _PRICING_KEYS, f"{label}.pricing")
    normalized_pricing = {
        key: _expect_public_text(pricing[key], f"{label}.pricing.{key}")
        for key in sorted(_PRICING_KEYS)
    }
    return {
        "usd": usd,
        "estimate": True,
        "pricing": normalized_pricing,
    }


def _validate_runtime(value: object, label: str = "runtime") -> dict[str, Any]:
    runtime = _expect_object(value, _RUNTIME_KEYS, label)
    name = _expect_safe_id(runtime["name"], f"{label}.name")
    version = _expect_safe_id(runtime["version"], f"{label}.version")
    config = _expect_object(runtime["configuration"], _CONFIG_KEYS, f"{label}.configuration")
    adapter = _expect_safe_id(config["adapter"], f"{label}.configuration.adapter")
    model = _expect_string(config["model"], f"{label}.configuration.model")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]+", model):
        _fail(f"{label}.configuration.model must be a provider/model id")
    token_budget = _expect_int(
        config["token_budget"], f"{label}.configuration.token_budget", minimum=1
    )
    max_tool_calls = _expect_int(
        config["max_tool_calls"], f"{label}.configuration.max_tool_calls", minimum=1
    )
    return {
        "name": name,
        "version": version,
        "configuration": {
            "adapter": adapter,
            "model": model,
            "token_budget": token_budget,
            "max_tool_calls": max_tool_calls,
        },
    }


def _validate_source(value: object, label: str = "source") -> dict[str, str]:
    source = _expect_object(value, _SOURCE_KEYS, label)
    commit = _expect_string(source["commit"], f"{label}.commit")
    artifact = _expect_string(source["artifact_sha256"], f"{label}.artifact_sha256")
    if not _HEX_40_64.fullmatch(commit):
        _fail(f"{label}.commit must be a lowercase 40-64 character hex digest")
    if not _HEX_64.fullmatch(artifact):
        _fail(f"{label}.artifact_sha256 must be a lowercase SHA-256 digest")
    return {"commit": commit, "artifact_sha256": artifact}


def _validate_scenario(value: object) -> dict[str, Any]:
    scenario = _expect_object(value, _SCENARIO_KEYS, "scenario")
    if scenario["schema_version"] != SCHEMA_VERSION:
        _fail(f"unsupported scenario schema_version: {scenario['schema_version']!r}")
    scenario_id = _expect_safe_id(scenario["scenario_id"], "scenario.scenario_id")
    scenario_version = _expect_safe_id(scenario["scenario_version"], "scenario.scenario_version")
    seed = _expect_int(scenario["seed"], "scenario.seed")
    measurement_class = scenario["measurement_class"]
    if measurement_class not in {"deterministic", "live"}:
        _fail("scenario.measurement_class must be deterministic or live")
    source = _validate_source(scenario["source"], "scenario.source")
    runtime = _validate_runtime(scenario["runtime"], "scenario.runtime")
    raw_attempts = scenario["attempts"]
    if not isinstance(raw_attempts, list) or not raw_attempts:
        _fail("scenario.attempts must be a non-empty array")
    attempts: list[dict[str, Any]] = []
    ordinals: set[int] = set()
    sessions: set[str] = set()
    for index, raw in enumerate(raw_attempts):
        item = _expect_object(raw, _COORDINATE_KEYS, f"scenario.attempts[{index}]")
        ordinal = _expect_int(item["ordinal"], f"scenario.attempts[{index}].ordinal", minimum=1)
        if ordinal in ordinals:
            _fail(f"duplicate attempt ordinal: {ordinal}")
        ordinals.add(ordinal)
        session_key = _expect_safe_id(
            item["session_key"], f"scenario.attempts[{index}].session_key"
        )
        if session_key in sessions:
            _fail(f"session key is not fresh across attempts: {session_key}")
        sessions.add(session_key)
        recovery = item["recovery_snapshot"]
        if recovery is not None:
            recovery = _expect_string(recovery, f"scenario.attempts[{index}].recovery_snapshot")
            candidate = Path(recovery)
            if candidate.is_absolute() or ".." in candidate.parts:
                _fail("recovery_snapshot must be relative and non-escaping")
        attempts.append(
            {
                "ordinal": ordinal,
                "run_id": _expect_safe_id(item["run_id"], f"scenario.attempts[{index}].run_id"),
                "project": _expect_safe_id(item["project"], f"scenario.attempts[{index}].project"),
                "task_id": _expect_safe_id(item["task_id"], f"scenario.attempts[{index}].task_id"),
                "session_key": session_key,
                "recovery_snapshot": recovery,
                "cost": _validate_cost(item["cost"], f"scenario.attempts[{index}].cost"),
            }
        )
    attempts.sort(key=lambda item: item["ordinal"])
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "scenario_version": scenario_version,
        "seed": seed,
        "measurement_class": measurement_class,
        "source": source,
        "runtime": runtime,
        "attempts": attempts,
    }


def _find_unique(records: object, key: str, value: str, label: str) -> dict[str, Any]:
    if not isinstance(records, list):
        _fail(f"{label} must be an array")
    matches = [
        record for record in records if isinstance(record, dict) and record.get(key) == value
    ]
    if len(matches) != 1:
        _fail(f"expected exactly one {label} record with {key}={value!r}, found {len(matches)}")
    return matches[0]


def _parse_time(value: object, label: str) -> datetime:
    text = _expect_string(value, label)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        _fail(f"{label} is not an ISO timestamp")
    if parsed.tzinfo is None:
        _fail(f"{label} must include a timezone")
    return parsed


def _detail_match(pattern: re.Pattern[str], detail: str) -> str | None:
    match = pattern.search(detail)
    if match is None:
        return None
    return next((group for group in match.groups() if group is not None), None)


def _audit_seq(record: dict[str, Any], label: str) -> int:
    return _expect_int(record.get("seq"), f"{label}.seq", minimum=1)


def _load_audit(home: Path) -> tuple[list[dict[str, Any]], str]:
    path, relative = _derived_path(home, Path("audit.log"), "audit log")
    records = _read_jsonl(path, "audit log", allow_empty=True)
    seen: set[int] = set()
    for index, record in enumerate(records):
        seq = _audit_seq(record, f"audit[{index}]")
        if seq in seen:
            _fail(f"duplicate audit sequence: {seq}")
        seen.add(seq)
    return records, relative


def _trace_evidence(
    home: Path, project: str, session_key: str, task_id: str
) -> tuple[dict[str, Any], str]:
    trace_path, relative = _derived_path(
        home, Path("traces") / project / f"{session_key}.jsonl", "trace"
    )
    records = _read_jsonl(trace_path, "trace")
    pending: dict[str, str] = {}
    finished: set[str] = set()
    executed = 0
    guardrail_blocks = 0
    stale_claims = 0
    for index, record in enumerate(records):
        if record.get("project") != project or record.get("session_id") != session_key:
            _fail(f"trace record {index + 1} has mismatched project/session identity")
        event_type = _expect_string(record.get("event_type"), f"trace[{index}].event_type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            _fail(f"trace[{index}].payload must be an object")
        if event_type == "tool_call":
            call_id = _expect_string(payload.get("callId"), f"trace[{index}].payload.callId")
            tool = _expect_string(payload.get("tool"), f"trace[{index}].payload.tool")
            if call_id in pending or call_id in finished:
                _fail(f"duplicate tool call id: {call_id}")
            pending[call_id] = tool
        elif event_type == "tool_result":
            call_id = _expect_string(payload.get("callId"), f"trace[{index}].payload.callId")
            tool = _expect_string(payload.get("tool"), f"trace[{index}].payload.tool")
            if pending.get(call_id) != tool:
                _fail(f"orphan or mismatched tool result: {call_id}")
            is_executed = _expect_bool(payload.get("executed"), f"trace[{index}].payload.executed")
            executed += int(is_executed)
            del pending[call_id]
            finished.add(call_id)
        elif event_type == "guardrail_block":
            guardrail_blocks += 1
        elif event_type == "stale_claim" and payload.get("task") == task_id:
            stale_claims += 1
    if pending:
        _fail(f"tool calls lack matching results: {sorted(pending)}")
    if stale_claims > 1:
        _fail(f"multiple stale_claim events for task {task_id}")
    return {
        "records": records,
        "tool_total": len(finished),
        "tool_executed": executed,
        "guardrail_blocks": guardrail_blocks,
        "stale_claim": stale_claims == 1,
    }, relative


def _policy_denials(
    audit: list[dict[str, Any]], project: str, audit_relative: str
) -> tuple[int, list[str]]:
    count = 0
    locators: list[str] = []
    for index, record in enumerate(audit):
        if record.get("action") != "tool.deny":
            continue
        detail = _expect_string(record.get("detail"), f"audit[{index}].detail", nonempty=False)
        policy_id = _detail_match(_POLICY_ID, detail)
        policy_action = _detail_match(_POLICY_ACTION, detail)
        entry_project = _detail_match(_PROJECT, detail)
        if entry_project != project or not policy_id or not policy_action:
            continue
        if policy_action == "allow":
            continue
        seq = _audit_seq(record, f"audit[{index}]")
        count += 1
        locators.append(f"{audit_relative}#seq={seq}")
    return count, locators


def _approval_latency(
    home: Path,
    audit: list[dict[str, Any]],
    audit_relative: str,
    project: str,
    task_id: str,
) -> tuple[int | None, list[str], list[str]]:
    approval_dir = home / "approvals"
    if not approval_dir.exists():
        return None, [], []
    relevant: list[dict[str, Any]] = []
    for path in sorted(approval_dir.glob("*.json")):
        try:
            resolved_path = path.resolve(strict=True)
            resolved_path.relative_to(home)
        except (OSError, ValueError) as exc:
            _fail(f"approval path escapes Docket home: {exc}")
        record = _read_json(resolved_path, "approval")
        if not isinstance(record, dict):
            _fail("approval must be an object")
        context = record.get("context")
        if (
            isinstance(context, dict)
            and context.get("taskId") == task_id
            and record.get("project") == project
        ):
            relevant.append(record)
    if not relevant:
        return None, [], []
    if len(relevant) != 1:
        _fail(f"expected at most one approval for task {task_id}, found {len(relevant)}")
    approval = relevant[0]
    token = _expect_string(approval.get("token"), "approval.token")
    state = approval.get("state")
    action = {"granted": "approval.grant", "denied": "approval.deny"}.get(str(state))
    if action is None:
        _fail("selected approval is not terminal")
    matches: list[dict[str, Any]] = []
    for index, record in enumerate(audit):
        if record.get("action") != action:
            continue
        detail = _expect_string(record.get("detail"), f"audit[{index}].detail", nonempty=False)
        if _detail_match(_TOKEN, detail) == token:
            matches.append(record)
    if len(matches) != 1:
        _fail(f"expected one terminal audit event for selected approval, found {len(matches)}")
    created = _parse_time(approval.get("created"), "approval.created")
    resolved_at = _parse_time(matches[0].get("ts"), "approval audit timestamp")
    delta = (resolved_at - created).total_seconds() * 1000
    if delta < 0 or not math.isfinite(delta) or not delta.is_integer():
        _fail("approval latency must be a non-negative whole number of milliseconds")
    seq = _audit_seq(matches[0], "approval audit")
    return int(delta), [f"{audit_relative}#seq={seq}"], [token]


def _handoff_failures(hops: object, label: str) -> int:
    if not isinstance(hops, list):
        _fail(f"{label} must be an array")
    failures = 0
    for index, hop in enumerate(hops):
        if not isinstance(hop, dict):
            _fail(f"{label}[{index}] must be an object")
        artifact = hop.get("artifact")
        if artifact is None:
            continue
        try:
            HandoffArtifact.model_validate(artifact)
        except Exception:
            failures += 1
    return failures


def _attempts(hops: object) -> int:
    if not isinstance(hops, list) or not hops:
        _fail("selected task must contain at least one persisted hop")
    total = 0
    for index, hop in enumerate(hops):
        if not isinstance(hop, dict):
            _fail(f"task.hops[{index}] must be an object")
        total += _expect_int(hop.get("attempts"), f"task.hops[{index}].attempts", minimum=1)
    return total


def _recovery(
    home: Path,
    coordinate: dict[str, Any],
    task: dict[str, Any],
    trace: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    raw_path = coordinate["recovery_snapshot"]
    if raw_path is None:
        if trace["stale_claim"]:
            _fail("stale_claim trace requires a recovery snapshot")
        return {
            "stale_claim_observed": False,
            "retained_hops": 0,
            "resumed_to_terminal": False,
        }, None
    path, relative = _relative_path(home, raw_path, "recovery_snapshot")
    snapshot = _read_json(path, "recovery snapshot")
    if not isinstance(snapshot, dict):
        _fail("recovery snapshot must be an object")
    stale = _find_unique(snapshot.get("tasks"), "id", coordinate["task_id"], "snapshot tasks")
    if stale.get("status") != "failed" or stale.get("failureKind") != "stale_claim":
        _fail("recovery snapshot is not a stale_claim failure")
    retained = stale.get("hops")
    if not isinstance(retained, list) or not retained:
        _fail("recovery snapshot has no retained hops")
    if _handoff_failures(retained, "recovery.hops") != 0:
        _fail("recovery snapshot retained an invalid handoff artifact")
    final_hops = task.get("hops")
    if not isinstance(final_hops, list) or len(final_hops) < len(retained):
        _fail("terminal task lost retained recovery hops")
    if _canonical(final_hops[: len(retained)]) != _canonical(retained):
        _fail("terminal task does not preserve the retained hop prefix")
    terminal = task.get("status") in {"done", "failed", "blocked", "cancelled"}
    if not trace["stale_claim"] or not terminal:
        _fail("recovery lacks matching stale_claim trace or terminal resumed task")
    return {
        "stale_claim_observed": True,
        "retained_hops": len(retained),
        "resumed_to_terminal": True,
    }, f"{relative}#{coordinate['task_id']}"


def _stop_reason(run: dict[str, Any], task: dict[str, Any], trace: dict[str, Any]) -> str:
    hops = task.get("hops")
    if (
        run.get("state") == "succeeded"
        and task.get("status") == "done"
        and isinstance(hops, list)
        and hops
        and all(isinstance(hop, dict) and hop.get("ok") is True for hop in hops)
    ):
        return "final_message"
    if run.get("state") == "cancelled" or task.get("status") == "cancelled":
        return "run_cancelled"
    for record in reversed(trace["records"]):
        if record.get("event_type") != "session_end":
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("stop_reason") in _STOP_REASONS:
            return str(payload["stop_reason"])
    if any(record.get("event_type") == "budget_exceeded" for record in trace["records"]):
        return "token_budget"
    _fail("durable records do not expose an unambiguous typed stop reason")


def _attempt_identity(scenario: dict[str, Any], ordinal: int) -> str:
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
    return "sha256:" + _sha256(_canonical(identity))


def _build_attempt(
    home: Path, scenario: dict[str, Any], coordinate: dict[str, Any]
) -> dict[str, Any]:
    run_path, run_relative = _derived_path(home, Path("docket-runs.json"), "run registry")
    runs_doc = _read_json(run_path, "run registry")
    if not isinstance(runs_doc, dict):
        _fail("run registry must be an object")
    run = _find_unique(runs_doc.get("runs"), "id", coordinate["run_id"], "runs")
    if run.get("project") != coordinate["project"]:
        _fail("run project does not match scenario")
    task_ids = run.get("taskIds")
    if not isinstance(task_ids, list) or coordinate["task_id"] not in task_ids:
        _fail("selected run does not reference selected task")

    task_relative_path = (
        Path("workspaces") / "projects" / f"{coordinate['project']}-lead" / "TASK_LIST.json"
    )
    task_path, task_relative = _derived_path(home, task_relative_path, "task list")
    tasks_doc = _read_json(task_path, "task list")
    if not isinstance(tasks_doc, dict):
        _fail("task list must be an object")
    task = _find_unique(tasks_doc.get("tasks"), "id", coordinate["task_id"], "tasks")

    session_relative_path = (
        Path("sessions") / quote(coordinate["session_key"], safe="") / "session.json"
    )
    session_path, session_relative = _derived_path(home, session_relative_path, "session")
    session = _read_json(session_path, "session")
    if not isinstance(session, dict) or session.get("sessionKey") != coordinate["session_key"]:
        _fail("session record identity does not match scenario")
    usage = session.get("usage")
    if not isinstance(usage, dict):
        _fail("session usage must be an object")
    input_tokens = _expect_int(usage.get("inputTokens"), "session.usage.inputTokens")
    output_tokens = _expect_int(usage.get("outputTokens"), "session.usage.outputTokens")

    trace, trace_relative = _trace_evidence(
        home, coordinate["project"], coordinate["session_key"], coordinate["task_id"]
    )
    audit, audit_relative = _load_audit(home)
    policy_denials, policy_locators = _policy_denials(audit, coordinate["project"], audit_relative)
    approval_latency, approval_locators, approval_tokens = _approval_latency(
        home,
        audit,
        audit_relative,
        coordinate["project"],
        coordinate["task_id"],
    )
    recovery, recovery_locator = _recovery(home, coordinate, task, trace)
    hops = task.get("hops")
    completed = run.get("state") == "succeeded" and task.get("status") == "done"

    attempt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "attempt",
        "attempt_id": _attempt_identity(scenario, coordinate["ordinal"]),
        "scenario": {
            "id": scenario["scenario_id"],
            "version": scenario["scenario_version"],
            "seed": scenario["seed"],
        },
        "source": scenario["source"],
        "runtime": scenario["runtime"],
        "measurement_class": scenario["measurement_class"],
        "attempt_ordinal": coordinate["ordinal"],
        "attempts": _attempts(hops),
        "completed": completed,
        "usage": {
            "basis": "provider_reported",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "tool_calls": {"total": trace["tool_total"], "executed": trace["tool_executed"]},
        "prevented_policy_violations": trace["guardrail_blocks"] + policy_denials,
        "approval_latency_ms": approval_latency,
        "recovery": recovery,
        "handoff_failures": _handoff_failures(hops, "task.hops"),
        "stop_reason": _stop_reason(run, task, trace),
        "cost": coordinate["cost"],
        "locators": {
            "run": f"{run_relative}#{coordinate['run_id']}",
            "task": f"{task_relative}#{coordinate['task_id']}",
            "session": session_relative,
            "trace": trace_relative,
            "audit": sorted(
                set(policy_locators + approval_locators),
                key=lambda item: int(item.rsplit("=", 1)[1]),
            ),
            "recovery_snapshot": recovery_locator,
        },
    }
    _validate_attempt_record(attempt)
    _assert_private(_canonical(attempt), home, approval_tokens)
    return attempt


def _validate_attempt_record(value: object) -> dict[str, Any]:
    record = _expect_object(value, _ATTEMPT_KEYS, "attempt record")
    if record["schema_version"] != SCHEMA_VERSION or record["record_type"] != "attempt":
        _fail("attempt record has an unsupported type/version")
    attempt_id = _expect_string(record["attempt_id"], "attempt.attempt_id")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", attempt_id):
        _fail("attempt.attempt_id is not a SHA-256 identifier")
    scenario = _expect_object(record["scenario"], _SCENARIO_COORDINATE_KEYS, "attempt.scenario")
    _expect_safe_id(scenario["id"], "attempt.scenario.id")
    _expect_safe_id(scenario["version"], "attempt.scenario.version")
    _expect_int(scenario["seed"], "attempt.scenario.seed")
    _validate_source(record["source"], "attempt.source")
    _validate_runtime(record["runtime"], "attempt.runtime")
    if record["measurement_class"] not in {"deterministic", "live"}:
        _fail("attempt.measurement_class is invalid")
    _expect_int(record["attempt_ordinal"], "attempt.attempt_ordinal", minimum=1)
    _expect_int(record["attempts"], "attempt.attempts", minimum=1)
    _expect_bool(record["completed"], "attempt.completed")
    usage = _expect_object(record["usage"], _USAGE_KEYS, "attempt.usage")
    if usage["basis"] != "provider_reported":
        _fail("attempt.usage.basis must be provider_reported")
    input_tokens = _expect_int(usage["input_tokens"], "attempt.usage.input_tokens")
    output_tokens = _expect_int(usage["output_tokens"], "attempt.usage.output_tokens")
    total_tokens = _expect_int(usage["total_tokens"], "attempt.usage.total_tokens")
    if total_tokens != input_tokens + output_tokens:
        _fail("attempt.usage.total_tokens does not equal input + output")
    tools = _expect_object(record["tool_calls"], _TOOL_COUNT_KEYS, "attempt.tool_calls")
    total_tools = _expect_int(tools["total"], "attempt.tool_calls.total")
    executed_tools = _expect_int(tools["executed"], "attempt.tool_calls.executed")
    if executed_tools > total_tools:
        _fail("attempt executed tool count exceeds total")
    _expect_int(record["prevented_policy_violations"], "attempt.prevented_policy_violations")
    latency = record["approval_latency_ms"]
    if latency is not None:
        _expect_int(latency, "attempt.approval_latency_ms")
    recovery = _expect_object(record["recovery"], _RECOVERY_KEYS, "attempt.recovery")
    stale = _expect_bool(recovery["stale_claim_observed"], "attempt.recovery.stale_claim_observed")
    retained = _expect_int(recovery["retained_hops"], "attempt.recovery.retained_hops")
    resumed = _expect_bool(recovery["resumed_to_terminal"], "attempt.recovery.resumed_to_terminal")
    if (stale or resumed) != (retained > 0) or stale != resumed:
        _fail("attempt recovery fields are inconsistent")
    _expect_int(record["handoff_failures"], "attempt.handoff_failures")
    if record["stop_reason"] not in _STOP_REASONS:
        _fail("attempt.stop_reason is invalid")
    _validate_cost(record["cost"], "attempt.cost")
    locators = _expect_object(record["locators"], _LOCATOR_KEYS, "attempt.locators")
    for key in ("run", "task", "session", "trace"):
        locator = _expect_string(locators[key], f"attempt.locators.{key}")
        if Path(locator.split("#", 1)[0]).is_absolute() or ".." in Path(locator).parts:
            _fail(f"attempt.locators.{key} is not relative")
    if locators["recovery_snapshot"] is not None:
        _expect_string(locators["recovery_snapshot"], "attempt.locators.recovery_snapshot")
    audit = locators["audit"]
    if not isinstance(audit, list) or not all(isinstance(item, str) for item in audit):
        _fail("attempt.locators.audit must be an array of strings")
    return record


def _aggregate(records: list[dict[str, Any]], jsonl_bytes: bytes) -> dict[str, Any]:
    if not records:
        _fail("cannot aggregate zero attempt records")
    validated = [_validate_attempt_record(record) for record in records]
    ordinals = [int(record["attempt_ordinal"]) for record in validated]
    if ordinals != sorted(ordinals) or len(set(ordinals)) != len(ordinals):
        _fail("attempt records must have unique ascending ordinals")
    ids = [str(record["attempt_id"]) for record in validated]
    if len(set(ids)) != len(ids):
        _fail("duplicate attempt id")
    first = validated[0]
    for record in validated[1:]:
        for key in ("scenario", "source", "runtime", "measurement_class"):
            if _canonical(record[key]) != _canonical(first[key]):
                _fail(f"attempt records mix {key} provenance")
    identity_scenario = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": first["scenario"]["id"],
        "scenario_version": first["scenario"]["version"],
        "seed": first["scenario"]["seed"],
        "measurement_class": first["measurement_class"],
        "source": first["source"],
        "runtime": first["runtime"],
    }
    for record in validated:
        expected = _attempt_identity(identity_scenario, int(record["attempt_ordinal"]))
        if record["attempt_id"] != expected:
            _fail("attempt id does not match normalized provenance")

    count = len(validated)
    completions = sum(int(record["completed"]) for record in validated)
    priced = [record["cost"] for record in validated if record["cost"] is not None]
    aggregate_cost: dict[str, Any] | None = None
    if len(priced) == count:
        pricing = priced[0]["pricing"]
        if any(_canonical(cost["pricing"]) != _canonical(pricing) for cost in priced[1:]):
            _fail("priced attempts use mixed pricing provenance")
        total = sum((Decimal(cost["usd"]) for cost in priced), Decimal("0"))
        aggregate_cost = {
            "usd": f"{total:.6f}",
            "estimate": True,
            "pricing": pricing,
        }
    latencies = [
        int(record["approval_latency_ms"])
        for record in validated
        if record["approval_latency_ms"] is not None
    ]
    stop_reasons: dict[str, int] = {}
    for record in validated:
        reason = str(record["stop_reason"])
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
    aggregate_identity = {
        "attempt_ids": ids,
        "measurement_class": first["measurement_class"],
        "runtime": first["runtime"],
        "scenario": first["scenario"],
        "source": first["source"],
    }
    aggregate: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "aggregate",
        "aggregate_id": "sha256:" + _sha256(_canonical(aggregate_identity)),
        "jsonl_sha256": _sha256(jsonl_bytes),
        "scenario": first["scenario"],
        "source": first["source"],
        "runtime": first["runtime"],
        "measurement_class": first["measurement_class"],
        "attempts": count,
        "completions": completions,
        "completion_rate": {"numerator": completions, "denominator": count},
        "usage": {
            "basis": "provider_reported",
            "input_tokens": sum(int(record["usage"]["input_tokens"]) for record in validated),
            "output_tokens": sum(int(record["usage"]["output_tokens"]) for record in validated),
            "total_tokens": sum(int(record["usage"]["total_tokens"]) for record in validated),
        },
        "tool_calls": {
            "total": sum(int(record["tool_calls"]["total"]) for record in validated),
            "executed": sum(int(record["tool_calls"]["executed"]) for record in validated),
        },
        "prevented_policy_violations": sum(
            int(record["prevented_policy_violations"]) for record in validated
        ),
        "approval_latency_ms": {"observed": len(latencies), "total": sum(latencies)},
        "recovery": {
            "attempted": sum(
                int(record["recovery"]["stale_claim_observed"]) for record in validated
            ),
            "resumed_to_terminal": sum(
                int(record["recovery"]["resumed_to_terminal"]) for record in validated
            ),
        },
        "handoff_failures": sum(int(record["handoff_failures"]) for record in validated),
        "stop_reasons": {key: stop_reasons[key] for key in sorted(stop_reasons)},
        "cost": aggregate_cost,
    }
    _validate_aggregate(aggregate)
    return aggregate


def _validate_aggregate(value: object) -> dict[str, Any]:
    aggregate = _expect_object(value, _AGGREGATE_KEYS, "aggregate")
    if aggregate["schema_version"] != SCHEMA_VERSION or aggregate["record_type"] != "aggregate":
        _fail("aggregate has an unsupported type/version")
    for key in ("aggregate_id",):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", _expect_string(aggregate[key], key)):
            _fail(f"aggregate.{key} is invalid")
    if not _HEX_64.fullmatch(_expect_string(aggregate["jsonl_sha256"], "jsonl_sha256")):
        _fail("aggregate.jsonl_sha256 is invalid")
    _expect_object(aggregate["scenario"], _SCENARIO_COORDINATE_KEYS, "aggregate.scenario")
    _validate_source(aggregate["source"], "aggregate.source")
    _validate_runtime(aggregate["runtime"], "aggregate.runtime")
    if aggregate["measurement_class"] not in {"deterministic", "live"}:
        _fail("aggregate.measurement_class is invalid")
    attempts = _expect_int(aggregate["attempts"], "aggregate.attempts", minimum=1)
    completions = _expect_int(aggregate["completions"], "aggregate.completions")
    if completions > attempts:
        _fail("aggregate completions exceed attempts")
    rate = _expect_object(
        aggregate["completion_rate"], {"numerator", "denominator"}, "completion_rate"
    )
    if rate != {"numerator": completions, "denominator": attempts}:
        _fail("aggregate completion rate is inconsistent")
    usage = _expect_object(aggregate["usage"], _USAGE_KEYS, "aggregate.usage")
    if usage["basis"] != "provider_reported":
        _fail("aggregate usage basis is invalid")
    input_tokens = _expect_int(usage["input_tokens"], "aggregate.usage.input_tokens")
    output_tokens = _expect_int(usage["output_tokens"], "aggregate.usage.output_tokens")
    if _expect_int(usage["total_tokens"], "aggregate.usage.total_tokens") != (
        input_tokens + output_tokens
    ):
        _fail("aggregate token total is inconsistent")
    tools = _expect_object(aggregate["tool_calls"], _TOOL_COUNT_KEYS, "aggregate.tool_calls")
    if _expect_int(tools["executed"], "aggregate.tool_calls.executed") > _expect_int(
        tools["total"], "aggregate.tool_calls.total"
    ):
        _fail("aggregate executed tool calls exceed total")
    _expect_int(aggregate["prevented_policy_violations"], "prevented_policy_violations")
    latency = _expect_object(
        aggregate["approval_latency_ms"], {"observed", "total"}, "approval_latency_ms"
    )
    _expect_int(latency["observed"], "approval_latency_ms.observed")
    _expect_int(latency["total"], "approval_latency_ms.total")
    recovery = _expect_object(
        aggregate["recovery"], {"attempted", "resumed_to_terminal"}, "aggregate.recovery"
    )
    attempted = _expect_int(recovery["attempted"], "aggregate.recovery.attempted")
    resumed = _expect_int(recovery["resumed_to_terminal"], "aggregate.recovery.resumed_to_terminal")
    if resumed > attempted or attempted > attempts:
        _fail("aggregate recovery counts are inconsistent")
    _expect_int(aggregate["handoff_failures"], "aggregate.handoff_failures")
    stop_reasons = aggregate["stop_reasons"]
    if not isinstance(stop_reasons, dict) or not stop_reasons:
        _fail("aggregate.stop_reasons must be a non-empty object")
    if any(key not in _STOP_REASONS for key in stop_reasons):
        _fail("aggregate.stop_reasons contains an unknown reason")
    if (
        sum(_expect_int(value, f"stop_reasons.{key}") for key, value in stop_reasons.items())
        != attempts
    ):
        _fail("aggregate stop reason counts do not equal attempts")
    _validate_cost(aggregate["cost"], "aggregate.cost")
    return aggregate


def _assert_private(payload: bytes, home: Path, approval_tokens: list[str]) -> None:
    text = payload.decode("utf-8")
    forbidden = [str(home), "/home/", "\\Users\\", *approval_tokens]
    for value in forbidden:
        if value and value in text:
            _fail("normalized output contains private path or approval identity")
    if _SECRET.search(text):
        _fail("normalized output contains secret-shaped text")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def run_scenario(scenario_path: Path, home: Path, jsonl_path: Path, aggregate_path: Path) -> None:
    if jsonl_path.resolve() == aggregate_path.resolve():
        _fail("JSONL and aggregate outputs must be different files")
    resolved_home = home.resolve(strict=True)
    if not resolved_home.is_dir():
        _fail("Docket home is not a directory")
    scenario = _validate_scenario(_read_json(scenario_path, "scenario"))
    records = [_build_attempt(resolved_home, scenario, item) for item in scenario["attempts"]]
    jsonl_bytes = b"".join(_canonical(record) + b"\n" for record in records)
    aggregate = _aggregate(records, jsonl_bytes)
    aggregate_bytes = _canonical(aggregate) + b"\n"
    _assert_private(jsonl_bytes + aggregate_bytes, resolved_home, [])
    # All parsing, joins, validation, aggregation, and privacy checks complete before either prior
    # output is replaced. Invalid input is therefore a two-file no-op.
    _atomic_write(jsonl_path, jsonl_bytes)
    _atomic_write(aggregate_path, aggregate_bytes)


def aggregate_jsonl(jsonl_path: Path, aggregate_path: Path) -> None:
    if jsonl_path.resolve() == aggregate_path.resolve():
        _fail("JSONL input and aggregate output must be different files")
    raw = _read_bytes(jsonl_path, "attempt JSONL")
    records = _read_jsonl(jsonl_path, "attempt JSONL")
    canonical = b"".join(_canonical(record) + b"\n" for record in records)
    if raw != canonical:
        _fail("attempt JSONL is not in canonical form")
    aggregate = _aggregate(records, raw)
    payload = _canonical(aggregate) + b"\n"
    _assert_private(payload, Path("/__no_home__"), [])
    _atomic_write(aggregate_path, payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="normalize one scenario and its durable records")
    run.add_argument("--scenario", type=Path, required=True)
    run.add_argument("--docket-home", type=Path, required=True)
    run.add_argument("--jsonl", type=Path, required=True)
    run.add_argument("--aggregate", type=Path, required=True)
    aggregate = subparsers.add_parser("aggregate", help="rebuild an aggregate from JSONL alone")
    aggregate.add_argument("--jsonl", type=Path, required=True)
    aggregate.add_argument("--aggregate", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            run_scenario(args.scenario, args.docket_home, args.jsonl, args.aggregate)
        else:
            aggregate_jsonl(args.jsonl, args.aggregate)
    except BenchmarkError as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
