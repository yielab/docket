"""Pod seeding and message helpers for the Telegram channel integration tests."""

from __future__ import annotations

from docket.governance import audit as _audit
from docket.teams import fleet as _fleet


def _bind(agent_id: str, peer_id: str, channel: str = "telegram") -> None:
    _fleet.upsert_binding(agent_id, peer_id, channel)


def _read_audit() -> list[dict[str, object]]:
    return _audit.read_audit()
