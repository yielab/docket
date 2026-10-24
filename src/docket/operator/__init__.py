"""Public surface of the ``operator`` context (ADR 0030).

Exactly the names other contexts import; the modules behind them stay internal.
"""

from __future__ import annotations

from docket.operator.channel import (
    ChannelError,
    ChannelSpec,
    delete_channel,
    disable_channel,
    enable_channel,
    export_channel,
    is_widening,
    load_catalog,
    load_channel_document,
    save_channel,
    set_content,
    unreached_warning,
)
from docket.operator.inbox import MemoryItem, build_inbox, pending_memory, task_view
from docket.operator.notify import (
    build_test_event,
    diff_events,
    flush,
    flush_notify_channels,
    read_state,
    resolve_secret,
)

__all__ = [
    "ChannelError",
    "ChannelSpec",
    "MemoryItem",
    "build_inbox",
    "build_test_event",
    "delete_channel",
    "diff_events",
    "disable_channel",
    "enable_channel",
    "export_channel",
    "flush",
    "flush_notify_channels",
    "is_widening",
    "load_catalog",
    "load_channel_document",
    "pending_memory",
    "read_state",
    "resolve_secret",
    "save_channel",
    "set_content",
    "task_view",
    "unreached_warning",
]
