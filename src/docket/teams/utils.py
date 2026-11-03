"""Shared utility functions for read-only command implementations."""

from __future__ import annotations


def si_format(n: int) -> str:
    """Format a token count with SI suffix (e.g. 1_234_567 → '1.2M')."""
    f = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(f) < 1000.0:
            return str(int(f)) if unit == "" else f"{f:.1f}{unit}"
        f /= 1000.0
    return f"{f:.1f}P"
