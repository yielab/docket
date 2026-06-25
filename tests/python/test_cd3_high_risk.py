"""CD-3: high-risk action classes.

Tests that high-risk policy templates fire require_approval for payment,
production-deploy, and credential-write patterns — including on binaries that
are in SAFE_BINS (exec allowlist). Uses the same hermetic oc_dir fixture
pattern as test_m5_gates_policy.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import policy as _policy
from docket.core import security as _sec

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
