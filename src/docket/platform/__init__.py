"""Public surface of the ``platform`` context (ADR 0030).

Exactly the names other contexts import; the modules behind them stay internal.
"""

from __future__ import annotations

from docket.platform.store import mkdir_private, read_json, read_modify_write, with_lock, write_json

__all__ = [
    "mkdir_private",
    "read_json",
    "read_modify_write",
    "with_lock",
    "write_json",
]
