"""Durable turn history + compaction (`agent/session.py`).

Covers session-key isolation, a round trip preserving `tool_calls`/
`tool_call_id`/`name`, an assistant `tool_calls` message never split from
its answering `tool` messages by a compaction cut, measured vs. estimated
token accounting, and fail-closed summarisation on a failing driver.
"""

from __future__ import annotations

from tests.support import home as _support_home

_isolate_sessions_dir = _support_home.isolate_sessions_dir

SUBJECT = "docket.agent.session_compaction"
