"""The teams adapter of the turn engine's ``RoleComposer`` port.

The engine (``agent/``) asks which tools a role may see, what context budget its archetype
declares and what system prompt its workspace composes; this module answers from
``teams/roles.py`` and ``teams/identity.py``. ``bootstrap.bind_adapters`` binds it once per entry.
"""

from __future__ import annotations

from pathlib import Path

from docket.agent.ports import PromptComposition
from docket.agent.tools.registry import ToolRegistry
from docket.teams import identity as _identity
from docket.teams import pod_settings as _pod_settings
from docket.teams import role_composer as _role_composer
from docket.teams import roles as _roles
from docket.teams.roles import BUILTIN_TOOL_KINDS, load_registry


class TeamsRoleComposer:
    def narrow_registry(self, registry: ToolRegistry, role: str, project: str) -> ToolRegistry:
        return _role_composer.registry_for_role(registry, role, project)

    def declared_token_budget(self, role: str, project: str) -> int | None:
        found = _roles.load_registry(project).get(role)
        return None if found is None else found.token_budget

    def compose_prompt(
        self,
        agent_id: str,
        *,
        project_roots: tuple[Path, ...],
        context_window_tokens: int | None,
        max_output_tokens: int | None,
    ) -> PromptComposition:
        return _identity.compose_agent_prompt(
            agent_id,
            project_roots=project_roots,
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
        )


# A bad stored value degrades to "no additional pod-level denial" rather than raising --
# mirroring `hops/application/driver.py`'s `_resolve_allow_commands` fail-open
# pattern for a different pod setting: this runs once per turn on the live agent-loop
# path and must never crash it, and the write path (`PodSettings.coerce`) is what
# refuses a bad value before it can ever reach here. Deferred import: `teams.pod`
# imports this module at module scope, so importing it back here would be circular --
# by the time any real turn calls this function both modules are already loaded.
def _pod_denied_tools(project: str) -> tuple[str, ...]:
    """*project*'s own `deniedTools` pod setting, or `()` for a non-pod caller, an
    unset setting, or an unreadable/malformed stored value."""
    if not project:
        return ()

    try:
        return _pod_settings.PodSettings.load_for(project).denied_tools
    except _pod_settings.PodSettingsError:
        return ()


def registry_for_role(base: ToolRegistry, role: str, project: str = "") -> ToolRegistry:
    """Narrow *base* to exactly what *role* may call.

    Looks *role* up in the live archetype registry (*project*'s pod overlay, when
    given, resolving nearest-wins above the global overlay -- see `load_registry`) and
    removes every name in the **union** of its `denied_tools` and *project*'s own
    `deniedTools` pod setting (`teams.pod_settings.PodSettings`, see `_pod_denied_tools`) via the
    public `ToolRegistry.without()` API -- data-driven, not a per-role branch
    (`agent/loop.py` is the one caller, once per turn, passing the turn's
    `ToolContext.project`). A pod-level denial is therefore as strong as an
    archetype-declared one: a pod's `deniedTools` naming `fetch` removes it from
    every role in that pod, not only the ones whose own archetype already denied it.
    A Reviewer's registry genuinely lacks `write`/`edit`, so a call to either is
    refused by `dispatch_tool` as an *unknown tool* -- stronger than a SOUL.md
    instruction telling it not to use them. An unrecognized *role* combined with no
    pod-level denial returns *base* unchanged.

    **Also removes by capability, not only by name.** `denied_tools` is a list of
    literal built-in names, but `base` may also carry MCP-adapted tools registered
    under a namespaced name (`mcp__<server>__<tool>`) no denylist could ever spell
    out in advance -- and every adapted tool is registered `kind="write"`
    unless its server was declared otherwise, since nothing can prove a remote tool
    is actually read-only. So after the name-based removal, this also maps each
    denied built-in name through `BUILTIN_TOOL_KINDS` and removes every tool of
    those kinds whose name is not a built-in. A built-in is removed only by its own
    name: denying `fetch` leaves `read`. A role denied `write` can never regain a
    write-capable tool just because it arrived through MCP instead of
    `agent.tools.registry.builtin_registry()`.
    """
    archetype = load_registry(project).get(role)
    role_denied = archetype.denied_tools if archetype is not None else ()
    denied = tuple(dict.fromkeys((*role_denied, *_pod_denied_tools(project))))
    if not denied:
        return base
    narrowed = base.without(*denied)
    denied_kinds = {kind for name in denied if (kind := BUILTIN_TOOL_KINDS.get(name))}
    if denied_kinds:
        extra = [
            name
            for name in narrowed.names()
            if name not in BUILTIN_TOOL_KINDS
            and (tool := narrowed.get(name)) is not None
            and tool.kind in denied_kinds
        ]
        narrowed = narrowed.without(*extra)
    return narrowed
