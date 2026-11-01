"""The composition root builds each handle against a tmp home and calls through its source module."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tests.support.fakes import FakeJail

from docket import bootstrap
from docket.hops.application import driver as _driver
from docket.kernel.errors import InvalidInput
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


def test_build_server_defaults_and_pinned_token(home: Home) -> None:
    plan = bootstrap.build_server(replace(home, serve_token="pinned"))
    assert (plan.port, plan.bind, plan.interval) == (7331, "127.0.0.1", 30)
    assert (plan.dispatch, plan.telegram, plan.token_file) == (False, False, None)
    assert plan.token == "pinned"


def test_build_server_mints_a_fresh_token_per_plan(home: Home) -> None:
    first = bootstrap.build_server(home, port=0, dispatch=True, token_file="t")
    second = bootstrap.build_server(home)
    assert first.token != second.token
    assert len(first.token) >= 32
    assert (first.port, first.dispatch, first.token_file) == (0, True, "t")


def test_build_server_carries_the_homes_read_token(home: Home) -> None:
    plan = bootstrap.build_server(replace(home, serve_token="pinned", serve_read_token="reader"))
    assert (plan.token, plan.read_token) == ("pinned", "reader")
    assert bootstrap.build_server(home).read_token == ""


def test_resolve_serve_tokens_keeps_a_distinct_read_token() -> None:
    assert bootstrap.resolve_serve_tokens("pinned", "") == ("pinned", "")
    assert bootstrap.resolve_serve_tokens("pinned", "reader") == ("pinned", "reader")
    random_token, read = bootstrap.resolve_serve_tokens("", "reader")
    assert len(random_token) >= 32 and read == "reader"


def test_resolve_serve_tokens_refuses_a_read_token_equal_to_the_serve_token() -> None:
    with pytest.raises(InvalidInput, match="DOCKET_SERVE_READ_TOKEN"):
        bootstrap.resolve_serve_tokens("same", "same")
