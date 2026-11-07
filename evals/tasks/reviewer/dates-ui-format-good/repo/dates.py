"""Dates are stored as UTC ISO-8601 and formatted only in the UI."""

from datetime import UTC, datetime

STORED = "%Y-%m-%dT%H:%M:%SZ"


def to_storage(moment: datetime) -> str:
    """The stored form of an aware *moment*: UTC ISO-8601 with a trailing Z."""
    return moment.astimezone(UTC).strftime(STORED)
