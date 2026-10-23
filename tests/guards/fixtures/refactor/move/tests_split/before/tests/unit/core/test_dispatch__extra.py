"""More dispatch tests that reuse a helper of the split file."""

from __future__ import annotations

from pathlib import Path

from docket.core import dispatch as _dispatch

from .test_dispatch import _name

SUBJECT = "docket.core.dispatch"


def test_extra() -> None:
    assert _name(Path("a/b")) == "b"
    assert _dispatch.ping() == "pong"
