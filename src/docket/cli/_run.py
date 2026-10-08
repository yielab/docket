"""The run command: drive a pod's pending tasks through its pipeline."""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from typing import Any, Literal

import typer
from rich.markup import escape

from docket import ui
from docket.cli import _contract, _progress
from docket.cli._setup import readiness
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import archetypes as _arch
from docket.core import config_docs as _config_docs
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models as _models
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod_core
from docket.core.audit import audit_log


def _parse_vars(values: list[str]) -> dict[str, str]:
    """``key=value`` strings as a mapping; a malformed one exits 2 naming it."""
    out: dict[str, str] = {}
    for raw in values:
        key, sep, value = raw.partition("=")
        if not sep or not key.strip():
            ui.error(f"--var {raw!r} is not key=value", "Pass --var key=value")
            raise typer.Exit(2)
        out[key.strip()] = value
    return out


def _load_spec(path: Path) -> _pipeline.PipelineSpec:
    """Load and validate a pipeline file; any problem exits 1."""
    try:
        _config_docs.load_document(path, kind="pipeline")
    except _config_docs.ConfigDocError as exc:
        ui.error(f"Pipeline file is invalid: {exc}", f"Check it with docket pod validate {path}")
        raise typer.Exit(1) from exc
    result = _pipeline.load_pipeline(path.read_text(encoding="utf-8"))
    if result.spec is None or result.errors:
        for err in result.errors:
            ui.fail(f"  {err}")
        ui.error("Pipeline file is invalid", f"Check it with docket pod validate {path}")
        raise typer.Exit(1)
    return result.spec


def _plan_roles(plan: _orch.ExecutionPlan) -> str:
    """The runnable steps of *plan* as ``role -> role``; a parallel group reads ``(a | b)``."""
    parts: list[str] = []
    for node in plan.runnable_nodes():
        if isinstance(node, _orch.PlannedGroup):
            parts.append(
                "(" + " | ".join(c.role or c.agent or c.step_id for c in node.children) + ")"
            )
        else:
            parts.append(node.role or node.agent or node.step_id)
    return " → ".join(parts)


def _pod_tokens(project: str) -> tuple[int, float]:
    """The pod's measured tokens so far and its labelled cost estimate."""
    from docket.core.utils import aggregate_cost

    ids = [a.id for a in _fleet.list_agents()]
    tokens = 0
    for mid, _role, _idx in _pod_core.members_of(ids, project):
        totals = aggregate_cost(mid)
        tokens += totals.input_tokens + totals.output_tokens
    cost, _estimated = _dispatch.pod_gating_cost(project)
    return tokens, cost


def _tokens_label(n: int) -> str:
    return str(n) if n < 1000 else f"{n / 1000:.1f}k"


def _clear_pause(project: str) -> None:
    """``--resume``: clear the Lead's auto-pause and un-block the pod's budget-blocked tasks."""
    lead = _pod_core.member_id(project, "lead")
    if _models.AgentMeta.coerce_paused(_fleet.meta_get(lead, "paused", "")):
        _fleet.meta_set(lead, "paused", False)
        _fleet.meta_set(lead, "pausedReason", "")
        audit_log("run.resume", f"pod={project}")
    unblocked = _dispatch.unblock_pod(project)
    if unblocked:
        ui.info(f"Unblocked {unblocked} budget-blocked task(s) in pod '{project}'")


def _flush_notify_after_dispatch() -> None:
    """One notify flush over every channel after the run summary.

    Silent unless a delivery failed or nothing beyond the console delivers."""
    from docket.core import channel as _channel
    from docket.core import notify as _notify
    from docket.edges.adapters import channels as _channels

    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = _notify.flush(
        list(_channel.load_catalog().entries.values()), _channels.sink_for, now=now
    )
    if report.failed:
        ui.warn(f"  notify: {report.failed} delivery failure(s) — see channels-health.json")
    if report.events:
        unreached = _channel.unreached_warning(_channel.load_catalog().delivering())
        if unreached:
            ui.warn(f"  {unreached}")


def _render_result(res: Any) -> None:
    """One line per task; ids and model-written reasons are data, never Rich markup."""
    for hop in res.hops:
        if hop.verification_skipped:
            ui.dim(escape(f"verification skipped — verifyCmd not set for {hop.member_id}"))
    if res.status == "done":
        ui.success(escape(f"  [{res.task_id}] done — {len(res.hops)} hop(s)"))
    elif res.status == "blocked" or res.status in ("waiting_approval", "waiting_input"):
        ui.warn(escape(f"  [{res.task_id}] {res.status} — {res.reason}"))
    else:
        ui.fail(escape(f"  [{res.task_id}] {res.status} — {res.reason}"))


def _summary(results: list[Any], tokens: int, cost: float) -> None:
    done = sum(1 for r in results if r.status == "done")
    waiting = sum(1 for r in results if r.status in ("waiting_approval", "waiting_input"))
    blocked = sum(1 for r in results if r.status == "blocked")
    failed = len(results) - done - waiting - blocked
    parts = [f"{done} done", f"{failed} failed"]
    if waiting:
        parts.append(f"{waiting} waiting")
    if blocked:
        parts.append(f"{blocked} blocked")
    parts.append(f"{_tokens_label(tokens)} tokens (~${cost:.2f} est.)")
    line = " · ".join(parts)
    (ui.fail if failed else ui.success)(line)
    _contract.next_step("docket inbox" if (failed or waiting or blocked) else "docket status")


def _pod_dispatch(
    project: str,
    *,
    resume: bool = False,
    timeout: int | None = None,
    progress: bool = False,
    no_prompt: bool = False,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, str] | None = None,
) -> None:
    """Drive the pod's pending tasks through the pipeline, one real turn per hop.

    Recorded in the run registry (source ``cli``), so a failure shows in ``docket log``."""
    from docket.core import runs as _runs

    try:
        _dispatch.pod_pipeline(project)
        effective = spec if spec is not None else _dispatch.effective_pipeline(project, None)
        plan = _orch.resolve_plan(
            effective, _dispatch.pod_full_roster(project), registry=_arch.load_registry()
        )
        cap = _dispatch.pod_budget(project)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if resume:
        _clear_pause(project)
    tasks = _dispatch.read_tasks(project)
    pending = [t for t in tasks if t.get("status") == "pending"]
    resumable = [
        t
        for t in tasks
        if resume
        and t.get("status") == "failed"
        and t.get("failureKind") in _dispatch.RESUMABLE_FAILURE_KINDS
    ]
    # A crashed dispatcher leaves a task ``running``; dispatch_pod's own stale-claim sweep
    # judges whether its claim is stale, so under --resume a running task is enough to enter.
    running = [t for t in tasks if resume and t.get("status") == "running"]
    if not pending and not resumable and not running:
        ui.warn(
            f"No pending tasks in pod '{project}'. Queue one: docket task add \"<description>\""
        )
        return
    count = f"{len(pending)} pending"
    if resume:
        count += f", {len(resumable)} resumable"
        if running:
            count += f", {len(running)} running (reclaimed only if the claim is stale)"
    ui.info(f"Running {count} task(s) through: {_plan_roles(plan)}")
    if cap:
        ui.dim(f"  Pod budget cap: ${cap:.2f} (spent ${_dispatch.pod_recorded_cost(project):.2f})")

    record = _runs.create_run("cli", project)
    tokens_before, cost_before = _pod_tokens(project)

    def _fn() -> list[Any]:
        default: Literal["wait", "park"] = "wait" if sys.stdin.isatty() else "park"
        return _dispatch.dispatch_pod(
            project,
            resume=resume,
            turn_timeout=timeout,
            verify_timeout=timeout,
            spec=spec,
            variables=variables,
            approval_default=default,
        )

    if _progress.should_render(progress_flag=progress):
        results = _progress.dispatch_with_progress(
            record["id"],
            _fn,
            prompt=_progress.should_prompt(no_prompt_flag=no_prompt, render=True),
        )
    else:
        results = _runs.execute(record["id"], _fn)
    if results is None:
        failed_run = _runs.get_run(record["id"])
        error = str(failed_run.get("error", "")) if failed_run else ""
        ui.error(f"Run failed: {error}", f"See docket log for run {record['id']}")
        raise typer.Exit(1)
    for res in results:
        _render_result(res)
    tokens_after, cost_after = _pod_tokens(project)
    _summary(results, max(tokens_after - tokens_before, 0), max(cost_after - cost_before, 0.0))
    _flush_notify_after_dispatch()
    final = _runs.get_run(record["id"])
    if final is not None and final.get("state") == "failed":
        raise typer.Exit(1)


def cmd_run(
    resume: bool = typer.Option(
        False, "--resume", help="Reclaim stale claims and clear a budget auto-pause"
    ),
    timeout: int | None = typer.Option(
        None, "--timeout", min=1, help="Agent-turn and verifyCmd timeout in seconds"
    ),
    progress: bool = typer.Option(False, "--progress", help="Show hop progress on stderr"),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Never ask for approval in place"),
    pipeline: Path | None = typer.Option(
        None,
        "--pipeline",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Run this pipeline file instead of the pod's own",
    ),
    var: list[str] = typer.Option(
        [], "--var", help="Pipeline variable key=value; repeat for several"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan and start nothing"),
    pod: str | None = pod_option(),
) -> None:
    """Run the pod's pending tasks through its pipeline, one real agent turn per hop.

    Each task is claimed before its first hop and every hop is saved as it finishes, so a
    crash loses at most the hop in flight. --dry-run prints the plan the executor would
    follow and starts nothing; --resume reclaims stale claims and clears a budget pause.

    Example: docket run --dry-run
    """
    import os

    try:
        project = resolve_pod(pod, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    variables = _parse_vars(var)
    spec = _load_spec(pipeline) if pipeline is not None else None
    if dry_run:
        _dry_run(project, spec)
        return
    piece = readiness().endpoint
    if not piece.ok:
        ui.error("No model endpoint yet", "Run docket setup")
        raise typer.Exit(1)
    _pod_dispatch(
        project,
        resume=resume,
        timeout=timeout,
        progress=progress,
        no_prompt=no_prompt,
        spec=spec,
        variables=variables or None,
    )


def _dry_run(project: str, spec: _pipeline.PipelineSpec | None) -> None:
    """Print the plan the executor renders for *project*; nothing is claimed or recorded."""
    try:
        _dispatch.pod_pipeline(project)
        effective = spec if spec is not None else _dispatch.effective_pipeline(project, None)
        plan = _orch.resolve_plan(
            effective, _dispatch.pod_full_roster(project), registry=_arch.load_registry()
        )
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    pending = sum(1 for t in _dispatch.read_tasks(project) if t.get("status") == "pending")
    ui.header("Run plan", project)
    ui.console.print()
    ui.console.print(_orch.render_plan(plan), markup=False)
    ui.console.print()
    ui.dim(f"  {pending} pending task(s) would run; nothing was started")
