"""A folder pod under an enforced jail reads any public host; every other pod keeps its list."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.agent.ports import ToolCall
from docket.agent.tools.registry import ToolContext, dispatch_tool
from docket.hops.application import builtin_tools as _builtin_tools
from docket.hops.application import capabilities as _capabilities
from docket.platform import fetch as _fetch
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_provisioning as _pp

SUBJECT = "docket.hops.application.builtin_tools"


class _Response:
    status = 200
    headers: ClassVar[dict[str, str]] = {"Content-Type": "text/plain"}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read1(self, n: int) -> bytes:
        return b""


class _Opener:
    """Answers the public host without a socket; any other URL goes to the real opener, whose
    connector refuses a private address before it dials."""

    def __init__(self, opened: list[str], real: object) -> None:
        self._opened = opened
        self._real = real

    def open(self, request: object, timeout: float = 0) -> object:
        url = request.full_url  # type: ignore[attr-defined]
        if urllib.parse.urlsplit(url).hostname != "example.org":
            return self._real.open(request, timeout=timeout)  # type: ignore[attr-defined]
        self._opened.append(url)
        return _Response()


def _jail_on(bind_launcher: Callable[..., Launcher]) -> None:
    bind_launcher(landlock=True)
    _fleet.set_sandbox_isolation()


def _declare(project: str, hosts: str) -> None:
    _fleet.meta_set(_pod.member_id(project, "lead"), "fetchDomains", hosts)


def _tools(project: str, role: str) -> list[str]:
    return _capabilities.member_capabilities(project, role)["tools"]


def test_a_folder_pod_under_the_jail_with_no_list_reads_any_public_host(
    tmp_path: Path, bind_launcher: Callable[..., Launcher], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real_build = _fetch.build_opener
    monkeypatch.setattr(
        _fetch, "build_opener", lambda *a, **k: _Opener(opened, real_build(*a, **k))
    )
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _jail_on(bind_launcher)

        caps = _capabilities.member_capabilities("demo", "researcher")
        assert "fetch" in caps["tools"]
        assert caps["fetchDomains"] == ["*"]

        registry = _builtin_tools.builtin_registry("demo")
        context = ToolContext(agent_id="t", roots=(tmp_path,), role="researcher", project="demo")

        def fetch_of(url: str) -> object:
            call = ToolCall(id="c", name="fetch", arguments=json.dumps({"url": url}))
            return dispatch_tool(call, context, registry)

        assert fetch_of("https://example.org/").ok  # type: ignore[attr-defined]
        refused = fetch_of("http://127.0.0.1/")
        assert not refused.ok  # type: ignore[attr-defined]
        assert opened == ["https://example.org/"]


def test_the_send_role_of_that_pod_holds_no_fetch(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _jail_on(bind_launcher)

        assert "fetch" not in _tools("demo", "actor")


def test_without_the_jail_a_folder_pod_reads_no_host(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        bind_launcher(landlock=True)
        _pp.provision_pod("demo", "respond")

        assert "fetch" not in _tools("demo", "researcher")


def test_a_codebase_pod_under_the_jail_reads_no_host(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        _jail_on(bind_launcher)
        build_pod("repo", ("lead", "researcher"), codebase="/src/repo")

        assert "fetch" not in _tools("repo", "researcher")


def test_a_folder_pod_with_a_declared_list_reads_that_list_only(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _declare("demo", "docs.python.org")
        _jail_on(bind_launcher)

        caps = _capabilities.member_capabilities("demo", "researcher")
        assert caps["fetchDomains"] == ["docs.python.org"]


def test_a_folder_pod_that_denies_fetch_holds_none_under_the_jail(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("demo", "respond")
        _fleet.meta_set(_pod.member_id("demo", "lead"), "deniedTools", "fetch")
        _jail_on(bind_launcher)

        assert "fetch" not in _tools("demo", "researcher")
