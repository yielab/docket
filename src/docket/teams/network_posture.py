"""How the network mode is worded: it is cut only while a sandbox is on and can run, and which
hosts a member's ``fetch`` reaches.

Every surface that prints the mode asks this module, so none of them can say the network is cut
while nothing is jailed. ``teams.pod.effective_network`` still decides the mode; this only words it.
``fetch_reach`` decides the hosts: the one reader of the declared list and of open read.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.kernel.ports import jail as _jail
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings
from docket.teams.models import WorkspaceKind

NOT_ENFORCED = "not enforced: isolation off"


@dataclass(frozen=True)
class NetworkPosture:
    """A mode, where it came from, whether a jail enforces it, and its two wordings."""

    mode: str
    scope: str
    enforced: bool
    short: str
    line: str


def jail_enforces(cfg: _fleet.FleetConfig | None = None) -> bool:
    """True when isolation is recorded on and a sandbox backend exists on this machine."""
    return _fleet.get_isolation_enabled(cfg) and _jail.sandbox_availability().backend != "none"


def network_posture(mode: str, scope: str, *, jailed: bool) -> NetworkPosture:
    """Word ``mode``; only ``none`` under a jail that runs (``jail_enforces``) is enforced, egress
    is open otherwise."""
    if mode != "none":
        if scope == _pod_settings.POD_GRANT_SCOPE:
            return NetworkPosture(mode, scope, False, "open (pod grant)", "open (pod grant)")
        return NetworkPosture(mode, scope, False, "open", "open")
    if jailed:
        return NetworkPosture(
            mode, scope, True, "none", f"none ({scope}); jailed tool calls have no network"
        )
    return NetworkPosture(
        mode,
        scope,
        False,
        f"none ({NOT_ENFORCED})",
        f"none ({scope}), {NOT_ENFORCED}, egress is open",
    )


def global_posture() -> NetworkPosture:
    """The fleet-wide mode as recorded, against the jail this machine can run."""
    cfg = _fleet.load_fleet()
    scope = "global" if _fleet.network_mode_recorded(cfg) else "default"
    return network_posture(_fleet.get_network_mode(cfg), scope, jailed=jail_enforces(cfg))


@dataclass(frozen=True)
class FetchReach:
    """The hosts a member's ``fetch`` reaches (``("*",)`` is any public host), which rule gave them
    (``open``, ``listed`` or ``none``), a sentence saying why and, when ``none``, the one command
    that opens it."""

    hosts: tuple[str, ...]
    mode: str
    reason: str
    fix: str


def isolation_fix() -> str:
    """The command that turns the jail on, or points at its backend when none exists."""
    if not _fleet.get_isolation_enabled():
        return "docket setup sandbox on"
    return "docket setup sandbox backend docker"


def fetch_reach(project: str | None) -> FetchReach:
    """How *project*'s members read the web: the declared list (machine's plus pod's) when there is
    one, else any public host for a folder pod under an enforced jail, else nothing. *project*
    ``None`` is the machine's list alone."""
    declared = _pod_settings.effective_fetch_domains(project)
    if declared:
        reason = (
            "any public host (granted with --widen)"
            if _pod_settings.FETCH_ANY in declared
            else f"reads {', '.join(declared)}"
        )
        return FetchReach(declared, "listed", reason, "")
    if project and _pod_settings.workspace_kind(project) == WorkspaceKind.workdir:
        if jail_enforces():
            return FetchReach(
                (_pod_settings.FETCH_ANY,),
                "open",
                "a folder team under the jail reads any public host",
                "",
            )
        return FetchReach(
            (),
            "none",
            "a folder team reads the web only under the jail, and the jail is not running",
            isolation_fix(),
        )
    fix = (
        f"docket pod set fetchDomains <host> --pod {project}"
        if project
        else "set FETCH_ALLOWED_DOMAINS"
    )
    return FetchReach((), "none", "no host is allowed", fix)
