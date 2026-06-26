"""Pod runtime-resource allocation.

Pure logic — no I/O. The CLI layer (cli/_pod.py) calls these helpers and
writes the allocation table via edges/store.py.

Each pod gets a reserved, non-overlapping **port range** (100 ports by default)
and an isolated **scratch data directory**. Ranges are tracked in a flat JSON
table at PORT_ALLOC_FILE (see config.py). The lowest available gap is assigned
on each allocation, so freed ranges are reused before expanding the ceiling.
"""

from __future__ import annotations

from typing import Any

# Per-pod port range defaults.  Override PORT_RANGE_SIZE via the env var
# DOCKET_PORT_RANGE_SIZE at daemon startup (kept here as module constants so
# tests can import directly without a live config).
PORT_BASE: int = 3000
PORT_RANGE_SIZE: int = 100


def allocate_pod_ports(
    project: str,
    table: dict[str, Any],
) -> tuple[int, int, dict[str, Any]]:
    """Assign a non-overlapping port range to *project*.

    Returns ``(portRangeStart, portRangeCount, updated_table)``.

    Idempotent: if *project* already has an allocation the existing range is
    returned and the table is unchanged.  The lowest available gap starting
    from ``PORT_BASE`` is assigned — freed ranges are reused before the
    ceiling advances.
    """
    allocs: dict[str, int] = {k: int(v) for k, v in table.get("allocations", {}).items()}
    if project in allocs:
        return allocs[project], PORT_RANGE_SIZE, table

    taken = sorted(allocs.values())
    start = PORT_BASE
    for s in taken:
        if start < s:
            break
        if start == s:
            start = s + PORT_RANGE_SIZE

    updated: dict[str, Any] = {**table, "allocations": {**allocs, project: start}}
    return start, PORT_RANGE_SIZE, updated


def free_pod_ports(
    project: str,
    table: dict[str, Any],
) -> dict[str, Any]:
    """Remove *project*'s port range from the allocation table.

    Idempotent: safe to call even if the project has no allocation.
    """
    allocs: dict[str, int] = {k: int(v) for k, v in table.get("allocations", {}).items()}
    allocs.pop(project, None)
    return {**table, "allocations": allocs}
