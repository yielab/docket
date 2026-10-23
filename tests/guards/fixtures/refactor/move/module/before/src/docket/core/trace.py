"""Append-only trace."""

from __future__ import annotations

EVENTS: list[str] = []


def record(event: str) -> None:
    EVENTS.append(event)
