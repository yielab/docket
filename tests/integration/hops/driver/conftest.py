"""Fixtures shared by the docket-driver tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.home import record_isolation_off

from docket.kernel.home import Home, current_home, use_home


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    with (
        use_home(Home(tmp_path / "docket")),
        use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)),
    ):
        # DOCKET_SANDBOX_BACKEND leaking in from the real dev/CI environment would
        # make TestIsolationWiring's "no backend available" cases flaky -- start
        # every test from the same clean slate and let individual tests opt in.
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        # These turns are about the driver, not the jail: record the explicit opt-out so they do
        # not depend on the host having a sandbox backend (a stock macOS runner has neither).
        # TestIsolationWiring records its own choice, or clears it to test the default.
        record_isolation_off(tmp_path / "docket")
        yield


@pytest.fixture(autouse=True)
def _no_endpoint_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A catalog row, not an environment override, picks the endpoint of these turns."""
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
