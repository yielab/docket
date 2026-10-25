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
from docket.operator.inbox import (
    MemoryItem,
    build_inbox,
    escalation_page,
    escalation_view,
    escalation_views,
    pause_is_live,
    pending_memory,
    question_escalation,
    task_view,
)
from docket.operator.notify import (
    build_test_event,
    diff_events,
    flush,
    flush_notify_channels,
    read_state,
    resolve_secret,
)
from docket.operator.render import (
    RenderedOption,
    ids_line,
    render_escalation,
)

__all__ = [
    "ChannelError",
    "ChannelSpec",
    "MemoryItem",
    "RenderedOption",
    "build_inbox",
    "build_test_event",
    "delete_channel",
    "diff_events",
    "disable_channel",
    "enable_channel",
    "escalation_page",
    "escalation_view",
    "escalation_views",
    "export_channel",
    "flush",
    "flush_notify_channels",
    "ids_line",
    "is_widening",
    "load_catalog",
    "load_channel_document",
    "pause_is_live",
    "pending_memory",
    "question_escalation",
    "read_state",
    "render_escalation",
    "resolve_secret",
    "save_channel",
    "set_content",
    "task_view",
    "unreached_warning",
]
