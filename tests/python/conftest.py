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
