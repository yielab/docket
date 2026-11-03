"""How the network mode is worded: it is cut only while a sandbox is on and can run.

Every surface that prints the mode asks this module, so none of them can say the network is cut
while nothing is jailed. ``teams.pod.effective_network`` still decides the mode; this only words it.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.kernel.ports import jail as _jail
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

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
