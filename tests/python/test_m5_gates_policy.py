"""M5 T5.4b + T5.3 tests: gates, policies, approve, deny.

Drives the four CLI run_* surfaces (and the core engines behind them) in-process
against a temp OPENCLAW_DIR. config.py and the openclaw ACL bind paths at import
time, so we repoint the live module attributes (the same technique as the doctor
and trace/audit suites). The `openclaw`/`docker` binaries are stubbed off PATH so
gate writes take the direct (hermetic) path and isolation reports "needs Docker".
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
from docket.edges.adapters import openclaw as _oc

_OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": "anthropic/claude-sonnet-4-6"},
        "list": [
            {"id": "myshop", "model": "anthropic/claude-sonnet-4-6", "metadata": {}},
            {"id": "content", "model": "anthropic/claude-haiku-4-5", "metadata": {}},
        ],
    },
    "bindings": [
        {
            "agentId": "myshop",
            "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-100"}},
        }
    ],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp ~/.openclaw with config + ACL paths repointed; binaries stubbed off."""
    d = tmp_path / ".openclaw"
    (d / "policies").mkdir(parents=True)
    (d / "approvals").mkdir(parents=True)
    cfg_file = d / "openclaw.json"
    cfg_file.write_text(json.dumps(_OC_CONFIG))
    cfg_file.chmod(0o600)

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", d / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    # ACL bound CONFIG_FILE at import — rebind.
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    # Never touch systemctl.
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_NO_AUDIT", "1")

    # Stub `openclaw` and `docker` off PATH so writes take the direct path and
    # isolation reports "needs Docker". Real binaries (git, python3, ...) pass.
    real_which = shutil.which

    def fake_which(name: str, *a: Any, **k: Any) -> str | None:
        if name in ("openclaw", "docker"):
            return None
        return real_which(name, *a, **k)

    monkeypatch.setattr(_sec.shutil, "which", fake_which)
    monkeypatch.setattr(_gates.shutil, "which", fake_which)
    # ACL.write_exec_approvals + security_gate_report import shutil locally; stub
    # the module-level shutil they would resolve via `import shutil as _shutil`.
    monkeypatch.setattr(shutil, "which", fake_which)
    return d


def _seed_policies(oc_dir: Path) -> None:
    """Copy the shipped baseline policy templates into the temp POLICIES_DIR."""
    for f in _cfg.policy_templates_dir().glob("*.json"):
        shutil.copy(f, oc_dir / "policies" / f.name)


# ── FD-3: high-risk action classes ─────────────────────────────────────────────


class TestHighRiskPatterns:
    def test_prod_deploy_matches_git_push_production(self) -> None:
        cls = _sec.match_high_risk("git push origin production")
        assert cls is not None
        assert cls.name == "prod-deploy"

    def test_prod_deploy_matches_npm_publish(self) -> None:
        assert _sec.is_high_risk("npm publish --access public") is True

    def test_money_movement_matches_stripe(self) -> None:
        assert _sec.is_high_risk("stripe charge customer") is True

    def test_secret_access_matches_ssh_keygen(self) -> None:
        assert _sec.is_high_risk("ssh-keygen -t ed25519") is True

    def test_non_matching_command_is_not_high_risk(self) -> None:
        assert _sec.is_high_risk("ls -la") is False
        assert _sec.is_high_risk("git status") is False

    def test_high_risk_bins_includes_git_and_npm(self) -> None:
        bins = _sec.high_risk_bins()
        assert "git" in bins
        assert "npm" in bins
        assert "ls" not in bins


class TestResolveCommandAction:
    def test_high_risk_forces_ask_even_when_binary_allowlisted(self) -> None:
        # 'git' the binary is on the allowlist, but a high-risk invocation of
        # it must still force 'ask' -- allowlist status must never bypass a
        # high-risk match.
        allowlist = ["/usr/bin/git"]
        action = _sec.resolve_command_action("git push origin production", allowlist)
        assert action == "ask"

    def test_non_matching_allowlisted_command_is_allowed(self) -> None:
        allowlist = ["/usr/bin/git"]
        action = _sec.resolve_command_action("git status", allowlist)
        assert action == "allow"

    def test_non_matching_non_allowlisted_command_asks(self) -> None:
        action = _sec.resolve_command_action("rm -rf /tmp/foo", ["/usr/bin/git"])
        assert action == "ask"


class TestResolveSafeBinPaths:
    def test_high_risk_attached_bins_still_seeded(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # git/npm have a HIGH_RISK_PATTERNS class attached for documentation
        # (docket gates classes) but the daemon can only gate by binary path,
        # not argument text -- excluding them wholesale would also block
        # every benign invocation (git status, npm test, ...), so they stay
        # seeded like any other SAFE_BINS member. Stub PATH resolution so the
        # assertion doesn't depend on npm actually being installed here.
        monkeypatch.setattr(_sec.shutil, "which", lambda name: f"/usr/bin/{name}")
        paths = _sec.resolve_safe_bin_paths()
        bases = {p.rsplit("/", 1)[-1] for p in paths}
        for name in _sec.high_risk_bins():
            assert name in bases

    def test_non_high_risk_bin_still_resolved(self, oc_dir: Path) -> None:
        paths = _sec.resolve_safe_bin_paths()
        bases = {p.rsplit("/", 1)[-1] for p in paths}
        assert "ls" in bases


class TestBuildExecApprovalsHighRisk:
    def test_seeded_allowlist_includes_high_risk_attached_bins(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # See test_high_risk_attached_bins_still_seeded: these bins remain
        # allowlisted despite having a documented high-risk class, since the
        # daemon can't distinguish their risky/benign invocations.
        monkeypatch.setattr(_sec.shutil, "which", lambda name: f"/usr/bin/{name}")
        paths = _sec.resolve_safe_bin_paths()
        merged, _, _ = _sec.build_exec_approvals({}, paths, ["myshop"], force=False)
        for agent in merged["agents"].values():
            bases = {e["pattern"].rsplit("/", 1)[-1] for e in agent["allowlist"]}
            for name in _sec.high_risk_bins():
                assert name in bases


# ── gates ─────────────────────────────────────────────────────────────────────


class TestGatesStatus:
    def test_status_unset(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No openclaw CLI → gate report NA; routing/isolation unset.
        rc = _gates.run_gates("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Approval routing: not configured" in out
        assert "Workspace isolation: not configured" in out

    def test_status_ok_policy(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            _gates._oc,
            "security_gate_report",
            lambda: ("OK", "security=allowlist ask=on-miss askFallback=deny", "agents=2"),
        )
        rc = _gates.run_gates("status")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Policy: security=allowlist" in out


class TestGatesEnableDisable:
    def test_enable_writes_exec_approvals_direct(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _gates.run_gates("enable")
        out = capsys.readouterr().out
        assert rc == 0
        appr = json.loads((oc_dir / "exec-approvals.json").read_text())
        assert appr["defaults"]["security"] == "allowlist"
        assert appr["defaults"]["ask"] == "on-miss"
        assert appr["defaults"]["askFallback"] == "deny"
        # 'main' is always seeded plus the two registered agents.
        for aid in ("main", "myshop", "content"):
            assert appr["agents"][aid]["allowlist"]
        assert "Applied gate defaults" in out
        # Direct write because openclaw is off PATH.
        assert "directly (gateway not reached)" in out
        # Routing wired; myshop has a telegram binding → count >= 1.
        assert "Approval routing on" in out
        assert "1 Telegram-bound agent" in out
        # openclaw.json now carries approvals.exec routing.
        cfg = json.loads((oc_dir / "openclaw.json").read_text())
        assert cfg["approvals"]["exec"] == {"enabled": True, "mode": "session"}

    def test_enable_idempotent_without_force(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("enable")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Gate defaults already set" in out

    def test_enable_force_overwrites(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("enable", force=True)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Applied gate defaults" in out

    def test_disable_resets_defaults_and_routing(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _gates.run_gates("enable")
        capsys.readouterr()
        rc = _gates.run_gates("disable")
        out = capsys.readouterr().out
        assert rc == 0
        appr = json.loads((oc_dir / "exec-approvals.json").read_text())
        assert appr["defaults"] == {}
        # Seeded allowlists are left in place.
        assert appr["agents"]["main"]["allowlist"]
        cfg = json.loads((oc_dir / "openclaw.json").read_text())
        assert cfg["approvals"]["exec"]["enabled"] is False
        assert "falls back to tools.exec" in out


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
        assert "stay allowlisted" in out
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
        cfg = json.loads((oc_dir / "openclaw.json").read_text())
        sb = cfg["agents"]["defaults"]["sandbox"]
        assert sb == {"mode": "non-main", "scope": "agent", "workspaceAccess": "rw"}
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
        cfg = json.loads((oc_dir / "openclaw.json").read_text())
        assert cfg["agents"]["defaults"]["sandbox"]["mode"] == "off"
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
        assert json.loads(path.read_text())["state"] == "expired"

    def test_sweep_leaves_fresh(self, oc_dir: Path) -> None:
        token = _create(oc_dir)
        assert _ap.approval_sweep_expired() == 0
        rec = json.loads((oc_dir / "approvals" / f"{token}.json").read_text())
        assert rec["state"] == "pending"
