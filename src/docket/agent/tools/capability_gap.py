"""What a turn may call that the pod's configuration lacks (agent-loop.spec.md requirement 113).

``dispatch_tool`` answers an unknown tool name with a ``CapabilityGap`` when the name is one the
pod could give the role by configuration alone, so the turn can stop on it and the task can say
what to change. The pod's names arrive as one typed ``PodOffer``, computed by the driver; this
module reads no pod, fleet or records module.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from dataclasses import dataclass, field

from docket.agent.ports import CapabilityGap
from docket.kernel.records import RECORDS_ALL_ENTRY, RECORDS_TOOL_PREFIX

FETCH = "fetch"


@dataclass(frozen=True)
class PodOffer:
    """What the turn's pod offers its role: the *holdable* tool names, the declared *record_sets*,
    whether `fetch` is *fetch_declarable*, the *fetch_fix* that opens it and the *held_back* MCP
    tools (name to restoring command)."""

    pod: str
    holdable: frozenset[str]
    record_sets: frozenset[str]
    fetch_declarable: bool
    fetch_fix: str = ""
    held_back: Mapping[str, str] = field(default_factory=dict)


def _then_update(pod: str) -> str:
    return f"then run `docket pod update --pod {pod}`"


def _list_in_tools(entry: str, role: str, pod: str) -> str:
    return (
        f"list '{entry}' in the tools of role '{role}' (its roles/{role}.yaml, or the step's "
        f"tools), {_then_update(pod)}"
    )


def gap_for(
    name: str, held: Container[str], role: str, offer: PodOffer | None
) -> CapabilityGap | None:
    """The gap a call to *name* is, or ``None`` for a name nothing offers. *held* is what the role's
    registry holds; a name in it is no gap."""
    if offer is None or name in held:
        return None
    if name.startswith(RECORDS_TOOL_PREFIX):
        return _records_gap(name, role, offer)
    if name in offer.held_back:
        return CapabilityGap("tool", name, offer.held_back[name])
    if name in offer.holdable:
        return CapabilityGap("tool", name, _list_in_tools(name, role, offer.pod))
    if name == FETCH and offer.fetch_declarable:
        fix = offer.fetch_fix or f"docket pod set fetchDomains <host> --pod {offer.pod}"
        return CapabilityGap("fetch", FETCH, f"run `{fix}`")
    return None


def _records_gap(name: str, role: str, offer: PodOffer) -> CapabilityGap | None:
    parts = name[len(RECORDS_TOOL_PREFIX) :].split("__")
    if len(parts) == 1:
        if name not in offer.holdable:
            return None
        return CapabilityGap(
            "records", parts[0], _list_in_tools(RECORDS_ALL_ENTRY, role, offer.pod)
        )
    record_set = parts[0]
    if name in offer.holdable:
        entry = RECORDS_TOOL_PREFIX + record_set
        return CapabilityGap("records", record_set, _list_in_tools(entry, role, offer.pod))
    if record_set not in offer.record_sets:
        return CapabilityGap(
            "records",
            record_set,
            f"declare records/{record_set}.yaml in the pod's configuration, {_then_update(offer.pod)}",
        )
    return None
