"""The composition root: `Home` in, wired objects out.

Plain `build_*` functions, no framework and no registry. `interfaces/` is the only caller:
`__main__` builds the CLI's `App` once and `run_serve` builds the server's `ServerPlan` once.
Every handle calls through its source module at use time (``_store.read_json(...)``), never a
name bound at import, so a test that patches the source module still lands, and building a
handle does no I/O, no host probe and no catalog load. The state a handle serves still comes
from `current_home()` underneath; the `Home` a handle carries names which home it was built for."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.agent.ports import bind_role_composer, bind_tool_gate
from docket.governance import gate as _gate
from docket.governance import security as _security
from docket.governance.ports import bind_approval_escalations, bind_approval_follow_up
from docket.hops.application import driver as _driver
from docket.kernel.home import Home, current_home
from docket.kernel.ports import (
    SandboxAvailability,
    bind_git,
    bind_jail,
    bind_process,
    bind_records,
    bind_tracer,
)
from docket.kernel.ports import jail as _jail
from docket.kernel.records_port import RecordStore
from docket.models import catalog as _catalog
from docket.models.adapters import openai_http as _openai_http
from docket.models.ports import bind_endpoint_prober
from docket.observability.adapters import otlp_http as _otlp_http
from docket.observability.adapters.local_tracer import LocalTracer
from docket.operator import adapters as _channel_adapters
from docket.operator import channel as _channel
from docket.operator.ports import bind_task_reader
from docket.platform import git as _git_adapter
from docket.platform import process as _process_adapter
from docket.platform import store as _store
from docket.platform.records_sqlite import SqliteRecordStore
from docket.sandbox.launch import Launcher
from docket.tasks.application import actions as _actions
from docket.tasks.application import escalations as _escalations
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams.ports import bind_channel_documents
from docket.teams.role_composer import TeamsRoleComposer

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# The concrete adapters the CLI and the server reach for but may not import themselves.
otlp_http = _otlp_http


def sink_for(spec: _channel.ChannelSpec) -> _channel_adapters.Deliver | None:
    """The delivery function of *spec*'s dialect, or None when no dialect is wired for it."""
    return _channel_adapters.sink_for(spec)


class _QueueTaskReader:
    """The operator's view of a pod's queue: every task as its stored JSON."""

    def read_tasks(self, project: str) -> list[dict[str, Any]]:
        return [
            r.model_dump(by_alias=True, mode="json") for r in TaskRepository.for_pod(project).list()
        ]


def _open_records(project: str) -> RecordStore:
    """The records backend of a pod; the one place a backend is chosen."""
    return SqliteRecordStore(current_home().pod_records_path(project))


def bind_adapters() -> None:
    """Bind the real adapters of every port; every entry calls this before it runs."""
    bind_role_composer(TeamsRoleComposer())
    bind_tool_gate(_gate)
    bind_tracer(LocalTracer())
    bind_approval_follow_up(_actions)
    bind_approval_escalations(_escalations)
    bind_task_reader(_QueueTaskReader())
    bind_endpoint_prober(_openai_http)
    bind_channel_documents(_channel)
    bind_git(_git_adapter)
    bind_process(_process_adapter)
    bind_records(_open_records)
    bind_jail(
        Launcher(
            recorded_backend=_fleet.get_sandbox_backend,
            credential_source=_catalog.credential_sources,
            high_risk=_security.match_high_risk,
        )
    )


@dataclass(frozen=True)
class Store:
    """The atomic, locked JSON store for one home."""

    home: Home

    def read_json(self, path: Path) -> dict[str, Any]:
        return _store.read_json(path)

    def write_json(self, path: Path, data: dict[str, Any]) -> None:
        _store.write_json(path, data)

    def read_modify_write(
        self, path: Path, fn: Callable[[dict[str, Any]], dict[str, Any] | None]
    ) -> dict[str, Any]:
        return _store.read_modify_write(path, fn)


@dataclass(frozen=True)
class Sandbox:
    """The jail backends of this host, probed when asked and never at build time."""

    home: Home

    def availability(self, choice: str | None = None) -> SandboxAvailability:
        return _jail.sandbox_availability(choice)


@dataclass(frozen=True)
class Channels:
    """The merged notification channel catalog of one home, loaded when asked."""

    home: Home

    def catalog(self) -> _channel.Catalog:
        return _channel.load_catalog()

    def unreached_warning(self) -> str | None:
        """The warning for a home whose enabled channels deliver nowhere, or None."""
        return _channel.unreached_warning(self.catalog().delivering())


@dataclass(frozen=True)
class App:
    """Everything the CLI reaches for, carried as the Click context object."""

    home: Home
    store: Store
    sandbox: Sandbox
    driver: _driver.DocketDriver
    channels: Channels


@dataclass(frozen=True)
class ServerPlan:
    """What `docket start` runs: the listen options, the bearer token and the collaborators."""

    home: Home
    port: int
    bind: str
    interval: int
    dispatch: bool
    telegram: bool
    token: str
    token_file: str | None
    store: Store
    driver: _driver.DocketDriver
    channels: Channels


def build_store(home: Home) -> Store:
    return Store(home)


def build_sandbox(home: Home) -> Sandbox:
    return Sandbox(home)


def build_driver(home: Home) -> _driver.DocketDriver:
    """The process-wide driver (``agent.driver.default_driver``): stateless, one shared instance."""
    return _driver.default_driver()


def build_channels(home: Home) -> Channels:
    return Channels(home)


def build_app(home: Home) -> App:
    bind_adapters()
    return App(
        home=home,
        store=build_store(home),
        sandbox=build_sandbox(home),
        driver=build_driver(home),
        channels=build_channels(home),
    )


def build_server(
    home: Home,
    *,
    port: int | None = None,
    bind: str = "127.0.0.1",
    interval: int = DEFAULT_INTERVAL,
    dispatch: bool = False,
    telegram: bool = False,
    token_file: str | None = None,
) -> ServerPlan:
    """The bearer token is ``DOCKET_SERVE_TOKEN`` when set, else a fresh random one."""
    bind_adapters()
    token = os.environ.get("DOCKET_SERVE_TOKEN") or secrets.token_urlsafe(32)
    return ServerPlan(
        home=home,
        port=DEFAULT_PORT if port is None else port,
        bind=bind,
        interval=interval,
        dispatch=dispatch,
        telegram=telegram,
        token=token,
        token_file=token_file,
        store=build_store(home),
        driver=build_driver(home),
        channels=build_channels(home),
    )
