from __future__ import annotations

from pathlib import Path
from typing import Literal

from docket.kernel.home import current_home
from docket.tasks.domain.task import DispatchError
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_settings as _teams_pod_settings
from docket.teams import utils as _utils

DEFAULT_TIMEOUT = 300


def pod_task_list_path(project: str) -> Path:
    """The pod's task queue lives in its Lead's workspace: one queue per pod, keyed by
    the Lead, so pods never share a task list.
    """
    lead_id = _pod.member_id(project, "lead")
    return current_home().workspace_dir(lead_id) / "TASK_LIST.json"


def pod_recorded_cost(project: str) -> float:
    """Sum each pod member's recorded USD spend (always 0.0 today — see ``pod_gating_cost``)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    total = 0.0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        total += float(_utils.aggregate_cost(mid).cost_usd)
    return round(total, 6)


def _pod_settings(project: str) -> _teams_pod_settings.PodSettings:
    """Load this pod's validated Lead-meta settings, or raise ``DispatchError``
    naming the offending key -- never a silently substituted default (see
    ``teams.pod.PodSettings``)."""
    try:
        return _teams_pod_settings.PodSettings.load_for(project)
    except _teams_pod_settings.PodSettingsError as exc:
        raise DispatchError(str(exc)) from exc


def pod_budget(project: str) -> float:
    """The pod's USD budget cap (Lead's ``budgetUsd``), 0.0 = unlimited."""
    return _pod_settings(project).budget_usd


def pod_max_rework_cycles(project: str) -> int:
    """Bounded rework budget for a REQUEST-CHANGES review: Lead's ``maxReworkCycles`` meta
    (default ``1``; ``0`` disables rework -- a hard gate, no retry). See pod-dispatch.spec.md
    ("Reviewer verdict gate and bounded rework")."""
    return _pod_settings(project).max_rework_cycles


def _retries_for_role(role: str) -> int:
    """Max retry attempts (after the first try) for one role's hop."""
    return current_home().dispatch_retries_per_role.get(
        role, current_home().dispatch_retries_default
    )


def _lead_meta_timeout(project: str, field_name: str) -> int | None:
    """Read one already-validated timeout field off this pod's ``PodSettings``."""
    settings = _pod_settings(project)
    return settings.turn_timeout_s if field_name == "turnTimeoutS" else settings.verify_timeout_s


def pod_turn_timeout(project: str) -> int | None:
    """The pod's configured agent-turn timeout (Lead's ``turnTimeoutS``), if set."""
    return _lead_meta_timeout(project, "turnTimeoutS")


def pod_verify_timeout(project: str) -> int | None:
    """The pod's configured verifyCmd timeout (Lead's ``verifyTimeoutS``), if set."""
    return _lead_meta_timeout(project, "verifyTimeoutS")


def pod_approval_mode_is_set(project: str) -> bool:
    """Whether this pod's Lead meta carries its own explicit ``approvalMode`` (see
    ``pod_approval_mode``)."""
    # Reads the raw stored key directly, never a validated PodSettings value, since that
    # always carries the field default ("wait") once loaded -- indistinguishable from a
    # real "wait" unless the raw presence is checked first.
    lead_id = _pod.member_id(project, "lead")
    return bool(_fleet.meta_get(lead_id, "approvalMode", ""))


def pod_approval_mode(
    project: str, *, caller_default: Literal["wait", "park"] = "wait"
) -> Literal["wait", "park", "refuse"]:
    """The pod's configured unattended-approval posture: an explicit Lead ``approvalMode``
    always wins; an unset one resolves through *caller_default* instead of a fixed "wait"."""
    # ADR 0016 SS2: `serve --dispatch`'s sweep and a non-TTY foreground dispatch pass
    # "park", a TTY foreground dispatch passes "wait" -- see `_compose_hop`.
    if pod_approval_mode_is_set(project):
        return _pod_settings(project).approval_mode
    return caller_default


def _resolve_timeout(explicit: int | None, pod_value: int | None) -> int:
    """Timeout precedence: an explicit per-call override, else the pod's Lead-meta
    config, else ``DEFAULT_TIMEOUT`` (the fallback of last resort)."""
    if explicit is not None:
        return explicit
    if pod_value is not None:
        return pod_value
    return DEFAULT_TIMEOUT
