"""Shared pytest fixtures for the docket Python suite.

There is no external daemon or compatibility layer to isolate around. The autouse fixture
below isolates Docket's own state instead (fleet.json, the `DOCKET_HOME`-derived registries,
docket-owned secrets) by running each test in a ``use_home`` block.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel.home import Home, use_home

_LANE_DURATION_CEILING_S = {"unit": 2.0, "guards": 2.0, "integration": 10.0}


def _lane_of(nodeid: str) -> str | None:
    parts = Path(nodeid.split("::", 1)[0]).parts
    if "tests" in parts:
        idx = parts.index("tests")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> object:
    """Fail the report when a test exceeds its lane's duration ceiling."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or report.failed:
        return
    lane = _lane_of(item.nodeid)
    ceiling = _LANE_DURATION_CEILING_S.get(lane) if lane else None
    if ceiling is not None and call.duration > ceiling:
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} took {call.duration:.2f}s, over the {ceiling:.0f}s {lane}/ ceiling"
        )


@pytest.fixture(autouse=True)
def _plain_typer_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer decides at import whether to force colour, from ``GITHUB_ACTIONS``/``FORCE_COLOR``,
    and Rich reads ``FORCE_COLOR`` itself, so on a CI runner usage errors and help arrive boxed
    in ANSI and no substring matches."""
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", None)
    monkeypatch.delenv("FORCE_COLOR", raising=False)


@pytest.fixture(autouse=True)
def _keep_pytest_dumpable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-process turn must not make the pytest process non-dumpable for every later test;
    the real flag is exercised in a subprocess (``test_process_non_dumpable.py``)."""
    from docket.platform import process as _process

    monkeypatch.setattr(_process, "make_non_dumpable", lambda: None, raising=True)


@pytest.fixture(autouse=True)
def _isolate_docket_home(tmp_path: Path) -> Iterator[None]:
    """Run every test in a home of its own under ``tmp_path``.

    **Measured, not assumed:** with only ``FLEET_FILE`` isolated, a full ``uv run pytest``
    wrote real approval records, trace JSONL, ``docket-conversations.json`` and
    ``port-allocations.json`` into the developer's actual ``~/.docket`` (verified by
    snapshotting the directory either side of a run). ``audit.log`` has no environment kill
    switch either, and some paths have no override at all, so a test cannot opt out of the real
    path even deliberately; that is what makes this an autouse default rather than each test's
    responsibility.

    A test wanting a specific location wraps its body in ``use_home(Home(path))``, which
    replaces this default for the block. The fleet file stays beside the home, at the leaf it
    has always had here.
    """
    home = Home(
        tmp_path / "_autouse_docket_home", fleet_file_override=tmp_path / "_autouse_fleet.json"
    )
    with use_home(home):
        yield


def register_local_provider(
    home: Path,
    name: str,
    models: list[dict[str, object]],
    base_url: str = "http://127.0.0.1:9999/v1",
) -> None:
    """Write a keyless loopback provider document into *home*'s global catalog."""
    from docket.models import catalog as _provider

    with use_home(Home(home)):
        _provider.save_provider(
            _provider.ProviderSpec.model_validate(
                {
                    "name": name,
                    "baseUrl": base_url,
                    "auth": {"type": "none"},
                    "local": True,
                    "models": models,
                }
            )
        )


def record_isolation_off(home: Path) -> None:
    """Record an explicit isolation off in *home*'s fleet.json, merging into any existing file."""
    _record_isolation_mode(home, "off")


def record_isolation_on(home: Path) -> None:
    """Record `docket setup sandbox on` in *home*'s fleet.json, merging into any existing file."""
    _record_isolation_mode(home, "non-main")


def _record_isolation_mode(home: Path, mode: str) -> None:
    import json

    home.mkdir(parents=True, exist_ok=True)
    path = home / "fleet.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data.setdefault("security", {})["isolationMode"] = mode
    path.write_text(json.dumps(data))
    path.chmod(0o600)
