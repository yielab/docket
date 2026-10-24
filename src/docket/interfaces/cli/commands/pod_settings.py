from __future__ import annotations

import contextlib
import hashlib as _hashlib
from pathlib import Path

import typer

from docket.governance.audit import audit_log
from docket.interfaces.cli.commands.pod_members import _implementer_member
from docket.interfaces.cli.render import ui
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.pipeline.application import schedule as _sched
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.platform import read_json, write_json
from docket.tasks.application import lifecycle as _lifecycle
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings
from docket.teams import roles as _arch
from docket.teams.apply import recipes as _recipes


def _regenerate_member_tools(member_id: str, project: str) -> None:
    """Rewrite TOOLS.md for an existing Implementer after a meta change (e.g.
    a verify change). No-op for non-implementers, and for members with no allocated
    resources and no verify command (nothing to render)."""
    role = _fleet.meta_get(member_id, "role", "")
    if role != "implementer":
        return
    port_start_s = _fleet.meta_get(member_id, "portRangeStart", "")
    port_count_s = _fleet.meta_get(member_id, "portRangeCount", "")
    scratch = _fleet.meta_get(member_id, "scratchDir", "")
    verify_cmd = _fleet.meta_get(member_id, "verifyCmd", "")
    if not ((port_start_s and scratch) or verify_cmd):
        return
    raw_codebase = _fleet.meta_get(member_id, "codebase", "")
    codebase = pod.resolve_member_cwd(member_id, "", raw_codebase)
    content = _member_workspace._member_tools(
        project,
        role,
        codebase,
        int(port_start_s) if port_start_s else 0,
        int(port_count_s) if port_count_s else 0,
        scratch,
        verify_cmd,
    )
    ws = current_home().projects_dir / member_id
    (ws / "TOOLS.md").write_text(content, encoding="utf-8")


def _set_member_verify(project: str, member_id: str, command: str) -> None:
    """Set an implementer's verify command (validated, audited) and re-render its TOOLS.md."""
    _implementer_member(project, member_id)
    try:
        command = _pp.validate_verify_cmd(command)
    except _pp.VerifyCmdError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    _fleet.meta_set(member_id, "verifyCmd", command)
    _regenerate_member_tools(member_id, project)
    audit_log("pod.set-verify", f"member={member_id} cmd={command!r}")
    ui.success(f"Set verify command for {member_id}: {command!r}")


def _unset_member_verify(project: str, member_id: str) -> None:
    _implementer_member(project, member_id)
    raw = read_json(current_home().meta_path(member_id))
    raw.pop("verifyCmd", None)
    write_json(current_home().meta_path(member_id), raw)
    _regenerate_member_tools(member_id, project)
    audit_log("pod.unset-verify", f"member={member_id}")
    ui.success(f"Cleared the verify command for {member_id}")


def _lead_for_settings(project: str) -> str:
    """The Lead's member id, after checking the pod exists and has one."""
    try:
        pod.pod_pipeline(project)
    except DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    return pod.member_id(project, "lead")


def _budget_changed(project: str, lead_id: str) -> None:
    """A changed budget re-queues the pod's blocked tasks and lifts the budget auto-pause."""
    unblocked = _lifecycle.unblock_pod(project)
    if unblocked:
        ui.info(f"Unblocked {unblocked} blocked task(s)")
    _fleet.meta_set(lead_id, "paused", False)
    _fleet.meta_set(lead_id, "pausedReason", "")


# Persists a docket-owned copy plus its sha256 hash in the Lead's own workspace, never the
# operator's original path, which can drift or disappear -- hops/application/steps.py's
# effective_pipeline verifies the copy against this hash on every read.
def _pod_config_set_pipeline(project: str, lead_id: str, path_str: str) -> None:
    """``docket pod set pipeline <file>``: validate *path_str* and
    plan it against the pod's real roster before binding it."""
    path = Path(path_str)
    if not path.is_file():
        ui.error(f"File not found: {path_str}")
        raise typer.Exit(1)
    text = path.read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    if result.spec is None:
        ui.error(f"Pipeline '{path_str}' is invalid:")
        for e in result.errors:
            ui.console.print(f"  [red]x[/red] {e}")
        raise typer.Exit(1)

    roster = pod.pod_full_roster(project)
    registry = _arch.load_registry(project)
    plan = _orch.resolve_plan(result.spec, roster, registry=registry)
    problems = _recipes.unresolvable_pipeline_steps(plan, project)
    if problems:
        ui.error(f"Pipeline '{path_str}' targets a role/agent this pod does not have:")
        for p in problems:
            ui.console.print(f"  [red]x[/red] {p}")
        raise typer.Exit(1)

    digest = _hashlib.sha256(text.encode("utf-8")).hexdigest()
    dest = pod.bound_pipeline_path(project)
    dest.write_text(text, encoding="utf-8")
    dest.chmod(0o600)

    _fleet.meta_set(lead_id, "pipeline", digest)
    audit_log(
        "pod.config",
        f"project={project} action=set key=pipeline file={path_str} hash={digest[:12]}",
    )
    ui.success(f"Bound pipeline '{path_str}' (hash {digest[:12]}...) to pod '{project}'.")


# Two writers for one logical value, same as `pipeline` above: `docket-schedules.json`
# (`Home.schedule_file`) is this schedule's real source of truth -- it is the file
# `interfaces/http/server.py::_check_schedules` actually reads to fire a dispatch -- while the Lead's meta
# copy exists only so `config get`/`list` can report it through the same generic
# `PodSettings.value_and_source` every other setting uses, instead of a bespoke display path.
def _pod_config_set_schedule(project: str, lead_id: str, spec: str) -> None:
    """``docket pod set schedule <spec>``: validate *spec*, persist it as
    this pod's writer into ``docket-schedules.json``, and mirror it into the Lead's meta
    for display."""
    try:
        coerced = _pod_settings.PodSettings.coerce("schedule", spec)
    except _pod_settings.PodSettingsError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    try:
        _sched.set_schedule(current_home().schedule_file, project, str(coerced))
    except _sched.ScheduleError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    _fleet.meta_set(lead_id, "schedule", coerced)
    audit_log("pod.config", f"project={project} action=set key=schedule value={coerced!r}")
    ui.success(f"Set schedule={coerced} for pod '{project}'.")


def set_setting(project: str, key: str, value: str, *, member: str | None = None) -> None:
    """Set one pod setting, or with ``member`` an implementer's verify command."""
    if key == "verify" or member is not None:
        if key != "verify":
            ui.error(
                "--member applies only to verify", "Example: docket pod set verify 'make test'"
            )
            raise typer.Exit(1)
        if member is None:
            ui.error("verify belongs to one member", "Pass --member <id>")
            raise typer.Exit(1)
        _set_member_verify(project, member, value)
        return
    lead_id = _lead_for_settings(project)
    if key == "pipeline":
        _pod_config_set_pipeline(project, lead_id, value)
        return
    if key == "schedule":
        _pod_config_set_schedule(project, lead_id, value)
        return
    if key in _pod_settings.PodSettings.RECORDED_KEYS:
        ui.error(f"{key} is written by update, not by set")
        raise typer.Exit(1)
    try:
        coerced = _pod_settings.PodSettings.coerce(key, value, project=project)
    except _pod_settings.PodSettingsError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    _fleet.meta_set(lead_id, key, coerced)
    audit_log("pod.config", f"project={project} action=set key={key} value={coerced!r}")
    ui.success(f"Set {key}={coerced} for pod '{project}'")
    if key == "budgetUsd":
        _budget_changed(project, lead_id)


def unset_setting(project: str, key: str, *, member: str | None = None) -> None:
    """Clear one pod setting back to its default, or with ``member`` a verify command."""
    if key == "verify" or member is not None:
        if key != "verify" or member is None:
            ui.error("--member goes with verify", "Example: docket pod unset verify --member <id>")
            raise typer.Exit(1)
        _unset_member_verify(project, member)
        return
    lead_id = _lead_for_settings(project)
    if key not in _pod_settings.PodSettings.KEYS:
        ui.error(
            f"unknown pod setting {key!r}",
            f"Valid keys: {', '.join(_pod_settings.PodSettings.KEYS)}",
        )
        raise typer.Exit(1)
    # None reads back exactly like an absent key: the writer's only way to clear one.
    _fleet.meta_set(lead_id, key, None)
    if key == "pipeline":
        with contextlib.suppress(OSError):
            pod.bound_pipeline_path(project).unlink()
    if key == "schedule":
        # docket-schedules.json, not the meta key cleared above, is what the serve sweep reads.
        _sched.unset_schedule(current_home().schedule_file, project)
    audit_log("pod.config", f"project={project} action=unset key={key}")
    ui.success(f"Unset {key} for pod '{project}'; it falls back to its default")
    if key == "budgetUsd":
        _budget_changed(project, lead_id)
