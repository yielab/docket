"""Fixtures shared by the role-tools tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel.home import Home, current_home, use_home


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path) -> Iterator[None]:
    with (
        use_home(Home(tmp_path / "docket")),
        use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)),
    ):
        yield
