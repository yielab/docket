"""Test-side role overlays: write a pod's authored role files without going through ``docket pod``."""

from __future__ import annotations

from docket.kernel.home import current_home
from docket.teams.builtin_roles import BUILTIN_ARCHETYPES, STARTER_ARCHETYPES


def write_role_overlay(
    project: str, role: str, denied_tools: list[str], *, extra: str = ""
) -> None:
    """A read-only pod role *role* as its authored ``roles/<role>.yaml`` and instructions file;
    *extra* is further authored YAML lines (an allow-list, a cap)."""
    roles = current_home().pod_config_dir(project) / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    cannot = ", ".join(denied_tools)
    (roles / f"{role}.yaml").write_text(
        f"kind: role\nname: {role}\nmodel: cheap\ntoolProfile: read-only\ncannot: [{cannot}]\n"
        f"{extra}"
    )
    (roles / f"{role}.md").write_text("x\n")


def write_vetter_overlay(project: str, denied_tools: list[str]) -> None:
    write_role_overlay(project, "vetter", denied_tools)


ROLE_NAMES: frozenset[str] = frozenset({**BUILTIN_ARCHETYPES, **STARTER_ARCHETYPES})
