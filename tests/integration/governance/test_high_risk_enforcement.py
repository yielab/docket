"""High-risk classes enforced on docket-launched processes.
``governance/security.py``'s ``HIGH_RISK_PATTERNS`` classifier, called only from tests, would be
documentation, not enforcement. ``match_high_risk`` is wired into the in-turn gate and into
``run_command``, the one path docket itself launches. Covers: TestRunVerifyCmdHighRisk (``run_command`` is the one docket-launched
subprocess built from a free-form, operator-composed shell command, unlike every other call in
that module's fixed argv lists; a high-risk match fails closed, the shell command never
starts).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home

from docket.kernel.ports import jail as _jail

_hermetic = _support_home.hermetic

SUBJECT = "docket.governance.security"

# ── system adapter: run_command's own high-risk guard ─────────────────────


class TestRunVerifyCmdHighRisk:
    def test_money_movement_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        code, output = _jail.run_command("stripe charge customer --amount 500", str(tmp_path))
        assert code is None
        assert "money-movement" in output
        assert "docket setup sandbox classes" in output

    def test_prod_deploy_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        code, output = _jail.run_command("git push origin production", str(tmp_path))
        assert code is None
        assert "prod-deploy" in output

    def test_secret_access_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        code, output = _jail.run_command("ssh-keygen -t ed25519 -N ''", str(tmp_path))
        assert code is None
        assert "secret-access" in output

    def test_ordinary_verify_pipeline_is_unaffected(self, tmp_path: Path) -> None:
        """A realistic multi-command verify pipeline is not a false positive."""
        code, output = _jail.run_command("echo building; echo testing && echo done", str(tmp_path))
        assert code == 0
        assert "done" in output
