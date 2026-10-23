"""Test-side pod seeding: provision a fresh pod's members without going through `docket init`."""

from __future__ import annotations

from rich.markup import escape

from docket.interfaces.cli.render import ui
from docket.teams import pod_provisioning as _pp


def build_pod(
    project: str,
    roles: tuple[str, ...],
    *,
    codebase: str = "",
    stack: str = "",
    description: str = "",
    project_key: str = "default",
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> list[str]:
    """Provision a pod's members and return their ids; a provisioning failure warns and
    returns ``[]``."""
    try:
        created = _pp.provision_members(
            project,
            roles,
            codebase=codebase,
            stack=stack,
            description=description,
            project_key=project_key,
            work_dir=work_dir,
            blueprint_name=blueprint_name,
            budget_usd=budget_usd,
        )
    except _pp.PodProvisionError as exc:
        ui.warn(f"  pod provisioning failed: {exc}")
        return []
    for m in created:
        ui.success(escape(f"  {m.member_id}  [{m.role}]  {m.model}"))
    return [m.member_id for m in created]
