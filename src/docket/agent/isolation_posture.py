from __future__ import annotations

from pathlib import Path

from docket.agent.ports import DOCKET_TASK_NETWORK
from docket.governance.audit import audit_log
from docket.hops.workspace import prepare as _prepare
from docket.kernel.home import current_home
from docket.kernel.jail import JailPolicy
from docket.kernel.jail import jail as _jail
from docket.tasks.domain.task import DispatchError
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_settings as _pod_settings


def _ensure_pod_cache(project: str) -> Path | None:
    """*project*'s cache dir, created 0700 when missing; ``None`` when it cannot be created."""
    cache = current_home().pod_cache_dir(project)
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return cache


def _pod_cache_dir(agent_id: str) -> Path | None:
    """The agent's pod cache dir, created 0700 if a pod provisioned before it existed lacks one."""
    project = _pod.pod_of(agent_id)
    return _ensure_pod_cache(project) if project is not None else None


def _jail_cache_dir(agent_id: str, want_sandbox: bool) -> Path | None:
    """The jail's cache dir for this turn; ``None`` when isolation is off."""
    return _pod_cache_dir(agent_id) if want_sandbox else None


def _resolve_sandbox(agent_id: str, role: str) -> tuple[bool, str | None]:
    """Fail-closed go/no-go for this turn's isolation posture. Returns ``(want_sandbox,
    refusal)``; a non-``None`` refusal message means isolation is on but no backend
    is usable, so the turn is refused up front and audited (``isolation.refused``)
    rather than letting ``toolbox.run_bash`` silently degrade per call. See
    specs/functional/security-gates.spec.md ("Fail closed, not fail open, when isolation is on
    and no backend is usable")."""
    if not _fleet.get_isolation_enabled():
        return False, None
    availability = _jail.sandbox_availability()
    if availability.backend != "none":
        return True, None
    detail = (
        f"agent={agent_id} role={role or '?'} "
        f"landlock={availability.landlock} docker={availability.docker} seatbelt={availability.seatbelt}"
    )
    audit_log("isolation.refused", detail)
    return False, (
        "isolation is on ('docket setup sandbox on') but no sandbox backend is usable on this "
        "host -- refusing to run this turn unsandboxed rather than silently downgrading it. "
        "Fix one of two ways: use Linux 5.13+ (landlock) or macOS (seatbelt), or choose docker "
        "with 'docket setup sandbox backend docker'; or record an explicit opt-out with "
        "'docket setup sandbox off'."
    )


def _resolve_network(
    agent_id: str,
    role: str,
    want_sandbox: bool,
    project: str | None = None,
    *,
    task_none: bool = False,
) -> tuple[bool, str | None]:
    """``(network_allowed, refusal)`` for this turn. Mode ``none`` needs the jail to enforce it,
    so with isolation off the turn is refused up front and audited (``network.refused``).
    *task_none* is the task's own ``network: none``: it narrows, never widens."""
    mode, scope = _pod_settings.effective_network(project or _pod.pod_of(agent_id))
    if task_none:
        mode, scope = "none", ("task" if scope == "default" else scope)
    if mode == "open":
        return True, None
    if want_sandbox:
        return False, None
    if scope == "default":
        return True, None
    audit_log("network.refused", f"agent={agent_id} role={role or '?'} scope={scope}")
    setting = {
        "global": "'docket setup sandbox network none'",
        "task": "the task's network restriction",
    }.get(scope, "the pod's network=none")
    return False, (
        f"network is none ({setting}) but isolation is off, and only the sandbox can cut "
        "the network -- refusing to run this turn with the network open. Fix one of two "
        "ways: turn isolation on with 'docket setup sandbox on', or lift the lockdown "
        "with 'docket setup sandbox network open' (and the pod's network setting)."
    )


def resolve_command_jail(project: str, label: str) -> tuple[JailPolicy | None, str | None]:
    """``(jail, refusal)`` for a command docket launches outside an agent turn (a verify command,
    a ``run:`` step): ``(None, None)`` with isolation off, the pod's jail with it on, and a
    refusal message when isolation is on but no backend is usable."""
    want_sandbox, refusal = _resolve_sandbox(project, label)
    if refusal is not None:
        return None, refusal
    if not want_sandbox:
        return None, None
    network_allowed, _ = _resolve_network(project, label, True, project=project)
    return JailPolicy(
        network=network_allowed,
        cache_dir=_ensure_pod_cache(project),
        read_only=_pod_settings.effective_read_only(project),
    ), None


def _hop_read_only(project: str, root: Path) -> tuple[Path, ...]:
    """The read-only roots of a hop: the operator's grants for the pod, plus the prepared
    install cache entries the hop's root links into."""
    return (*_pod_settings.effective_read_only(project), *_prepare.linked_entries(root))


def _resolve_posture(
    agent_id: str, role: str, env: dict[str, str] | None = None
) -> tuple[bool, bool]:
    """``(want_sandbox, network_allowed)``: the isolation go/no-go, then the network's; *env*'s
    task network coordinate can only cut it. A refused posture raises ``DispatchError``."""

    task_none = (env or {}).get(DOCKET_TASK_NETWORK) == "none"

    want_sandbox, refusal = _resolve_sandbox(agent_id, role)
    if refusal is not None:
        raise DispatchError(refusal)
    network_allowed, refusal = _resolve_network(agent_id, role, want_sandbox, task_none=task_none)
    if refusal is not None:
        raise DispatchError(refusal)
    return want_sandbox, network_allowed
