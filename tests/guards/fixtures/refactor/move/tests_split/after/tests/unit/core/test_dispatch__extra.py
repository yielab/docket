"""More dispatch tests that reuse a helper of the split file."""

from __future__ import annotations

from pathlib import Path

from tests.unit.hops.test_runner import _name

from docket.core import dispatch as _dispatch

SUBJECT = "docket.core.dispatch"


def test_extra() -> None:
    assert _name(Path("a/b")) == "b"
    assert _dispatch.ping() == "pong"
