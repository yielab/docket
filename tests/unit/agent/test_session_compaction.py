"""Durable turn history + compaction (`agent/session.py`).

Covers session-key isolation, a round trip preserving `tool_calls`/
`tool_call_id`/`name`, an assistant `tool_calls` message never split from
its answering `tool` messages by a compaction cut, measured vs. estimated
token accounting, and fail-closed summarisation on a failing driver.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel.home import current_home, use_home

SUBJECT = "docket.agent.session_compaction"


@pytest.fixture(autouse=True)
def _isolate_sessions_dir(tmp_path: Path) -> Iterator[None]:
    with use_home(dataclasses.replace(current_home(), sessions_dir_override=tmp_path / "sessions")):
        yield
