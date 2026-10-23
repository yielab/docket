"""The run command: drive a pod's pending tasks through its pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import typer
from rich.markup import escape

from docket.governance.audit import audit_log
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.setup import readiness
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import progress as _progress
from docket.interfaces.cli.render import ui
from docket.kernel import clock as _clock
from docket.pipeline.application import steps as _steps
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import config_docs as _config_docs
from docket.teams import fleet as _fleet
from docket.teams import models as _models
from docket.teams import pod as _pod_core
from docket.teams import report as _report
from docket.teams import roles as _arch
from docket.teams import settings as _settings
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import review as _review
from docket.teams.apply import write as _write


def _repo_dir(project: str) -> Path | None:
    """The configuration-of-record directory of *project*'s Lead, or None with no codebase."""
    codebase = _fleet.meta_get(_pod_core.member_id(project, "lead"), "codebase", "")
    return _review.repo_config_dir(Path(codebase), project) if codebase else None


def _ask_changed_commands(changes: _pod_apply.RepoChanges) -> bool:
    """Show before/now for each changed command and ask; off a terminal warn and say no."""
    from docket.interfaces.cli.commands.pod_config import run_item_label

    when = f" on {changes.allowed_on}" if changes.allowed_on else ""
    if not _contract.is_tty():
        ui.warn(
            "The repository changed a command that needs your OK. Running with the version "
            f"you allowed{when}. To review it, run docket run on a terminal."
        )
        return False
    ui.console.print(f"The repository changed a command since you allowed it{when}:")
    for change in changes.runs_changed:
        ui.console.print(f"  {escape(run_item_label(change.item))}")
        ui.console.print(f"    before: {escape(change.before or '(not allowed before)')}")
        ui.console.print(f"    now:    {escape(change.item.runs)}")
    if input("Allow the new version? [y/N] ").strip().lower() in ("y", "yes"):
        return True
    ui.info(f"Running with the version you allowed{when}.")
    return False


def _pick_up_repository(project: str) -> None:
    """Apply what the pod's repository changed in ``.docket/`` since the last apply; a changed
    command needs the operator's OK, else the pod keeps the version it has."""
    from docket.governance import review as _reviewed

    directory = _repo_dir(project)
    if directory is None:
        return
    try:
        changes = _pod_apply.repo_changes(project, directory)
    except _model.PodApplyError as exc:
        ui.warn(f"The repository's .docket/ was not applied: {exc}. Running with the pod as it is.")
        return
    if changes is None:
        return
    if changes.review.refused:
        ui.warn(
            f"The repository lets the agent run {', '.join(changes.review.refused)}, which is "
            "never applied. Running with the pod as it is."
        )
        return
    if changes.runs_changed and not _ask_changed_commands(changes):
        return
    if changes.review.runs and (changes.runs_changed or changes.allowed_on):
        _reviewed.remember(_review.repo_root(directory), project, changes.review.runs)
    _write.apply(changes.plan)
    if changes.adds_changed:
        ui.info(f"Updated from the repository: {', '.join(changes.adds_changed)}.")


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
    from docket.teams.utils import aggregate_cost

    ids = [a.id for a in _fleet.list_agents()]
    tokens = 0
    for mid, _role, _idx in _pod_core.members_of(ids, project):
        totals = aggregate_cost(mid)
        tokens += totals.input_tokens + totals.output_tokens
    cost, _estimated = _pre_hop.pod_gating_cost(project)
    return tokens, cost


def _tokens_label(n: int) -> str:
    return str(n) if n < 1000 else f"{n / 1000:.1f}k"


def _clear_pause(project: str) -> None:
    """``--resume``: clear the Lead's auto-pause and un-block the pod's blocked tasks."""
    lead = _pod_core.member_id(project, "lead")
    if _models.AgentMeta.coerce_paused(_fleet.meta_get(lead, "paused", "")):
        _fleet.meta_set(lead, "paused", False)
        _fleet.meta_set(lead, "pausedReason", "")
        audit_log("run.resume", f"pod={project}")
    unblocked = _lifecycle.unblock_pod(project)
    if unblocked:
        ui.info(f"Unblocked {unblocked} blocked task(s) in pod '{project}'")


def _flush_notify_after_dispatch() -> None:
    """One notify flush over every channel after the run summary.

    Silent unless a delivery failed or nothing beyond the console delivers."""
    from docket.operator import adapters as _channels
    from docket.operator import channel as _channel
    from docket.operator import notify as _notify

    now = _clock.stamp()
    report = _notify.flush(
        list(_channel.load_catalog().entries.values()), _channels.sink_for, now=now
    )
    if report.error:
        ui.warn(escape(f"  notify: {report.error}"))
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


def _cap_progress(project: str) -> str:
    """How far the pod is toward its cap, as the gate counts it: the labelled estimate, since
    the driver records no cost; a recorded figure only if one ever exists."""
    amount, estimated = _pre_hop.pod_gating_cost(project)
    if amount > 0 and not estimated:
        return f"recorded ${amount:.2f}"
    return f"estimate so far ~${amount:.2f}, no cost recorded"


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
    from docket.tasks.application import runs as _runs

    try:
        _steps.pod_pipeline(project)
        effective = spec if spec is not None else _steps.effective_pipeline(project, None)
        plan = _orch.resolve_plan(
            effective, _queue.pod_full_roster(project), registry=_arch.load_registry(project)
        )
        cap = _settings.pod_budget(project)
    except _task.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if resume:
        _clear_pause(project)
    tasks = _queue.read_tasks(project)
    pending = [t for t in tasks if t.get("status") == "pending"]
    resumable = [
        t
        for t in tasks
        if resume
        and t.get("status") == "failed"
        and t.get("failureKind") in _queue.RESUMABLE_FAILURE_KINDS
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
        ui.dim(f"  Pod budget cap: ${cap:.2f} ({_cap_progress(project)})")

    record = _runs.create_run("cli", project)
    tokens_before, cost_before = _pod_tokens(project)

    def _fn() -> list[Any]:
        default: Literal["wait", "park"] = _report.caller_default()
        return _sweep.dispatch_pod(
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

    project = _contract.require_pod(pod)
    variables = _parse_vars(var)
    spec = _load_spec(pipeline) if pipeline is not None else None
    if dry_run:
        _dry_run(project, spec)
        return
    piece = readiness().endpoint
    if not piece.ok:
        ui.error("No model endpoint yet", "Run docket setup")
        raise typer.Exit(1)
    _pick_up_repository(project)
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
        _steps.pod_pipeline(project)
        effective = spec if spec is not None else _steps.effective_pipeline(project, None)
        plan = _orch.resolve_plan(
            effective, _queue.pod_full_roster(project), registry=_arch.load_registry(project)
        )
    except _task.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    pending = sum(1 for t in _queue.read_tasks(project) if t.get("status") == "pending")
    ui.header("Run plan", project)
    ui.console.print()
    ui.console.print(_orch.render_plan(plan), markup=False)
    ui.console.print()
    ui.dim(f"  {pending} pending task(s) would run; nothing was started")
