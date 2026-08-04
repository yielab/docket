"""Shared pytest fixtures for the docket Python suite.

There is no external daemon, no `openclaw` binary, no `openclaw.json`, and no
ACL module to isolate around. Every fixture below isolates docket's own state
instead (fleet.json, the `DOCKET_HOME`-derived registries, docket-owned
secrets).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import secrets as _secrets


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
def _isolate_fleet_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default FLEET_FILE to an ephemeral path for every test.

    ``DOCKET_HOME`` (fleet.json's home) is not implicitly isolated by
    repointing some other directory for hermeticity. The fleet read/write API
    lives in ``core/fleet.py``, which reads ``_cfg.FLEET_FILE`` fresh on
    every call, never a module-level rebound copy -- so patching
    ``_cfg.FLEET_FILE`` alone is sufficient, there is no second module to
    patch. A test that wants a specific fleet.json still repoints
    ``_cfg.FLEET_FILE`` itself, which simply overrides this default.
    """
    monkeypatch.setattr(_cfg, "FLEET_FILE", tmp_path / "_autouse_fleet.json", raising=True)


@pytest.fixture(autouse=True)
def _isolate_secrets_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default docket's secrets store to an ephemeral path.

    ``core/secrets.py`` reads ``SECRETS_FILE``/``SECRETS_META_FILE`` as
    module-level constants computed once at import (``DOCKET_HOME /
    "secrets.json"`` etc.), not through ``_cfg`` at call time -- so isolating
    them means patching the ``core.secrets`` module's own attributes
    directly.
    """
    monkeypatch.setattr(_secrets, "SECRETS_FILE", tmp_path / "_autouse_secrets.json", raising=True)
    monkeypatch.setattr(
        _secrets, "SECRETS_META_FILE", tmp_path / "_autouse_secrets_meta.json", raising=True
    )


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
    ("POLICIES_DIR", "policies"),
    ("SESSIONS_DIR", "sessions"),
    ("PORT_ALLOC_FILE", "port-allocations.json"),
    ("CONVERSATIONS_FILE", "docket-conversations.json"),
    ("SCHEDULE_FILE", "docket-schedules.json"),
    ("RUNS_FILE", "docket-runs.json"),
    ("MCP_SERVERS_FILE", "docket-mcp-servers.json"),
    ("TELEGRAM_OFFSET_FILE", "docket-telegram-offset.json"),
    ("MODEL_REGISTRY_FILE", "docket-models.json"),
    ("ARCHETYPE_REGISTRY_FILE", "docket-roles.json"),
    ("PROJECTS_DIR", "workspaces/projects"),
    ("AUDIT_LOG", "audit.log"),
    ("WORKSPACES_DIR", "workspaces"),
    ("PODS_DIR", "workspaces/pods"),
)


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

    A test wanting a specific location still repoints the constant itself,
    which simply overrides this default.
    """
    home = tmp_path / "_autouse_docket_home"
    for attr, leaf in _DOCKET_HOME_PATHS:
        monkeypatch.setattr(_cfg, attr, home / leaf, raising=True)
