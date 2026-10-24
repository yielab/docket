"""The composition root builds each handle against a tmp home and calls through its source module."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.fakes import FakeJail

from docket import bootstrap
from docket.hops.application import driver as _driver
from docket.kernel.home import Home
from docket.kernel.ports import SandboxAvailability

SUBJECT = "docket.bootstrap"


@pytest.fixture
def home(tmp_path: Path) -> Home:
    return Home(tmp_path / "home")


def test_build_store_reads_and_writes_through_the_store_module(home: Home, tmp_path: Path) -> None:
    store = bootstrap.build_store(home)
    target = tmp_path / "doc.json"
    store.write_json(target, {"a": 1})
    assert store.read_json(target) == {"a": 1}
    assert store.read_modify_write(target, lambda d: {**d, "b": 2}) == {"a": 1, "b": 2}
    assert store.home is home


def test_build_sandbox_probes_only_when_asked(home: Home, fake_jail: FakeJail) -> None:
    probes: list[str | None] = []
    fake = SandboxAvailability(backend="none", docker=False)
    fake_jail.sandbox_availability = lambda choice=None: probes.append(choice) or fake
    sandbox = bootstrap.build_sandbox(home)
    assert probes == []
    assert sandbox.availability("auto") is fake
    assert probes == ["auto"]


def test_build_driver_is_the_process_wide_driver(home: Home) -> None:
    assert bootstrap.build_driver(home) is _driver.default_driver()


def test_build_channels_loads_the_catalog_on_demand(home: Home) -> None:
    channels = bootstrap.build_channels(home)
    assert channels.catalog().get("console") is not None
    assert channels.unreached_warning() is None or isinstance(channels.unreached_warning(), str)


def test_build_app_carries_every_handle(home: Home) -> None:
    app = bootstrap.build_app(home)
    assert app.home is home
    assert app.store.home is home
    assert app.sandbox.home is home
    assert app.channels.home is home
    assert app.driver is _driver.default_driver()


def test_build_server_defaults_and_pinned_token(
    home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SERVE_TOKEN", "pinned")
    plan = bootstrap.build_server(home)
    assert (plan.port, plan.bind, plan.interval) == (7331, "127.0.0.1", 30)
    assert (plan.dispatch, plan.telegram, plan.token_file) == (False, False, None)
    assert plan.token == "pinned"


def test_build_server_mints_a_fresh_token_per_plan(
    home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOCKET_SERVE_TOKEN", raising=False)
    first = bootstrap.build_server(home, port=0, dispatch=True, token_file="t")
    second = bootstrap.build_server(home)
    assert first.token != second.token
    assert len(first.token) >= 32
    assert (first.port, first.dispatch, first.token_file) == (0, True, "t")
