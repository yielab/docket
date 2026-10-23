"""How the network mode is worded: it is cut only while the sandbox is on.

Every surface that prints the mode asks this module, so none of them can say the network is cut
while nothing is jailed. ``teams.pod.effective_network`` still decides the mode; this only words it.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.teams import fleet as _fleet

NOT_ENFORCED = "not enforced: isolation off"


@dataclass(frozen=True)
class NetworkPosture:
    """A mode, where it came from, whether a jail enforces it, and its two wordings."""

    mode: str
    scope: str
    enforced: bool
    short: str
    line: str


def network_posture(mode: str, scope: str, *, isolation_on: bool) -> NetworkPosture:
    """Word ``mode``; only ``none`` with isolation on is enforced, egress is open otherwise."""
    if mode != "none":
        return NetworkPosture(mode, scope, False, "open", "open")
    if isolation_on:
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
    """The fleet-wide mode as recorded, against the recorded isolation."""
    cfg = _fleet.load_fleet()
    scope = "global" if _fleet.network_mode_recorded(cfg) else "default"
    return network_posture(
        _fleet.get_network_mode(cfg), scope, isolation_on=_fleet.get_isolation_enabled(cfg)
    )
