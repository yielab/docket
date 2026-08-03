"""Shared pytest fixtures for the docket Python suite.

The OpenClaw daemon is an external dependency docket shells out to; CI does not
install it. Rather than monkeypatch docket's *own* dependency/health code (which
would bypass the very logic under test), we put a minimal **real** `openclaw`
executable on PATH so probes like ``shutil.which("openclaw")`` and
``openclaw --version`` run their real code paths against a real binary. Only the
daemon's *state-mutating* CLI calls (which would need a running daemon) are stubbed
at the ACL boundary by individual tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import docket.config as _cfg


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default AUDIT_LOG to an ephemeral path for every test.

    ``core/audit.py`` no longer has an environment kill switch (G-4) — best-
    effort recording now genuinely always happens — so a test that exercises
    a mutating code path but forgets to repoint ``_cfg.AUDIT_LOG`` at its own
    sandbox would otherwise append real entries to the developer's actual
    ``~/.openclaw/audit.log``. This applies to every test by default; a test
    that wants to inspect audit output still repoints ``_cfg.AUDIT_LOG`` to
    its own fixture-managed directory, which simply overrides this default.
    """
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "_autouse_audit.log", raising=True)


@pytest.fixture(autouse=True)
def _isolate_fleet_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: default FLEET_FILE to an ephemeral path for every test.

    ROADMAP Phase 19 P19-6 decoupled ``DOCKET_HOME`` (fleet.json's home) from
    ``OPENCLAW_DIR`` -- pre-P19-6, a test that repointed ``OPENCLAW_DIR``/
    ``CONFIG_FILE`` for hermeticity got fleet-registry isolation "for free"
    (docket-models.json etc. still don't). Since the two are independent now,
    the same test would otherwise read/write the developer's real
    ``~/.docket/fleet.json`` -- or worse, leak agent-registration state
    between unrelated tests that happen to share that real default path.
    Mirrors ``_isolate_audit_log`` above for the identical reason; a test
    that wants a specific fleet.json still repoints ``_cfg.FLEET_FILE`` (and
    ``edges.adapters.openclaw.FLEET_FILE``, bound at import time) itself,
    which simply overrides this default.
    """
    fleet_file = tmp_path / "_autouse_fleet.json"
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file, raising=True)
    from docket.edges.adapters import openclaw as _oc

    monkeypatch.setattr(_oc, "FLEET_FILE", fleet_file, raising=True)


def write_fake_openclaw(bindir: Path) -> Path:
    """Write a minimal `openclaw` shim that answers the read-only probes docket
    makes during install/doctor (``--version``; everything else exits 0)."""
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "openclaw"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args[:1] == ['--version']:\n"
        "    print('openclaw 2026.2.23 (test shim)')\n"
        "sys.exit(0)\n"
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_openclaw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Prepend a real (shim) `openclaw` binary to PATH.

    Lets dependency/version/health checks execute their real code instead of
    being stubbed — they pass because they genuinely find an `openclaw` on PATH,
    which is the honest analogue of a machine that has the daemon installed.
    Returns the bin directory so a test can remove it to assert the absent case.
    """
    bindir = tmp_path / "_ocbin"
    write_fake_openclaw(bindir)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return bindir
