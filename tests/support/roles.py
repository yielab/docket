"""Test-side role overlays: write a pod's authored role files without going through ``docket pod``."""

from __future__ import annotations

from docket.kernel.home import current_home


def write_role_overlay(project: str, role: str, denied_tools: list[str]) -> None:
    """A read-only pod role *role* as its authored ``roles/<role>.yaml`` and instructions file."""
    roles = current_home().pod_config_dir(project) / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    cannot = ", ".join(denied_tools)
    (roles / f"{role}.yaml").write_text(
        f"kind: role\nname: {role}\nmodel: cheap\ntoolProfile: read-only\ncannot: [{cannot}]\n"
    )
    (roles / f"{role}.md").write_text("x\n")


def write_vetter_overlay(project: str, denied_tools: list[str]) -> None:
    write_role_overlay(project, "vetter", denied_tools)
