"""sandbox gates, pod policies and check, approve, deny commands.

Drives the CLI surfaces (and the core engines behind them) in-process
against a temp DOCKET_HOME. config.py binds paths at import time, so we repoint
the live module attributes (the same technique as the doctor and trace/audit
suites). The `docker` binary is stubbed off PATH so isolation reports "needs
Docker".

There is no daemon and no exec-approvals.json file format.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _approve, _deny, _pod, _setup_sandbox
from docket.core import approval as _ap
from docket.core import policy as _policy
from docket.core import security as _sec

SUBJECT = "docket.cli"

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

    repoint_docket_home(monkeypatch, d)
    monkeypatch.setattr(_cfg, "APPROVAL_TIMEOUT", 900, raising=True)
    # Never touch systemctl.
    # No real backend probing from these tests: default to "no backend usable".
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
    return d


def _pod_cli(*args: str) -> Any:
    return CliRunner().invoke(_pod.pod_app, list(args))


def _seed_policies(oc_dir: Path) -> None:
    """Copy the shipped baseline policy templates into the temp POLICIES_DIR -- JSON or YAML,
    since the baseline templates ship as short-form YAML."""
    for pattern in ("*.json", "*.yaml", "*.yml"):
        for f in _cfg.policy_templates_dir().glob(pattern):
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
        rc = _setup_sandbox.status()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Isolation: off (default)" in out

    def test_status_always_reports_the_gate_active(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # There is no daemon gate report to query -- docket's own tool-call
        # gate (pre_tool_call + classify_command) is unconditionally active,
        # and `docket gates status` says so regardless of isolation configuration.
        rc = _setup_sandbox.status()
        out = capsys.readouterr().out
        assert rc == 0
        assert "always active" in out.lower()


class TestGatesClasses:
    def test_classes_lists_all_patterns(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _setup_sandbox.classes()
        out = capsys.readouterr().out
        assert rc == 0
        for cls in _sec.HIGH_RISK_PATTERNS:
            assert cls.name in out

    def test_classes_shows_overlapping_bins(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _setup_sandbox.classes()
        out = capsys.readouterr().out
        assert rc == 0
        assert "git" in out
        assert "npm" in out


class TestGatesIsolate:
    def test_isolate_on_needs_a_backend(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _setup_sandbox.isolate("on")
        err = capsys.readouterr().err
        assert rc == 1
        assert "No sandbox backend is usable" in err
        assert "bubblewrap" in err

    def test_isolate_on_applies_when_a_backend_is_usable(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        rc = _setup_sandbox.isolate("on")
        out = capsys.readouterr().out
        assert rc == 0
        # Isolation mode lives in fleet.json.
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["isolationMode"] == "non-main"
        assert "Isolation on" in out

    def test_isolate_off(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        _setup_sandbox.isolate("on")
        capsys.readouterr()
        rc = _setup_sandbox.isolate("off")
        out = capsys.readouterr().out
        assert rc == 0
        fleet = json.loads(_cfg.FLEET_FILE.read_text())
        assert fleet["security"]["isolationMode"] == "off"
        assert "Isolation off" in out
        _setup_sandbox.status()
        assert "Isolation: off (explicit)" in capsys.readouterr().out


# ── policies ──────────────────────────────────────────────────────────────────


class TestPolicies:
    def test_list_empty(self, oc_dir: Path) -> None:
        result = _pod_cli("policies")
        assert result.exit_code == 0
        assert "No policies installed" in result.output

    def test_seeded_then_list(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("policies")
        assert result.exit_code == 0
        assert "block-destructive" in result.output
        assert "pre_tool_call" in result.output
        # ACTION column truncates to 14 chars.
        assert "require_approv" in result.output

    def test_show_found(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("policies", "block-destructive")
        assert result.exit_code == 0
        assert json.loads(result.output)["id"] == "block-destructive"

    def test_show_missing(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("policies", "nope")
        assert result.exit_code == 1
        assert "Policy not found" in result.output

    def test_check_block_destructive(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("check", "rm -rf /tmp/foo", "--role", "programmer")
        assert result.exit_code == 0
        assert "require_approval" in result.output

    def test_check_allow_default(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("check", "ls -la", "--role", "programmer")
        assert result.exit_code == 0
        assert "Result: allow" in result.output

    def test_check_matches_the_live_gate_for_an_offlist_binary(self, oc_dir: Path) -> None:
        """A `cd`-prefixed command with an off-allowlist later segment (no declarative
        policy matches `export`) must ask here exactly as the live gate would, not
        `allow` from a declarative-only dry-run that never consults the classifier."""
        _seed_policies(oc_dir)
        result = _pod_cli("check", "cd /worktree && export FOO=bar", "--role", "implementer")
        assert result.exit_code == 0
        assert "Result: ask" in result.output
        assert "curated allowlist" in result.output

    def test_check_unknown_hook(self, oc_dir: Path) -> None:
        result = _pod_cli("check", "x", "--role", "programmer", "--hook", "bogus_hook")
        assert result.exit_code == 2
        assert "Unknown hook" in result.output

    def test_check_missing_text(self, oc_dir: Path) -> None:
        result = _pod_cli("check", "--role", "programmer")
        assert result.exit_code == 2

    def test_list_rejects_unknown_flag(self, oc_dir: Path) -> None:
        """A flag `pod policies` does not declare is a usage error, never a silently ignored
        token that still prints the table and exits 0."""
        assert _pod_cli("policies", "--bogus").exit_code == 2

    def test_list_json_names_each_policy(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        rows = json.loads(_pod_cli("policies", "--json").output)
        assert "block-destructive" in {r["id"] for r in rows}

    def test_check_free_text_is_never_treated_as_a_flag(self, oc_dir: Path) -> None:
        """The text after `--` is arbitrary dry-run text, so a leading `-` in it reaches the
        evaluator untouched instead of being rejected as an unrecognized flag."""
        result = _pod_cli("check", "--role", "programmer", "--", "-rf /tmp/foo")
        assert result.exit_code == 0

    # -- pod validate over the installed policy store (wires core.policy.validate_policy) ----

    def test_validate_checks_every_installed_file(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        result = _pod_cli("validate", str(oc_dir))
        assert result.exit_code == 0
        assert "block-destructive.yaml" in result.output

    def test_validate_by_file_path(self, oc_dir: Path) -> None:
        candidate = oc_dir / "candidate" / "policies" / "candidate.json"
        candidate.parent.mkdir(parents=True)
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
        result = _pod_cli("validate", str(candidate))
        assert result.exit_code == 0
        assert "candidate.json" in result.output

    def test_validate_by_file_path_invalid(self, oc_dir: Path) -> None:
        candidate = oc_dir / "candidate" / "policies" / "candidate.json"
        candidate.parent.mkdir(parents=True)
        candidate.write_text(json.dumps({"id": "candidate"}))  # missing required fields
        result = _pod_cli("validate", str(candidate))
        assert result.exit_code == 1
        assert "missing fields" in result.output

    def test_validate_reports_invalid_installed_file(self, oc_dir: Path) -> None:
        (oc_dir / "policies" / "bad.json").write_text(json.dumps({"id": "bad"}))
        result = _pod_cli("validate", str(oc_dir))
        assert result.exit_code == 1
        assert "missing fields" in result.output


class TestPolicyEngine:
    def test_most_restrictive_wins(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        # pre_output matches the redact policy.
        assert (
            _policy.policy_eval_detail("programmer", "pre_output", "ANTHROPIC_API_KEY=").action
            == "redact"
        )

    def test_no_match_allows(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        assert (
            _policy.policy_eval_detail("programmer", "pre_tool_call", "echo hi").action == "allow"
        )

    def test_validate_good_policy(self, oc_dir: Path) -> None:
        _seed_policies(oc_dir)
        f = oc_dir / "policies" / "block-destructive.yaml"
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


class TestBrokenPolicyStoreCli:
    """CLI surfaces of the fail-closed policy store."""

    _BROKEN: ClassVar[dict[str, object]] = {
        "id": "zz-broken",
        "applies_to": ["*"],
        "hook": "pre_tool_call",
        "match": {"type": "regex", "pattern": "make\\s+deploy("},
        "action": "block",
        "message": "no deploys",
    }

    def test_validate_flags_uncompilable_regex(self, oc_dir: Path) -> None:
        (oc_dir / "policies" / "zz-broken.json").write_text(json.dumps(self._BROKEN))
        result = _pod_cli("validate", str(oc_dir))
        assert result.exit_code == 1
        assert "pattern" in result.output

    def test_check_reports_broken_store_as_deny(self, oc_dir: Path) -> None:
        (oc_dir / "policies" / "zz-broken.json").write_text(json.dumps(self._BROKEN))
        result = _pod_cli("check", "ls src", "--role", "implementer")
        assert result.exit_code == 0
        assert "deny" in result.output
        assert "zz-broken.json" in result.output


class TestPoliciesTestToolKind:
    """--tool picks whether the command classifier applies to the dry-run."""

    _WARN: ClassVar[dict[str, object]] = {
        "id": "watch-mainpy",
        "applies_to": ["*"],
        "hook": "pre_tool_call",
        "match": {"type": "regex", "pattern": "main\\.py"},
        "action": "warn",
        "message": "main.py touched",
    }

    def test_non_exec_tool_skips_the_classifier(self, oc_dir: Path) -> None:
        (oc_dir / "policies" / "watch-mainpy.json").write_text(json.dumps(self._WARN))
        result = _pod_cli(
            "check", 'write path="main.py"', "--role", "implementer", "--tool", "write"
        )
        assert result.exit_code == 0
        assert "allow" in result.output
        assert "watch-mainpy" in result.output
        assert "curated allowlist" not in result.output

    def test_exec_default_still_classifies(self, oc_dir: Path) -> None:
        result = _pod_cli("check", "somebinary --flag", "--role", "implementer")
        assert result.exit_code == 0
        assert "ask" in result.output
        assert "curated allowlist" in result.output

    def test_unknown_tool_errors(self, oc_dir: Path) -> None:
        result = _pod_cli("check", "x", "--role", "implementer", "--tool", "bogus")
        assert result.exit_code == 2
        assert "bogus" in result.output
        assert "bash" in result.output
