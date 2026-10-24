"""Fixtures shared by the telegram-channel tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from docket.kernel.home import current_home, use_home


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
        yield
