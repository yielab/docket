"""The ``lights-out`` profile: what a pod must have in place before its tasks run unattended.

The decision is a pure function over ``Facts``; ``gather_facts`` fills them from the readers that
already decide each thing (isolation, the sandbox probe, ``effective_network``, the planned
pipeline, the secret store) and decides nothing itself. See security-gates.spec.md "Profiles".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.agent.tools import mcp_tools as _mcp
from docket.governance import secrets as _secrets
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.sandbox import launch as _launch
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

LIGHTS_OUT = "lights-out"


@dataclass(frozen=True)
class Violation:
    """One unmet requirement and the operator command or edit that fixes it."""

    requirement: str
    detail: str
    fix: str


@dataclass(frozen=True)
class Facts:
    """Everything ``lights_out_violations`` decides on."""

    isolation_on: bool
    backend: str
    network_mode: str
    network_scope: str
    ungated_implementers: tuple[str, ...]
    injected_secrets: tuple[str, ...]


def lights_out_violations(facts: Facts) -> list[Violation]:
    """Every requirement *facts* leaves unmet, in a fixed order."""
    out: list[Violation] = []
    if not facts.isolation_on:
        out.append(Violation("isolation", "isolation is off", "docket setup sandbox on"))
    elif facts.backend == "none":
        out.append(
            Violation(
                "isolation",
                "isolation is on but no sandbox backend is usable",
                "docket setup sandbox backend docker, or use Linux 5.13+ or macOS",
            )
        )
    if facts.network_mode != "none" or facts.network_scope == "default":
        out.append(
            Violation(
                "network",
                "the jail's network is not cut by a recorded choice",
                "docket setup sandbox network none, or docket pod set network none",
            )
        )
    for step in facts.ungated_implementers:
        out.append(
            Violation(
                "external-gate",
                f"implementer step {step!r} has no external gate",
                f"add 'gate: {{external: <verifier command>}}' to step {step!r}",
            )
        )
    for name in facts.injected_secrets:
        out.append(
            Violation(
                "secrets",
                f"the pod injects {name}, which is named in the secret store",
                f"remove {name} from the pod's MCP server env, or from the secret store",
            )
        )
    return out


def effective_profile(project: str) -> str:
    """``lights-out`` when the fleet or the pod says so (a pod only strengthens); unreadable pod
    settings fail closed to ``lights-out``."""
    if _fleet.get_profile() == LIGHTS_OUT:
        return LIGHTS_OUT
    try:
        return _pod_settings.PodSettings.load_for(project).profile
    except _pod_settings.PodSettingsError:
        return LIGHTS_OUT


def _walk(nodes: tuple[Any, ...]) -> list[_orch.PlannedUnit]:
    units: list[_orch.PlannedUnit] = []
    for node in nodes:
        if isinstance(node, _orch.PlannedGroup):
            units.extend(node.children)
        else:
            units.append(node)
    return units


def _is_implementer(unit: _orch.PlannedUnit) -> bool:
    if unit.skipped or unit.member_id is None:
        return False
    role = unit.role or _fleet.meta_get(unit.member_id, "role", "")
    return role == "implementer"


def _injected_names(project: str, nodes: tuple[Any, ...]) -> set[str]:
    from docket.hops.application import record as _record

    names: set[str] = set()
    for unit in _walk(nodes):
        if _is_implementer(unit) and unit.member_id:
            names.update(_record.hop_env(unit.member_id, "implementer") or {})
    try:
        selection = _pod_settings.PodSettings.load_for(project).mcp_servers
    except _pod_settings.PodSettingsError:
        selection = None
    for server in _mcp.load_mcp_servers(project):
        if selection is None or server.name in selection:
            names.update(server.env)
    return names


def gather_facts(
    project: str, nodes: tuple[Any, ...] | None = None, spec: _pipeline.PipelineSpec | None = None
) -> Facts:
    """Read the live state. *nodes* are the planned steps a dispatch is about to run; omitted, the
    pod's own pipeline is planned (``doctor`` and ``status``)."""
    if nodes is None:
        from docket.pipeline.application import executor as _executor

        nodes = _executor._resolve_pipeline_steps(project, spec)[0]
    mode, scope = _pod_settings.effective_network(project)
    ungated = tuple(
        unit.step_id
        for unit in _walk(nodes)
        if _is_implementer(unit) and not isinstance(unit.gate, _gates.ExternalGate)
    )
    stored = _secrets.secrets_keys()
    return Facts(
        isolation_on=_fleet.get_isolation_enabled(),
        backend=_launch.sandbox_availability().backend,
        network_mode=mode,
        network_scope=scope,
        ungated_implementers=ungated,
        injected_secrets=tuple(sorted(_injected_names(project, nodes) & stored)),
    )


def project_violations(
    project: str, nodes: tuple[Any, ...] | None = None, spec: _pipeline.PipelineSpec | None = None
) -> list[Violation]:
    """The pod's violations under ``lights-out``, ``[]`` when its effective profile is attended."""
    if effective_profile(project) != LIGHTS_OUT:
        return []
    return lights_out_violations(gather_facts(project, nodes, spec))


def fleet_violations() -> list[Violation]:
    """The requirements the fleet record alone decides (isolation, network), with no pod in view."""
    mode, scope = _pod_settings.effective_network(None)
    facts = Facts(
        isolation_on=_fleet.get_isolation_enabled(),
        backend=_launch.sandbox_availability().backend,
        network_mode=mode,
        network_scope=scope,
        ungated_implementers=(),
        injected_secrets=(),
    )
    return lights_out_violations(facts)


def lights_out_report() -> dict[str, list[Violation]]:
    """Every dispatchable pod whose effective profile is ``lights-out``, with its violations; empty
    on a fleet that records nothing (the usual case)."""
    from docket.tasks.application import queue as _queue

    report: dict[str, list[Violation]] = {}
    for project in _queue.dispatchable_pods():
        if effective_profile(project) == LIGHTS_OUT:
            report[project] = project_violations(project)
    return report


def as_json(violations: list[Violation]) -> dict[str, Any]:
    """The ``profile`` block ``status --json`` and ``doctor --json`` carry under ``lights-out``."""
    return {
        "name": LIGHTS_OUT,
        "violations": [{"requirement": v.requirement, "fix": v.fix} for v in violations],
    }
