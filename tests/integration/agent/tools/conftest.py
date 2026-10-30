from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from tests.support.loopback import recording_service


@pytest.fixture
def service_server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    with recording_service() as served:
        yield served
