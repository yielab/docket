"""High-risk action classes.

Tests that high-risk policy templates fire require_approval for payment,
production-deploy, and credential-write patterns — including on binaries that
are in SAFE_BINS (exec allowlist). Uses the same hermetic oc_dir fixture
pattern as test_gates_policies_approve_deny.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import policy as _policy
from docket.core import security as _sec

SUBJECT = "docket.core.policy"

# ── fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def policies_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp POLICIES_DIR containing all shipped templates (including high-risk)."""
    d = tmp_path / "policies"
    d.mkdir()
    monkeypatch.setattr(_cfg, "POLICIES_DIR", d, raising=True)

    # Copy every shipped template so we get the full baseline set.
    template_dir = _cfg.policy_templates_dir()
    for f in template_dir.glob("*.json"):
        shutil.copy(f, d / f.name)

    return d


# ── high-risk-payment ─────────────────────────────────────────────────────────


class TestHighRiskPayment:
    def test_stripe_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval("implementer", "pre_tool_call", "stripe charge customer")
        assert action == "require_approval"

    def test_paypal_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval("implementer", "pre_tool_call", "paypal payout send")
        assert action == "require_approval"

    def test_wire_transfer_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "initiate wire transfer to account"
        )
        assert action == "require_approval"

    def test_refund_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "refund amount to customer card"
        )
        assert action == "require_approval"

    def test_non_payment_text_not_gated(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "list all orders in the database"
        )
        # Should not trigger a high-risk gate.
        assert action != "require_approval"


# ── high-risk-deploy ──────────────────────────────────────────────────────────


class TestHighRiskDeploy:
    def test_git_push_main_requires_approval(self, policies_dir: Path) -> None:
        # 'git' is in SAFE_BINS (exec allowlist) — policy still fires.
        action = _policy.policy_eval("implementer", "pre_tool_call", "git push origin main")
        assert action == "require_approval"

    def test_git_push_production_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval("implementer", "pre_tool_call", "git push origin production")
        assert action == "require_approval"

    def test_npm_publish_requires_approval(self, policies_dir: Path) -> None:
        # 'npm' is in SAFE_BINS — policy still fires.
        action = _policy.policy_eval("implementer", "pre_tool_call", "npm publish --access public")
        assert action == "require_approval"

    def test_terraform_apply_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "terraform apply -auto-approve"
        )
        assert action == "require_approval"

    def test_helm_upgrade_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "helm upgrade my-chart ./chart --namespace prod"
        )
        assert action == "require_approval"

    def test_git_push_feature_branch_not_gated(self, policies_dir: Path) -> None:
        # Pushing to a feature branch is not high-risk.
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "git push origin feature/my-feature"
        )
        assert action != "require_approval"

    def test_allowlisted_bin_still_gated_by_high_risk(self, policies_dir: Path) -> None:
        # Core acceptance criterion: git and npm are in SAFE_BINS but the
        # high-risk-deploy policy must override the allowlist.
        assert "git" in _sec.SAFE_BINS
        assert "npm" in _sec.SAFE_BINS
        git_action = _policy.policy_eval("implementer", "pre_tool_call", "git push origin master")
        npm_action = _policy.policy_eval("implementer", "pre_tool_call", "npm publish")
        assert git_action == "require_approval", "git (allowlisted) must still gate on prod push"
        assert npm_action == "require_approval", "npm (allowlisted) must still gate on publish"


# ── high-risk-credentials ─────────────────────────────────────────────────────


class TestHighRiskCredentials:
    def test_vault_write_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "vault write secret/myapp api_key=xyz"
        )
        assert action == "require_approval"

    def test_kubectl_create_secret_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "kubectl create secret generic db-creds"
        )
        assert action == "require_approval"

    def test_openssl_genrsa_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "openssl genrsa -out key.pem 4096"
        )
        assert action == "require_approval"

    def test_ssh_keygen_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval(
            "implementer", "pre_tool_call", "ssh-keygen -t ed25519 -C user@example.com"
        )
        assert action == "require_approval"

    def test_adduser_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval("implementer", "pre_tool_call", "adduser deployer")
        assert action == "require_approval"

    def test_read_secret_not_gated(self, policies_dir: Path) -> None:
        # Reading a secret (vault read) is not a write — not high-risk.
        action = _policy.policy_eval("implementer", "pre_tool_call", "vault read secret/myapp")
        # No high-risk policy should fire on a read-only vault path.
        assert action != "require_approval"


# ── policy validation ─────────────────────────────────────────────────────────


class TestHighRiskTemplatesValid:
    """Every high-risk template must pass the schema validator."""

    def test_payment_template_valid(self) -> None:
        p = _cfg.policy_templates_dir() / "high-risk-payment.json"
        assert p.exists(), "high-risk-payment.json template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-payment.json invalid: {err}"

    def test_deploy_template_valid(self) -> None:
        p = _cfg.policy_templates_dir() / "high-risk-deploy.json"
        assert p.exists(), "high-risk-deploy.json template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-deploy.json invalid: {err}"

    def test_credentials_template_valid(self) -> None:
        p = _cfg.policy_templates_dir() / "high-risk-credentials.json"
        assert p.exists(), "high-risk-credentials.json template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-credentials.json invalid: {err}"

    def test_all_three_have_class_field(self) -> None:
        for name in ("high-risk-payment", "high-risk-deploy", "high-risk-credentials"):
            p = _cfg.policy_templates_dir() / f"{name}.json"
            doc = json.loads(p.read_text())
            assert doc.get("class") == "high-risk", f"{name}.json must have class: high-risk"


# ── policy store integrity (fail closed) ─────────────────────────────────────


def _write_policy(policies_dir: Path, name: str, doc: object) -> Path:
    f = policies_dir / name
    f.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return f


class TestBrokenPolicyFailsClosed:
    """A policy file that fails validation blocks instead of being silently skipped."""

    def test_uncompilable_regex_blocks_its_hook(self, policies_dir: Path) -> None:
        """One stray paren must deny the hook it guards, attributed to the file."""
        _write_policy(
            policies_dir,
            "zz-broken.json",
            {
                "id": "zz-broken",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "make\\s+deploy("},
                "action": "block",
                "message": "no deploys",
            },
        )
        hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "ls src")
        assert hit.action == "block"
        assert "zz-broken.json" in hit.policy_id
        assert "zz-broken.json" in hit.message

    def test_uncompilable_regex_leaves_other_hooks_alone(self, policies_dir: Path) -> None:
        """The declared hook scopes the fail-closed verdict when it is readable."""
        _write_policy(
            policies_dir,
            "zz-broken.json",
            {
                "id": "zz-broken",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "("},
                "action": "block",
            },
        )
        assert _policy.policy_eval("implementer", "pre_output", "hello world") == "allow"

    def test_unreadable_json_blocks_every_hook(self, policies_dir: Path) -> None:
        """With nothing readable, the scope is every hook and every role."""
        _write_policy(policies_dir, "zz-mangled.json", '{"id": "zz", not json')
        for hook in ("pre_input", "pre_tool_call", "pre_output"):
            hit = _policy.policy_eval_detail("lead", hook, "hello world")
            assert hit.action == "block", hook
            assert "zz-mangled.json" in hit.policy_id

    def test_unknown_action_blocks(self, policies_dir: Path) -> None:
        """An action typo on a gating policy must not degrade to allow."""
        _write_policy(
            policies_dir,
            "zz-typo.json",
            {
                "id": "zz-typo",
                "applies_to": ["*"],
                "hook": "pre_output",
                "match": {"type": "regex", "pattern": "secret"},
                "action": "blocc",
            },
        )
        assert _policy.policy_eval("tester", "pre_output", "nothing to see") == "block"

    def test_empty_pattern_blocks(self, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "zz-empty.json",
            {
                "id": "zz-empty",
                "applies_to": ["*"],
                "hook": "pre_input",
                "match": {"type": "regex", "pattern": ""},
                "action": "block",
            },
        )
        assert _policy.policy_eval("lead", "pre_input", "a task") == "block"

    def test_broken_scope_respects_applies_to(self, policies_dir: Path) -> None:
        """A readable applies_to keeps the fail-closed verdict off other roles."""
        _write_policy(
            policies_dir,
            "zz-scoped.json",
            {
                "id": "zz-scoped",
                "applies_to": ["implementer"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "("},
                "action": "warn",
            },
        )
        assert _policy.policy_eval("implementer", "pre_tool_call", "ls") == "block"
        assert _policy.policy_eval("lead", "pre_tool_call", "ls") == "allow"

    def test_trusted_skip_never_widens_over_a_broken_file(self, policies_dir: Path) -> None:
        """trusted=True skips a readable injection id, not an arbitrary broken file."""
        _write_policy(policies_dir, "zz-mangled.json", "{broken")
        hit = _policy.policy_eval_detail("lead", "pre_input", "hello", trusted=True)
        assert hit.action == "block"


class TestValidateCompilesRegex:
    def test_uncompilable_pattern_is_invalid(self, policies_dir: Path) -> None:
        f = _write_policy(
            policies_dir,
            "zz-broken.json",
            {
                "id": "zz-broken",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "make\\s+deploy("},
                "action": "block",
            },
        )
        err = _policy.validate_policy(f)
        assert err != ""
        assert "pattern" in err
