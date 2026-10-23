from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from rich.markup import escape

from docket.interfaces.cli.render import ui
from docket.kernel.ports import git as _git
from docket.observability import trace as _trace
from docket.tasks.application import evidence as _evidence
from docket.tasks.application import interruptions as _interruptions
from docket.tasks.application import runs as _runs
from docket.tasks.domain.refs import TaskRef, short_id
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import report as _report


def _say(text: str) -> None:
    ui.console.print(text, markup=False)


def _pod_codebase(project: str) -> str:
    return str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")


def _worktree(project: str, task: dict[str, Any]) -> dict[str, str] | None:
    """The task's worktree record when it has a directory that was not pruned."""
    record = task.get("worktree")
    if not isinstance(record, dict) or not record.get("dir") or record.get("prunedAt"):
        return None
    path = str(record["dir"])
    base = str(record.get("baseCommit") or "")
    branch = str(record.get("branch") or "")
    codebase = str(_pod_codebase(project) or "")
    root = f"git -C {codebase} " if codebase else "git "
    git_dir, common_dir = str(record.get("gitDir") or ""), str(record.get("commonDir") or "")
    _git.trust_worktree(path, git_dir, common_dir)
    where = (
        f"GIT_DIR={git_dir} GIT_COMMON_DIR={common_dir} GIT_WORK_TREE={path} git"
        if git_dir and common_dir
        else f"git -C {path}"
    )
    return {
        "path": path,
        "branch": branch,
        "baseCommit": base,
        "diff": f"{where} diff {base}",
        "merge": f"{root}merge {branch}",
    }


def _cost_cell(task: dict[str, Any]) -> str:
    cost = task.get("costUsd")
    return f"${float(cost):.4f}" if cost else "-"


def _list_item(project: str, task: dict[str, Any]) -> dict[str, Any]:
    wt = _worktree(project, task)
    cost = task.get("costUsd")
    return {
        "id": str(task.get("id", "")),
        "priority": str(task.get("priority", "normal")),
        "status": str(task.get("status", "")),
        "costUsd": float(cost) if cost else None,
        "description": str(task.get("description", "")),
        "worktree": wt["path"] if wt else None,
    }


def _hop_rows(ev: _evidence.TaskEvidence) -> list[list[str]]:
    return [
        [
            hop.step_id,
            hop.role,
            "yes" if hop.ok else "no",
            hop.verdict or "-",
            str(hop.verify.exit_code) if hop.verify else "-",
            hop.commit[:8] if hop.commit else "-",
            str(hop.usage.input) if hop.usage else "-",
            str(hop.usage.output) if hop.usage else "-",
        ]
        for hop in ev.hops
    ]


def _run_lines(run_ids: tuple[str, ...]) -> list[str]:
    lines = []
    for run_id in run_ids:
        rec = _runs.get_run(run_id) or {}
        line = (
            f"{run_id}  {rec.get('state', '?')}  source={rec.get('source', '?')}  "
            f"created={str(rec.get('created', ''))[:19]}"
        )
        cancel = rec.get("cancellation")
        if isinstance(cancel, dict) and cancel.get("requestedAt"):
            stopped = cancel.get("stoppedAt") or "not yet"
            line += f"  cancel requested={cancel['requestedAt']} stopped={stopped}"
        if rec.get("error"):
            line += f"  error={rec['error']}"
        lines.append(line)
    return lines


def _render_forecast(project: str) -> None:
    items = _interruptions.forecast(project, caller_default=_report.caller_default())
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        _say(f"  {_interruptions.NOTHING_WILL_ASK}")
    for i in askers:
        _say(f"  - {i.description}")
    mode = next((i for i in items if i.kind == "mode"), None)
    if mode is not None:
        ui.dim(escape(f"  {mode.description}"))
    for label, kind in (("Always enforced:", "high_risk_class"), ("Will notify:", "channel")):
        chosen = [i for i in items if i.kind == kind]
        if chosen:
            ui.dim(f"  {label}")
            for i in chosen:
                ui.dim(escape(f"    - {i.description}"))


def _render_show(
    found: TaskRef,
    task: dict[str, Any],
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> None:
    ui.header("task", short_id(found.task_id))
    _say(f"  pod:      {found.project}")
    _say(f"  id:       {found.task_id}")
    _say(f"  status:   {task.get('status', '?')}")
    _say(f"  priority: {task.get('priority', 'normal')}")
    _say(f"  cost:     {_cost_cell(task)}")
    _say(f"  task:     {task.get('description', '')}")
    if ev.hops:
        ui.section("Hops")
        cols = ["HOP", "ROLE", "OK", "VERDICT", "VERIFY", "COMMIT", "TOKENS IN", "TOKENS OUT"]
        ui.table([[escape(c) for c in row] for row in _hop_rows(ev)], cols)
    if found.run_ids:
        ui.section("Runs")
        for line in _run_lines(found.run_ids):
            _say(f"  {line}")
    if wt is not None:
        ui.section("Worktree")
        _say(f"  path:   {wt['path']}")
        _say(f"  branch: {wt['branch']}")
        _say(f"  base:   {wt['baseCommit']}")
        _say(f"  diff:   {wt['diff']}")
        _say(f"  merge:  {wt['merge']}")
    if notes:
        ui.section("Corrections")
        for rec in notes:
            _say(f"  {str(rec.get('ts', ''))[:19]}  {rec.get('kind', '')}  {rec.get('text', '')}")
    ui.section("May ask you")
    _render_forecast(found.project)


def _show_json(
    found: TaskRef,
    task: dict[str, Any],
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    forecast = _interruptions.forecast(found.project, caller_default=_report.caller_default())
    return {
        "pod": found.project,
        "task": {**_list_item(found.project, task), "worktree": wt},
        "evidence": json.loads(ev.model_dump_json(by_alias=True)),
        "runs": [_runs.get_run(r) for r in found.run_ids],
        "corrections": notes,
        "interruptions": [
            {"kind": i.kind, "description": i.description, "detail": i.detail} for i in forecast
        ],
    }


TAIL_POLL_S = 0.5


def _event_line(r: dict[str, Any]) -> str:
    ts = str(r.get("ts", "?"))[:19]
    etype = str(r.get("event_type", "?"))
    role = str(r.get("agent_role", "") or "")
    payload = r.get("payload", {})
    parts: list[str] = []
    if etype == "llm_call" and isinstance(payload, dict):
        parts.append(str(payload.get("model") or ""))
        in_tok, out_tok = payload.get("inputTokens"), payload.get("outputTokens")
        if in_tok is not None or out_tok is not None:
            parts.append(f"in={in_tok or 0}/out={out_tok or 0}")
        if payload.get("ok") is False:
            parts.append(f"failed: {payload.get('failureKind') or 'unknown'}")
    elif isinstance(payload, dict):
        for k in ("tool", "hop", "status", "action", "text", "task_id", "pct"):
            if payload.get(k) is not None:
                parts.append(f"{k}={payload[k]}")
    extras = []
    if r.get("cost_usd") is not None:
        with contextlib.suppress(TypeError, ValueError):
            extras.append(f"${float(r['cost_usd']):.4f}")
    if r.get("duration_ms") is not None:
        extras.append(f"{r['duration_ms']}ms")
    who = f"  ({role})" if role and role != "unknown" else ""
    summary = "  " + "  ".join(p for p in parts if p) if any(parts) else ""
    tail = f"  [{'  '.join(extras)}]" if extras else ""
    return f"  {ts}  {etype:<25}{who}{summary}{tail}"


def _trace_file(found: TaskRef) -> Path:
    return _trace.project_trace_dir(found.project) / f"agent:{found.project}:{found.task_id}.jsonl"


def _follow(path: Path) -> None:
    """Print events as they are written; return once the session has ended."""
    seen = 0
    with contextlib.suppress(KeyboardInterrupt):
        while True:
            records = _trace.read_trace(path)
            for r in records[seen:]:
                _say(_event_line(r))
            seen = len(records)
            if any(r.get("event_type") == "session_end" for r in records):
                return
            time.sleep(TAIL_POLL_S)
