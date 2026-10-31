"""What a pod member's role can reach, for ``GET /pods/<pod>`` (operator-api.spec.md "Pod answers").

Computed by ``registry_for_role``, the function that narrows a hop's tools each turn, applied to
the tools docket itself declares: the built-ins and the pod's record tools. MCP and service tools
are not listed, because a server's tools are known only once it is started and a service's only once
its secret resolves; a ``GET`` does neither."""

from __future__ import annotations

from typing import Any

from docket.agent.tools import records_tools as _records_tools
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel.ports import records as _pod_records
from docket.kernel.records import RECORDS_QUERY_TOOL, records_tool_name
from docket.teams import records as _records
from docket.teams import role_composer as _role_composer


def member_capabilities(project: str, role: str) -> dict[str, Any]:
    """The tool ``kinds``, the tool names and the record sets *role* can write and query in
    *project*, after the role's and the pod's denials."""
    registry = builtin_registry()
    sets, _problems = _records.pod_record_sets(project)
    _records_tools.load_records_tools(registry, store=_pod_records.open(project), sets=sets)
    held = _role_composer.registry_for_role(registry, role, project)
    names = set(held.names())
    return {
        "kinds": sorted({tool.kind for n in names if (tool := held.get(n)) is not None}),
        "tools": sorted(names),
        "records": {
            "write": [s.name for s in sets if records_tool_name(s.name, "add") in names],
            "query": RECORDS_QUERY_TOOL in names,
        },
    }
