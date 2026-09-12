"""gates, policies, approve, deny commands.

Drives the four CLI run_* surfaces (and the core engines behind them) in-process
against a temp DOCKET_HOME. config.py binds paths at import time, so we repoint
the live module attributes (the same technique as the doctor and trace/audit
suites). The `docker` binary is stubbed off PATH so isolation reports "needs
Docker".

There is no daemon and no exec-approvals.json file format -- `docket gates
enable/disable` only flips fleet.json's approval-routing state (see
cli/_gates.py); there is no daemon config to write.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _approve, _deny, _gates, _policies
from docket.core import approval as _ap
from docket.core import policy as _policy
from docket.core import security as _sec

# Agent registration + channel bindings + gates/isolation flags live in
# fleet.json.
_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}, {"id": "content"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100"}
    ],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp DOCKET_HOME with config paths repointed; docker stubbed off PATH."""
    d = tmp_path / ".docket"
    (d / "policies").mkdir(parents=True)
    (d / "approvals").mkdir(parents=True)
    fleet_file = d / "fleet.json"
    fleet_file.write_text(json.dumps(_FLEET_CONFIG))
    fleet_file.chmod(0o600)

    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", fleet_file, raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", d / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    # audit_log() has no kill switch — repoint it explicitly rather than
    # relying only on the conftest-wide safety net, matching this fixture's
    # own pattern of repointing every config path it touches.
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    # Never touch systemctl.
    # Stub `docker` off PATH so isolation reports "needs Docker". Real
    # binaries (git, python3, ...) pass.
    real_which = shutil.which

    def fake_which(name: str, *a: Any, **k: Any) -> str | None:
        if name == "docker":
            return None
        return real_which(name, *a, **k)

    monkeypatch.setattr(_gates.shutil, "which", fake_which)
    monkeypatch.setattr(shutil, "which", fake_which)
    return d


def _seed_policies(oc_dir: Path) -> None:
    """Copy the shipped baseline policy templates into the temp POLICIES_DIR."""
    for f in _cfg.policy_templates_dir().glob("*.json"):
        shutil.copy(f, oc_dir / "policies" / f.name)


# ── high-risk action classes ─────────────────────────────────────────────────────


class TestHighRiskPatterns:
    def test_prod_deploy_matches_git_push_production(self) -> None:
        cls = _sec.match_high_risk("git push origin production")
        assert cls is not None
        assert cls.name == "prod-deploy"

    def test_prod_deploy_matches_npm_publish(self) -> None:
        assert _sec.match_high_risk("npm publish --access public") is not None

    def test_money_movement_matches_stripe(self) -> None:
        assert _sec.match_high_risk("stripe charge customer") is not None

    def test_secret_access_matches_ssh_keygen(self) -> None:
        assert _sec.match_high_risk("ssh-keygen -t ed25519") is not None

    def test_non_matching_command_is_not_high_risk(self) -> None:
        assert _sec.match_high_risk("ls -la") is None
        assert _sec.match_high_risk("git status") is None

    def test_git_and_npm_are_the_bins_with_an_attached_class(self) -> None:
        # The attached-bin set is read straight off HIGH_RISK_PATTERNS. It used
        # to come from a `high_risk_bins()` helper, deleted because it had no
        # production caller: `docket gates classes` walks `cls.bins`
        # itself and nothing else ever wanted the flattened set.
        bins = {name for cls in _sec.HIGH_RISK_PATTERNS for name in cls.bins}

        assert "git" in bins
        assert "npm" in bins
        assert "ls" not in bins


# resolve_safe_bin_paths()/build_exec_approvals() no longer exist: they
# seeded the daemon's own exec-approvals.json allowlist file, a file format
# that is gone along with the daemon. No successor: docket's own gate
# (pre_tool_call + classify_command) is argument-aware and always active; it
# does not need a seeded bin allowlist.


# ── gates ─────────────────────────────────────────────────────────────────────


class TestGatesStatus:
    def test_status_unset(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing: not configured" in out
        assert "Workspace isolation: not configured" in out

    def test_status_always_reports_the_gate_active(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # There is no daemon gate report to query -- docket's own tool-call
        # gate (pre_tool_call + classify_command) is unconditionally active,
        # and `docket gates status` says so regardless of routing/isolation
        # configuration.
        rc = _gates.run_gates("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "always active" in out.lower()

    def test_status_after_enable_reports_routing_on(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing: on (mode=session)" in out


class TestGatesEnableDisable:
    """`docket gates enable/disable` does not seed a daemon exec-approvals.json
    allowlist (that file format is gone along with the daemon) -- it only
    flips fleet.json's approval-routing state. There is no existing-config
    distinction left to force over, so there is no idempotent/--force test
    here asserting on repeated exec-approvals.json writes.
    """

    def test_enable_turns_on_routing(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("enable")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing on (mode=session)" in out
        # Routing wired; myshop has a telegram binding → count >= 1.
        assert "1 channel-bound agent" in out
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["approvalRoutingState"] == "on"
        assert fleet["security"]["approvalRoutingMode"] == "session"

    def test_enable_is_idempotent(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("enable")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing on (mode=session)" in out
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["approvalRoutingState"] == "on"

    def test_disable_resets_routing(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("disable")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing off" in out
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["approvalRoutingState"] == "off"


class TestGatesClasses:
    def test_classes_lists_all_patterns(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("classes")
        out = capsys.readouterr().out
        assert rc == 0
        for cls in _sec.HIGH_RISK_PATTERNS:
            assert cls.name in out
            assert cls.description in out
        assert "not yet user-configurable" in out

    def test_classes_shows_overlapping_bins(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("classes")
        out = capsys.readouterr().out
        assert rc == 0
        assert "git" in out
        assert "stay allowlisted" in out or "classify_command reads the" in out
        assert "npm" in out


class TestGatesIsolate:
    def test_isolate_on_needs_docker(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("isolate", want="on")
        out = capsys.readouterr().out
        assert rc == 1
        assert "Docker not found" in out

    def test_isolate_on_applies_when_docker_present(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(_gates.shutil, "which", lambda name, *a, **k: "/usr/bin/docker")
        rc = _gates.run_gates("isolate", want="on")
        out = capsys.readouterr().out
        assert rc == 0
        # Isolation mode lives in fleet.json.
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["isolationMode"] == "non-main"
        assert fleet["security"]["isolationEnabled"] is True
        assert "Sandbox isolation on" in out

    def test_isolate_off(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(_gates.shutil, "which", lambda name, *a, **k: "/usr/bin/docker")
        _gates.run_gates("isolate", want="on")
        capsys.readouterr()
        rc = _gates.run_gates("isolate", want="off")
        out = capsys.readouterr().out
        assert rc == 0
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["isolationMode"] == "off"
        assert "disabled (mode=off)" in out

    def test_unknown_subcommand_shows_usage(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("bogus")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Usage: docket gates" in out


# ── policies ──────────────────────────────────────────────────────────────────


class TestPolicies:
    def test_list_empty(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _policies.run_policies("list")
        captured = capsys.readouterr()
        assert rc == 0
        assert "No policies installed." in captured.out  # warn() → stdout

    def test_init_then_list(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _policies.run_policies("init")
        out = capsys.readouterr().out
        assert rc == 0
        assert "installed: block-destructive.json" in out
        # Files copied + 0600.
        dest = oc_dir / "policies" / "block-destructive.json"
        assert dest.is_file()
        assert (dest.stat().st_mode & 0o777) == 0o600

        rc = _policies.run_policies("list")
        out = capsys.readouterr().out
        assert rc == 0
        assert "block-destructive" in out
        assert "pre_tool_call" in out
        # ACTION column truncates to 14 chars (matches Bash list formatter).
        assert "require_approv" in out

    def test_init_idempotent_skips(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _policies.run_policies("init")
        capsys.readouterr()
        rc = _policies.run_policies("init")
        out = capsys.readouterr().out
        assert rc == 0
        assert "skip (exists)" in out

    def test_show_found(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("show", args=["block-destructive"])
        out = capsys.readouterr().out
        assert rc == 0
        parsed = json.loads(out)
        assert parsed["id"] == "block-destructive"

    def test_show_missing(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("show", args=["nope"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Policy not found" in captured.err

    def test_test_block_destructive(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("test", args=["pre_tool_call", "programmer", "rm -rf /tmp/foo"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "require_approval" in out

    def test_test_allow_default(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("test", args=["pre_tool_call", "programmer", "ls -la"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Result: allow" in out

    def test_test_unknown_hook(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _policies.run_policies("test", args=["bogus_hook", "programmer", "x"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Unknown hook" in captured.err

    def test_test_missing_args(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _policies.run_policies("test", args=["pre_tool_call"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Usage:" in captured.err

    def test_help_default_for_unknown(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _policies.run_policies("--help")
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket policies list" in out

    # ── validate (wires core.policy.validate_policy) ──────────────────────────────

    def test_validate_no_args_checks_every_installed_file(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("validate")
        out = capsys.readouterr().out
        assert rc == 0
        assert "block-destructive.json is valid" in out

    def test_validate_no_args_no_policies_installed(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _policies.run_policies("validate")
        out = capsys.readouterr().out
        assert rc == 0
        assert "No policies installed." in out

    def test_validate_by_id(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("validate", args=["block-destructive"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "'block-destructive' is valid." in out

    def test_validate_by_id_not_found(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_policies(oc_dir)
        rc = _policies.run_policies("validate", args=["nope"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Policy not found" in captured.err

    def test_validate_by_file_path(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        candidate = oc_dir / "candidate.json"
        candidate.write_text(
            json.dumps(
                {
                    "id": "candidate",
                    "applies_to": ["*"],
                    "hook": "pre_input",
                    "match": {"type": "regex", "pattern": "x"},
                    "action": "warn",
                }
            )
        )
        rc = _policies.run_policies("validate", args=[str(candidate)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "is valid" in out

    def test_validate_by_file_path_invalid(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        candidate = oc_dir / "candidate.json"
        candidate.write_text(json.dumps({"id": "candidate"}))  # missing required fields
        rc = _policies.run_policies("validate", args=[str(candidate)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "missing fields" in captured.err

    def test_validate_reports_invalid_installed_file(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (oc_dir / "policies").mkdir(parents=True, exist_ok=True)
        (oc_dir / "policies" / "bad.json").write_text(json.dumps({"id": "bad"}))
        rc = _policies.run_policies("validate")
        captured = capsys.readouterr()
        assert rc == 1
        assert "missing fields" in captured.err


class TestPolicyEngine:
    def test_most_restrictive_wins(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        # pre_output matches the redact policy.
        assert _policy.policy_eval("programmer", "pre_output", "ANTHROPIC_API_KEY=") == "redact"

    def test_no_match_allows(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        assert _policy.policy_eval("programmer", "pre_tool_call", "echo hi") == "allow"

    def test_validate_good_policy(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        f = oc_dir / "policies" / "block-destructive.json"
        assert _policy.validate_policy(f) == ""

    def test_validate_bad_policy(self, oc_dir: Path) -> None:
        f = oc_dir / "policies" / "broken.json"
        f.write_text(json.dumps({"id": "x", "hook": "pre_input"}))
        msg = _policy.validate_policy(f)
        assert "missing fields" in msg


# ── approve / deny ────────────────────────────────────────────────────────────


def _create(oc_dir: Path, action: str = "rm -rf /tmp") -> str:
    return _ap.approval_create("myshop", "programmer", action)


class TestApprove:
    def test_list_empty(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _approve.run_approve(None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "No pending approvals." in out

    def test_create_then_list(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        token = _create(oc_dir)
        rc = _approve.run_approve(None)
        out = capsys.readouterr().out
        assert rc == 0
        assert token in out
        assert "project=myshop" in out

    def test_grant_transitions_state(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _create(oc_dir)
        rc = _approve.run_approve(token)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval granted" in out
        rec = json.loads((oc_dir / "approvals" / f"{token}.json").read_text())
        assert rec["state"] == "granted"

    def test_grant_already_granted_warns(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _create(oc_dir)
        _approve.run_approve(token)
        capsys.readouterr()
        rc = _approve.run_approve(token)
        captured = capsys.readouterr()
        assert rc == 0
        assert "Already granted" in captured.out  # warn() → stdout

    def test_grant_missing_token_errors(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _approve.run_approve("apr-does-not-exist")
        captured = capsys.readouterr()
        assert rc == 1
        assert "Approval not found" in captured.err


class TestDeny:
    def test_deny_transitions_state(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        token = _create(oc_dir)
        rc = _deny.run_deny(token)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval denied" in out
        rec = json.loads((oc_dir / "approvals" / f"{token}.json").read_text())
        assert rec["state"] == "denied"

    def test_deny_no_token_shows_help(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _deny.run_deny(None)
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket deny <token>" in out

    def test_deny_after_grant_errors(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _create(oc_dir)
        _approve.run_approve(token)
        capsys.readouterr()
        rc = _deny.run_deny(token)
        captured = capsys.readouterr()
        assert rc == 1
        assert "Cannot deny approval in state 'granted'" in captured.err

    def test_deny_already_denied_warns(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _create(oc_dir)
        _deny.run_deny(token)
        capsys.readouterr()
        rc = _deny.run_deny(token)
        captured = capsys.readouterr()
        assert rc == 0
        assert "Already denied" in captured.out  # warn() → stdout


class TestSweep:
    def test_sweep_expires_old_pending(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token = _create(oc_dir)
        # Backdate the record well past the timeout.
        path = oc_dir / "approvals" / f"{token}.json"
        rec = json.loads(path.read_text())
        rec["created"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(rec))
        swept = _ap.approval_sweep_expired()
        assert swept == 1
        # The timeout sweep resolves to "denied" (fail-closed), not the
        # prior, read-by-nobody "expired" state.
        assert json.loads(path.read_text())["state"] == "denied"

    def test_sweep_leaves_fresh(self, oc_dir: Path) -> None:
        token = _create(oc_dir)
        assert _ap.approval_sweep_expired() == 0
        rec = json.loads((oc_dir / "approvals" / f"{token}.json").read_text())
        assert rec["state"] == "pending"
