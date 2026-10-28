"""Shared home helpers and fixtures for the docket suite."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from docket.interfaces.cli.commands import contract as _contract
from docket.kernel.home import Home, current_home, reset_default, use_home

FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100123"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
}


API_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "apitest"}],
    "bindings": [],
    "security": {"gatesEnabled": False, "isolationEnabled": False},
    "defaults": {"model": ""},
}


API_META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "Api Test Agent",
    "scope": "project",
    "model": "anthropic/claude-haiku-4-5-20251001",
    "budgetUsd": "5.0",
}


@pytest.fixture(autouse=True)
def hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield


@pytest.fixture(autouse=True)
def trace_on_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


@pytest.fixture(autouse=True)
def hermetic_trace_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        yield


@pytest.fixture(autouse=True)
def hermetic_no_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(_contract, "is_tty", lambda: False)
    home = tmp_path / "home"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        yield home


@pytest.fixture(autouse=True)
def hermetic_no_approval_wait(tmp_path: Path) -> Iterator[None]:
    with (
        use_home(Home(tmp_path)),
        use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)),
    ):
        yield


@pytest.fixture(autouse=True)
def isolate_stores(tmp_path: Path) -> Iterator[None]:
    with use_home(Home(tmp_path / "docket")):
        record_isolation_off(tmp_path / "docket")
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            yield


@pytest.fixture()
def runs_file(tmp_path: Path) -> Iterator[Path]:
    f = tmp_path / "docket-runs.json"
    with use_home(dataclasses.replace(current_home(), runs_file_override=f)):
        yield f


@pytest.fixture(autouse=True)
def isolate_gates(tmp_path: Path) -> Iterator[None]:
    """Tests here call `dispatch_tool` directly, which consults `governance/policy.py` and
    `governance/approval.py` -- point both at an ephemeral, empty directory so this file never reads a
    developer's real ``~/.docket/policies`` or blocks on an approval nothing will grant."""
    with use_home(
        dataclasses.replace(
            current_home(),
            policies_dir_override=tmp_path / "_policies",
            approvals_dir_override=tmp_path / "_approvals",
            tool_approval_timeout=0,
        )
    ):
        yield


@pytest.fixture(autouse=True)
def isolate_sessions_dir(tmp_path: Path) -> Iterator[None]:
    with use_home(dataclasses.replace(current_home(), sessions_dir_override=tmp_path / "sessions")):
        yield


@pytest.fixture()
def approvals_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "approvals"
    d.mkdir()
    with use_home(dataclasses.replace(current_home(), approvals_dir_override=d)):
        yield d


@contextmanager
def home(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    with use_home(Home(home)):
        yield home


@contextmanager
def point_config_at(
    home: Path,
) -> Iterator[None]:
    """Repoint the already-imported config module at a temp DOCKET_HOME."""
    with use_home(Home(home)):
        yield


def global_providers(home: Path) -> dict[str, dict[str, object]]:
    path = Home(home).providers_file
    if not path.exists():
        return {}
    providers: dict[str, dict[str, object]] = json.loads(path.read_text())["providers"]
    return providers


@pytest.fixture()
def fake_home(tmp_path: Path) -> Iterator[Path]:
    """Seed a temp DOCKET_HOME with one project agent + fleet.json."""
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    session = home / "sessions" / "agent%3Amyshop%3Amyshop"
    session.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "sessionKey": "agent:myshop:myshop",
                "created": "2026-06-19T08:00:00Z",
                "updated": "2026-06-20T09:30:00Z",
                "messages": [],
            }
        )
    )
    (home / "fleet.json").write_text(json.dumps(FLEET_CONFIG))

    with use_home(Home(home)):
        yield home


@pytest.fixture()
def api_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / "apitest"
    ws.mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(API_META))

    (home / "fleet.json").write_text(json.dumps(API_FLEET_CONFIG))

    # repoint_docket_home points APPROVALS_DIR at home/"approvals" without
    # creating it, so list_pending() still returns [] gracefully.
    with use_home(Home(home)):
        yield home


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


@pytest.fixture(autouse=True)
def fresh_default() -> Iterator[None]:
    """Each test starts and ends with an unset default home."""
    reset_default()
    yield
    reset_default()


@pytest.fixture()
def schedule_file(tmp_path: Path) -> Iterator[Path]:
    f = tmp_path / "docket-schedules.json"
    with use_home(
        dataclasses.replace(
            current_home(),
            schedule_file_override=f,
            runs_file_override=tmp_path / "docket-runs.json",
        )
    ):
        yield f
