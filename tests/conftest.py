"""Shared pytest fixtures for the docket Python suite.

There is no external daemon or compatibility layer to isolate around. Every fixture below
isolates Docket's own state
instead (fleet.json, the `DOCKET_HOME`-derived registries, docket-owned
secrets).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.kernel.home as _home
from docket.kernel.home import Home, current_home, use_home

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
def _isolate_audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default AUDIT_LOG to an ephemeral path for every test.

    ``core/audit.py`` has no environment kill switch — best-effort recording
    always happens — so a test that exercises
    a mutating code path but forgets to repoint ``_cfg.AUDIT_LOG`` at its own
    sandbox would otherwise append real entries to the developer's actual
    ``~/.docket/audit.log``. This applies to every test by default; a test
    that wants to inspect audit output still repoints ``_cfg.AUDIT_LOG`` to
    its own fixture-managed directory, which simply overrides this default.
    """
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "_autouse_audit.log", raising=True)


@pytest.fixture(autouse=True)
def _isolate_fleet_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Safety net: default FLEET_FILE to an ephemeral path for every test.

    ``DOCKET_HOME`` (fleet.json's home) is not implicitly isolated by
    repointing some other directory for hermeticity. The fleet read/write API
    lives in ``core/fleet.py``, which reads ``_cfg.FLEET_FILE`` fresh on
    every call, never a module-level rebound copy -- so patching
    ``_cfg.FLEET_FILE`` alone is sufficient, there is no second module to
    patch. A test that wants a specific fleet.json still repoints
    ``_cfg.FLEET_FILE`` itself, which simply overrides this default.
    """
    with use_home(
        dataclasses.replace(current_home(), fleet_file_override=tmp_path / "_autouse_fleet.json")
    ):
        yield


@pytest.fixture(autouse=True)
def _keep_pytest_dumpable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-process turn must not make the pytest process non-dumpable for every later test;
    the real flag is exercised in a subprocess (``test_process_non_dumpable.py``)."""
    from docket.edges.adapters import system as _system

    monkeypatch.setattr(_system, "make_non_dumpable", lambda: None, raising=True)


# Every ``DOCKET_HOME``-derived path, and the config attribute each is read
# through at call time. Nothing under ``src/docket/`` binds these at import
# (no ``from docket.config import TRACES_DIR`` etc.), so patching the config
# module alone is sufficient -- ``FLEET_FILE`` above is the one exception
# noted in its own fixture's docstring.
#
# ``AUDIT_LOG`` already has its own dedicated ``_isolate_audit_log`` fixture
# above; it is listed here too so ``test_docket_home_isolation.py``'s
# source-scanning guard (which does not know about that separate fixture)
# stays green. Both fixtures isolate it to a safe tmp path, so the
# redundancy is harmless.
_DOCKET_HOME_PATHS: tuple[tuple[str, str], ...] = (
    ("TRACES_DIR", "traces"),
    ("APPROVALS_DIR", "approvals"),
    ("CORRECTIONS_DIR", "corrections"),
    ("CONSULT_PARKED_DIR", "consult-parked"),
    ("POLICIES_DIR", "policies"),
    ("PLUGINS_DIR", "plugins"),
    ("SKILLS_DIR", "skills"),
    ("SESSIONS_DIR", "sessions"),
    ("PORT_ALLOC_FILE", "port-allocations.json"),
    ("CONVERSATIONS_FILE", "docket-conversations.json"),
    ("SCHEDULE_FILE", "docket-schedules.json"),
    ("RUNS_FILE", "docket-runs.json"),
    ("SERVE_PID_FILE", "serve.pid"),
    ("MCP_SERVERS_FILE", "docket-mcp-servers.json"),
    ("PROVIDERS_FILE", "docket-providers.json"),
    ("PROVIDER_MODELS_FILE", "provider-models.json"),
    ("EXPORTERS_FILE", "docket-exporters.json"),
    ("EXPORTERS_HEALTH_FILE", "exporters-health.json"),
    ("CHANNELS_FILE", "docket-channels.json"),
    ("NOTIFY_STATE_FILE", "notify-state.json"),
    ("CHANNELS_HEALTH_FILE", "channels-health.json"),
    ("TELEGRAM_OFFSET_FILE", "docket-telegram-offset.json"),
    ("REVIEWED_REPOS_FILE", "reviewed-repos.json"),
    ("INBOX_CURSOR_FILE", "inbox-cursor.json"),
    ("MODEL_REGISTRY_FILE", "docket-models.json"),
    ("PROJECTS_DIR", "workspaces/projects"),
    ("AUDIT_LOG", "audit.log"),
    ("WORKSPACES_DIR", "workspaces"),
    ("JAIL_TMP_DIR", "jail-tmp"),
    ("PREPARE_CACHE_DIR", "cache/prepare"),
    ("PODS_DIR", "workspaces/pods"),
)


# The single shared way for a test to isolate a *specific* home directory it
# controls, instead of declaring its own partial copy of _DOCKET_HOME_PATHS --
# a local subset silently stops tracking that tuple the moment a new constant
# is added there, with nothing to fail. DOCKET_HOME and FLEET_FILE are set
# explicitly because neither is in _DOCKET_HOME_PATHS (DOCKET_HOME is the
# tuple's input, not a derived path, and FLEET_FILE has its own dedicated
# _isolate_fleet_file fixture). The kernel Home (what core/secrets.py reads) is
# named explicitly too: it does not follow config.DOCKET_HOME, so a test that
# repoints to its own chosen home must move it with the rest of the constants,
# or the secrets store would silently keep pointing at the autouse fixtures'
# home -- a home split in two with nothing to fail.
def point_home_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Make *root* the root of the process-default kernel Home, for a test that cannot wrap
    its body in ``use_home``. A ``use_home`` block still wins over it."""
    monkeypatch.setattr(
        _home, "_DEFAULT", dataclasses.replace(_home.current_home(), root=root), raising=True
    )


def patch_home(monkeypatch: pytest.MonkeyPatch, **fields: object) -> None:
    """Set *fields* on the process-default kernel Home for this test, the way a ``Home``
    override is set in production. Use ``use_home`` when the test body can sit in a block."""
    monkeypatch.setattr(
        _home, "_DEFAULT", dataclasses.replace(_home.current_home(), **fields), raising=True
    )


def repoint_docket_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point every DOCKET_HOME-derived constant at *home*."""
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    point_home_at(monkeypatch, home)
    for attr, leaf in _DOCKET_HOME_PATHS:
        monkeypatch.setattr(_cfg, attr, home / leaf, raising=True)


@pytest.fixture(autouse=True)
def _isolate_docket_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default every ``DOCKET_HOME``-derived path to a tmp dir.

    Same reasoning as ``_isolate_fleet_file`` above, which covered exactly one
    of the constants that changed meaning. **Measured, not assumed:** with
    only ``FLEET_FILE`` isolated, a full ``uv run pytest`` wrote real approval
    records, trace JSONL, ``docket-conversations.json`` and
    ``port-allocations.json`` into the developer's actual ``~/.docket``
    (verified by snapshotting the directory either side of a run).

    Two of these constants -- ``PORT_ALLOC_FILE`` and ``CONVERSATIONS_FILE``
    -- have no environment override at all, so a test cannot opt out of the
    real path even deliberately; that is what makes this an autouse default
    rather than each test's responsibility.

    A test wanting a specific location still repoints the constant itself
    (see ``repoint_docket_home`` above), which simply overrides this default.
    """
    home = tmp_path / "_autouse_docket_home"
    for attr, leaf in _DOCKET_HOME_PATHS:
        monkeypatch.setattr(_cfg, attr, home / leaf, raising=True)
    point_home_at(monkeypatch, home)


def register_local_provider(
    home: Path,
    name: str,
    models: list[dict[str, object]],
    base_url: str = "http://127.0.0.1:9999/v1",
) -> None:
    """Write a keyless loopback provider document into *home*'s global catalog."""
    from docket.core import provider as _provider

    with pytest.MonkeyPatch.context() as mp:
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
