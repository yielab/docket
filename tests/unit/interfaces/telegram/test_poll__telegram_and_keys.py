"""`docket start --telegram` wiring: the poll loop's pacing/backoff discipline.

Pinned here, which the channel/adapter test modules don't reach: `serve.py`'s poll loop
paces itself (no busy-loop on an unconfigured bot or transport error) and never lets an
unexpected exception escape silently -- catch, print, back off, keep going, never a bare
`contextlib.suppress(Exception)`.
"""

from __future__ import annotations

import pytest

from docket.interfaces.telegram import poll

SUBJECT = "docket.interfaces.telegram.poll"


@pytest.fixture(autouse=True)
def _fast_backoffs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poll, "_TELEGRAM_UNCONFIGURED_BACKOFF_S", 0, raising=True)
    monkeypatch.setattr(poll, "_TELEGRAM_ERROR_BACKOFF_S", 0, raising=True)
