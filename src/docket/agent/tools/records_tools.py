"""A pod's records as tools (specs/functional/pod-records.spec.md, "The tools")."""

from __future__ import annotations

from collections.abc import Sequence

from docket.agent.tools.registry import ToolRegistry
from docket.kernel.records import RecordSet
from docket.platform import RecordsStore

__all__ = ["load_records_tools"]


def load_records_tools(
    registry: ToolRegistry, *, store: RecordsStore, sets: Sequence[RecordSet]
) -> list[str]:
    """Register the record tools of *sets* into *registry*; the names registered."""
    raise NotImplementedError
