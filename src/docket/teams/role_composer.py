"""The teams adapter of the turn engine's ``RoleComposer`` port.

The engine (``agent/``) asks which tools a role may see, what context budget its archetype
declares and what system prompt its workspace composes; this module answers from
``teams/roles.py`` and ``teams/identity.py``. ``bootstrap.bind_adapters`` binds it once per entry.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docket.agent.ports import PromptComposition
from docket.agent.tools.registry import Tool, ToolRegistry
from docket.teams import identity as _identity
from docket.teams import pod_settings as _pod_settings
from docket.teams import role_composer as _role_composer
from docket.teams import roles as _roles
from docket.teams.roles import BUILTIN_TOOL_KINDS, load_registry


class TeamsRoleComposer:
    def narrow_registry(
        self,
        registry: ToolRegistry,
        role: str,
        project: str,
        *,
        surface: str = "full",
        allow: tuple[str, ...] | None = None,
    ) -> ToolRegistry:
        return _role_composer.registry_for_role(
            registry, role, project, surface=surface, allow=allow
        )

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


# What the `minimal` surface keeps: the tools a small model needs to find, read, change, run and check. A tool
# that ends the turn (the step's closing tool) is kept by what it does, not by a name given here.
MINIMAL_SURFACE = ("bash", "read", "glob", "edit", "write", "verify")

# Tools that only serve another: a role denied the key is not offered them either.
SERVED_TOOLS: dict[str, tuple[str, ...]] = {"bash": ("process_output", "process_stop")}


def _keeping(base: ToolRegistry, keep: Callable[[Tool], bool]) -> ToolRegistry:
    """A copy of *base* holding only the tools *keep* accepts."""
    dropped = [name for name in base.names() if (tool := base.get(name)) and not keep(tool)]
    return base.without(*dropped)


def registry_for_role(
    base: ToolRegistry,
    role: str,
    project: str = "",
    *,
    surface: str = "full",
    allow: tuple[str, ...] | None = None,
) -> ToolRegistry:
    """What a hop sees, decided once: *base* narrowed by the model profile's *surface*, then by
    the allow-list (*allow* when the step declared one, else *role*'s `tools`), then minus what
    *role* and its pod deny.

    A ``minimal`` *surface* keeps ``MINIMAL_SURFACE``, every tool that ends the turn and every MCP
    tool the allow-list in force names (a step's *allow* replaces the role's `tools` there too), so a
    role that names an MCP tool keeps it and a role with no allow-list gets none; ``full`` keeps
    all. The allow-list keeps the names it lists and the tool that ends the turn, and an
    allow-list never grants a denied tool, because the denial runs last. Looks *role* up in the live
    archetype registry (*project*'s pod overlay, when given, resolving nearest-wins above the
    global overlay -- see `load_registry`) and removes every name in the **union** of its
    `denied_tools` and *project*'s own `deniedTools` pod setting (`teams.pod_settings.PodSettings`,
    see `_pod_denied_tools`) via the public `ToolRegistry.without()` API -- data-driven, not a
    per-role branch (`agent/loop.py` is the one caller, once per turn, passing the turn's
    `ToolContext.project`). A denied tool takes with it the tools that only serve it (denying
    `bash` removes `process_output` and `process_stop`). A pod-level denial is therefore as strong
    as an archetype-declared one: a pod's `deniedTools` naming `fetch` removes it from
    every role in that pod, not only the ones whose own archetype already denied it.
    A Reviewer's registry genuinely lacks `write`/`edit`, so a call to either is
    refused by `dispatch_tool` as an *unknown tool* -- stronger than a SOUL.md
    instruction telling it not to use them. An unrecognized *role* combined with no
    pod-level denial, a `full` surface and no allow-list returns *base* unchanged.

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
    named = tuple(dict.fromkeys((*role_denied, *_pod_denied_tools(project))))
    denied = tuple(dict.fromkeys((*named, *(t for n in named for t in SERVED_TOOLS.get(n, ())))))
    allowed = allow if allow is not None else (archetype.tools if archetype is not None else None)
    narrowed = base
    if surface == "minimal":
        narrowed = _keeping(
            narrowed,
            lambda t: t.name in MINIMAL_SURFACE
            or t.ends_turn
            or (
                t.name.startswith(_roles.MCP_TOOL_PREFIX)
                and allowed is not None
                and _roles.allow_list_names(allowed, t.name)
            ),
        )
    if allowed is not None:
        narrowed = _keeping(
            narrowed, lambda t: _roles.allow_list_names(allowed, t.name) or t.ends_turn
        )
    held = archetype.tools if archetype is not None and archetype.tools else ()
    if any((tool := narrowed.get(n)) is not None and tool.kind == "send" for n in narrowed.names()):
        narrowed = _keeping(
            narrowed, lambda t: t.kind != "send" or _roles.allow_list_names(held, t.name)
        )
    if not denied:
        return narrowed
    narrowed = narrowed.without(*denied)
    denied_kinds: set[str] = {kind for name in named if (kind := BUILTIN_TOOL_KINDS.get(name))}
    if _roles.SEND_KIND in named:
        denied_kinds.add(_roles.SEND_KIND)
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
