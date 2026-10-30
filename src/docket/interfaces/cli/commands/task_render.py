from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

from rich.markup import escape

from docket.governance.approval import approval_call
from docket.hops.application import interruptions as _interruptions
from docket.hops.application import report as _report
from docket.interfaces.cli.render import ui
from docket.interfaces.cli.render.escalation import answer_command, decision_line, options_line
from docket.kernel.operator_contract import EscalationView
from docket.kernel.ports import git as _git
from docket.observability import trace as _trace
from docket.operator import escalation_views, render_escalation
from docket.tasks.application import evidence as _evidence
from docket.tasks.application import runs as _runs
from docket.tasks.domain.refs import TaskRef, short_id
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod


def _say(text: str) -> None:
    ui.console.print(text, markup=False)


def _pod_codebase(project: str) -> str:
    return str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")


def _worktree(project: str, record: TaskRecord) -> dict[str, str] | None:
    """The task's worktree record when it has a directory that was not pruned."""
    wt = record.worktree
    path = record.worktree_dir
    if wt is None or not path:
        return None
    codebase = _pod_codebase(project)
    root = f"git -C {codebase} " if codebase else "git "
    git_dir, common_dir = wt.git_dir or "", wt.common_dir or ""
    _git.trust_worktree(path, git_dir, common_dir)
    where = (
        f"GIT_DIR={git_dir} GIT_COMMON_DIR={common_dir} GIT_WORK_TREE={path} git"
        if git_dir and common_dir
        else f"git -C {path}"
    )
    return {
        "path": path,
        "branch": wt.branch,
        "baseCommit": wt.base_commit,
        "diff": f"{where} diff {wt.base_commit}",
        "merge": f"{root}merge {wt.branch}",
    }


def _cost_cell(record: TaskRecord) -> str:
    return f"${record.cost_usd:.4f}" if record.cost_usd else "-"


def _list_item(project: str, record: TaskRecord) -> dict[str, Any]:
    wt = _worktree(project, record)
    return {
        "id": record.id,
        "priority": record.priority,
        "status": str(record.status),
        "costUsd": record.cost_usd or None,
        "description": record.description,
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


def _waiting_on(found: TaskRef) -> list[EscalationView]:
    """The escalations the task is waiting on a person for."""
    views = escalation_views(pod=found.project, task=found.task_id)
    return [v for v in views if v.state == "pending"]


def _decided_for(found: TaskRef) -> list[EscalationView]:
    """The escalations the pod settled for the task without a person."""
    views = escalation_views(pod=found.project, task=found.task_id)
    return [v for v in views if v.state == "decided"]


def _decision_lines(view: EscalationView) -> list[str]:
    """What to print under one pending escalation: its options and the commands that answer it."""
    rendered = render_escalation(view, "full")
    if view.kind in ("consult", "input"):
        listed = options_line(rendered.options)
        return ([f"    options: {listed}"] if listed else []) + [
            f"    answer:  {answer_command(view.task, rendered.options)}"
        ]
    return [
        f"    approve: docket task answer {view.id} --option approve_once",
        f"    deny:    docket task answer {view.id} --option deny",
    ]


def _render_waiting(found: TaskRef) -> None:
    views = _waiting_on(found)
    if not views:
        return
    ui.section("Waiting on you")
    for view in views:
        rendered = render_escalation(view, "full")
        prompt = (rendered.prompt or "").replace("\n", "\n    ")
        _say(f"  {rendered.title}: {prompt}")
        for line in _decision_lines(view):
            _say(line)


def _render_outward(found: TaskRef) -> None:
    """The whole call of each pending outward approval: what a person is asked to let leave."""
    shown = [(v.id, approval_call(v.id)) for v in _waiting_on(found) if v.outward]
    calls = [(esc_id, call) for esc_id, call in shown if call is not None]
    if not calls:
        return
    ui.section("What leaves")
    for esc_id, call in calls:
        _say(f"  {esc_id}:")
        _say("    " + call.replace("\n", "\n    "))


def _render_unused(found: TaskRef) -> None:
    """One line per approved call a hop ended without issuing again."""
    events = [
        r["payload"]
        for r in _trace.read_trace(_trace_file(found))
        if r.get("event_type") == "approval_unused" and isinstance(r.get("payload"), dict)
    ]
    if not events:
        return
    ui.section("Approved, not used")
    for payload in events:
        _say(
            f"  {payload.get('role', '')} was told to issue the approved {payload.get('tool', '')} "
            f"call again and did not ({payload.get('escalation', '')})"
        )


def _render_decided(found: TaskRef) -> None:
    views = _decided_for(found)
    if not views:
        return
    ui.section("Decided without you")
    for view in views:
        rendered = render_escalation(view, "full")
        prompt = (rendered.prompt or "").replace("\n", "\n    ")
        _say(f"  {rendered.title}: {prompt}")
        _say(f"    {decision_line(view)}")


def _render_show(
    found: TaskRef,
    record: TaskRecord,
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> None:
    ui.header("task", short_id(found.task_id))
    _say(f"  pod:      {found.project}")
    _say(f"  id:       {found.task_id}")
    _say(f"  status:   {record.status}")
    _say(f"  priority: {record.priority}")
    _say(f"  cost:     {_cost_cell(record)}")
    _say(f"  task:     {record.description}")
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
    _render_waiting(found)
    _render_outward(found)
    _render_unused(found)
    _render_decided(found)
    if notes:
        ui.section("Corrections")
        for rec in notes:
            _say(f"  {str(rec.get('ts', ''))[:19]}  {rec.get('kind', '')}  {rec.get('text', '')}")
    ui.section("May ask you")
    _render_forecast(found.project)


def _show_json(
    found: TaskRef,
    record: TaskRecord,
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    forecast = _interruptions.forecast(found.project, caller_default=_report.caller_default())
    decided = [v.model_dump(by_alias=True, mode="json") for v in _decided_for(found)]
    return {
        "pod": found.project,
        "task": {**_list_item(found.project, record), "worktree": wt},
        "evidence": json.loads(ev.model_dump_json(by_alias=True)),
        "runs": [_runs.get_run(r) for r in found.run_ids],
        "corrections": notes,
        "interruptions": [
            {"kind": i.kind, "description": i.description, "detail": i.detail} for i in forecast
        ],
        "escalations": [v.model_dump(by_alias=True, mode="json") for v in _waiting_on(found)],
        **({"decided": decided} if decided else {}),
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
