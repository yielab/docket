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
from docket.teams import roles as _roles


class TeamsRoleComposer:
    def narrow_registry(self, registry: ToolRegistry, role: str, project: str) -> ToolRegistry:
        return _roles.registry_for_role(registry, role, project)

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
