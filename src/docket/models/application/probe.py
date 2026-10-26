from __future__ import annotations

from dataclasses import dataclass, field

from docket.agent.ports import ModelLimits

# ── registration probe ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeResult:
    """A raw, unclassified probe of a provider's ``/models`` route. ``status`` is ``None``
    only for a transport failure (DNS, refused, timeout) -- classification into a registration
    outcome is ``models/catalog.py::verify_endpoint``'s job, kept pure and out of this module."""

    status: int | None
    transport_error: str = ""
    model_ids: list[str] = field(default_factory=list)
    limits: dict[str, ModelLimits] = field(default_factory=dict)
