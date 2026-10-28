"""High-risk action classes.

Tests that high-risk policy templates fire require_approval for payment,
production-deploy, and credential-write patterns — including on binaries that
are in SAFE_BINS (exec allowlist). Uses the same hermetic oc_dir fixture
pattern as test_gates_policies_approve_deny.py.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

import docket.kernel.templates as _templates
from docket.governance import policy as _policy
from docket.governance import security as _sec
from docket.governance.gate import render_tool_call
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.governance.policy"

# ── fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def policies_dir(tmp_path: Path) -> Iterator[Path]:
    """Temp POLICIES_DIR containing all shipped templates (including high-risk)."""
    d = tmp_path / "policies"
    d.mkdir()
    with use_home(dataclasses.replace(current_home(), policies_dir_override=d)):
        # Copy every shipped template so we get the full baseline set -- JSON or YAML, since
        # the baseline templates ship as short-form YAML.
        template_dir = _templates.POLICY_TEMPLATES_DIR
        for pattern in ("*.json", "*.yaml", "*.yml"):
            for f in template_dir.glob(pattern):
                shutil.copy(f, d / f.name)

        yield d


# ── high-risk-payment ─────────────────────────────────────────────────────────


class TestHighRiskPayment:
    def test_stripe_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval_detail(
            "implementer", "pre_tool_call", "stripe charge customer"
        ).action
        assert action == "require_approval"

    def test_paypal_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval_detail(
            "implementer", "pre_tool_call", "paypal payout send"
        ).action
        assert action == "require_approval"

    def test_wire_transfer_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval_detail(
            "implementer", "pre_tool_call", "initiate wire transfer to account"
        ).action
        assert action == "require_approval"

    def test_refund_requires_approval(self, policies_dir: Path) -> None:
        action = _policy.policy_eval_detail(
            "implementer", "pre_tool_call", "refund amount to customer card"
        ).action
        assert action == "require_approval"

    def test_non_payment_text_not_gated(self, policies_dir: Path) -> None:
        action = _policy.policy_eval_detail(
            "implementer", "pre_tool_call", "list all orders in the database"
        ).action
        # Should not trigger a high-risk gate.
        assert action != "require_approval"


# ── block-destructive targets ────────────────────────────────────────────────


_HEREDOC = (
    "python3 - <<'EOF'\nimport os\nopen(p,'w').write(s)\n"
    + "x = 1\n" * 12
    + "const k = process.env.KEY\nEOF"
)


def _bash_action(command: str) -> str:
    """What the baseline policies answer a ``bash`` call carrying *command*."""
    args = {"command": command}
    call = _policy.ToolCallFacts("bash", args, lambda: "")
    return _policy.policy_eval_detail(
        "implementer", "pre_tool_call", render_tool_call("bash", args), call=call
    ).action


def _bd_hit(policies_dir: Path, tool: str, args: dict[str, str]) -> bool:
    call = _policy.ToolCallFacts(tool, args, lambda: "")
    hit = _policy.policy_eval_detail(
        "implementer", "pre_tool_call", render_tool_call(tool, args), call=call
    )
    return hit.policy_id == "block-destructive"


class TestBlockDestructiveTargets:
    @pytest.mark.parametrize(
        "command",
        [
            "echo k=v > .env",
            "cat >> config/.env",
            "tee .env",
            "sed -i s/a/b/ .env",
            "cp x ~/.ssh/authorized_keys",
            "mv key .ssh/id_rsa",
        ],
    )
    def test_bash_write_to_the_path_is_gated(self, policies_dir: Path, command: str) -> None:
        assert _bd_hit(policies_dir, "bash", {"command": command})

    @pytest.mark.parametrize("tool", ["write", "edit"])
    @pytest.mark.parametrize("path", [".env", "app/.env", "~/.ssh/authorized_keys"])
    def test_write_tool_with_the_path_is_gated(
        self, policies_dir: Path, tool: str, path: str
    ) -> None:
        assert _bd_hit(policies_dir, tool, {"path": path, "content": "x"})

    @pytest.mark.parametrize(
        "command", [_HEREDOC, "grep -r process.env src/", "cat .env", "ls ~/.ssh/"]
    )
    def test_two_words_in_one_call_are_not_gated(self, policies_dir: Path, command: str) -> None:
        assert not _bd_hit(policies_dir, "bash", {"command": command})

    def test_write_tool_content_naming_the_path_is_not_gated(self, policies_dir: Path) -> None:
        assert not _bd_hit(policies_dir, "write", {"path": "a.py", "content": "load(.env)"})


# ── high-risk-deploy ──────────────────────────────────────────────────────────


class TestHighRiskDeploy:
    def test_git_push_main_requires_approval(self, policies_dir: Path) -> None:
        # 'git' is in SAFE_BINS (exec allowlist) — policy still fires.
        action = _bash_action("git push origin main")
        assert action == "require_approval"

    def test_git_push_production_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("git push origin production")
        assert action == "require_approval"

    def test_npm_publish_requires_approval(self, policies_dir: Path) -> None:
        # 'npm' is in SAFE_BINS — policy still fires.
        action = _bash_action("npm publish --access public")
        assert action == "require_approval"

    def test_terraform_apply_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("terraform apply -auto-approve")
        assert action == "require_approval"

    def test_helm_upgrade_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("helm upgrade my-chart ./chart --namespace prod")
        assert action == "require_approval"

    def test_git_push_feature_branch_not_gated(self, policies_dir: Path) -> None:
        # Pushing to a feature branch is not high-risk.
        action = _bash_action("git push origin feature/my-feature")
        assert action != "require_approval"

    def test_allowlisted_bin_still_gated_by_high_risk(self, policies_dir: Path) -> None:
        # Core acceptance criterion: git and npm are in SAFE_BINS but the
        # high-risk-deploy policy must override the allowlist.
        assert "git" in _sec.SAFE_BINS
        assert "npm" in _sec.SAFE_BINS
        git_action = _bash_action("git push origin master")
        npm_action = _bash_action("npm publish")
        assert git_action == "require_approval", "git (allowlisted) must still gate on prod push"
        assert npm_action == "require_approval", "npm (allowlisted) must still gate on publish"


# ── high-risk-credentials ─────────────────────────────────────────────────────


class TestHighRiskCredentials:
    def test_vault_write_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("vault write secret/myapp api_key=xyz")
        assert action == "require_approval"

    def test_kubectl_create_secret_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("kubectl create secret generic db-creds")
        assert action == "require_approval"

    def test_openssl_genrsa_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("openssl genrsa -out key.pem 4096")
        assert action == "require_approval"

    def test_ssh_keygen_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("ssh-keygen -t ed25519 -C user@example.com")
        assert action == "require_approval"

    def test_adduser_requires_approval(self, policies_dir: Path) -> None:
        action = _bash_action("adduser deployer")
        assert action == "require_approval"

    def test_read_secret_not_gated(self, policies_dir: Path) -> None:
        # Reading a secret (vault read) is not a write — not high-risk.
        action = _bash_action("vault read secret/myapp")
        # No high-risk policy should fire on a read-only vault path.
        assert action != "require_approval"


# ── policy validation ─────────────────────────────────────────────────────────


class TestHighRiskTemplatesValid:
    """Every high-risk template must pass the schema validator."""

    def test_payment_template_valid(self) -> None:
        p = _templates.POLICY_TEMPLATES_DIR / "high-risk-payment.yaml"
        assert p.exists(), "high-risk-payment.yaml template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-payment.yaml invalid: {err}"

    def test_deploy_template_valid(self) -> None:
        p = _templates.POLICY_TEMPLATES_DIR / "high-risk-deploy.yaml"
        assert p.exists(), "high-risk-deploy.yaml template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-deploy.yaml invalid: {err}"

    def test_credentials_template_valid(self) -> None:
        p = _templates.POLICY_TEMPLATES_DIR / "high-risk-credentials.yaml"
        assert p.exists(), "high-risk-credentials.yaml template must exist"
        err = _policy.validate_policy(p)
        assert err == "", f"high-risk-credentials.yaml invalid: {err}"

    def test_all_three_have_class_field(self) -> None:
        for name in ("high-risk-payment", "high-risk-deploy", "high-risk-credentials"):
            p = _templates.POLICY_TEMPLATES_DIR / f"{name}.yaml"
            doc = _policy.read_policy(p)
            assert doc.get("class") == "high-risk", f"{name}.yaml must have class: high-risk"


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
                "kind": "policy",
                "name": "zz-broken",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "make\\s+deploy("},
                "then": "block",
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
                "kind": "policy",
                "name": "zz-broken",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "("},
                "then": "block",
            },
        )
        assert (
            _policy.policy_eval_detail("implementer", "pre_output", "hello world").action == "allow"
        )

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
                "kind": "policy",
                "name": "zz-typo",
                "appliesTo": ["*"],
                "on": "output",
                "when": {"matches": "secret"},
                "then": "blocc",
            },
        )
        assert (
            _policy.policy_eval_detail("tester", "pre_output", "nothing to see").action == "block"
        )

    def test_empty_pattern_blocks(self, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "zz-empty.json",
            {
                "kind": "policy",
                "name": "zz-empty",
                "appliesTo": ["*"],
                "on": "input",
                "when": {"matches": ""},
                "then": "block",
            },
        )
        assert _policy.policy_eval_detail("lead", "pre_input", "a task").action == "block"

    def test_broken_scope_respects_applies_to(self, policies_dir: Path) -> None:
        """A readable applies_to keeps the fail-closed verdict off other roles."""
        _write_policy(
            policies_dir,
            "zz-scoped.json",
            {
                "kind": "policy",
                "name": "zz-scoped",
                "appliesTo": ["implementer"],
                "on": "toolCall",
                "when": {"matches": "("},
                "then": "warn",
            },
        )
        assert _policy.policy_eval_detail("implementer", "pre_tool_call", "ls").action == "block"
        assert _policy.policy_eval_detail("lead", "pre_tool_call", "ls").action == "allow"

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
                "kind": "policy",
                "name": "zz-broken",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "make\\s+deploy("},
                "then": "block",
            },
        )
        err = _policy.validate_policy(f)
        assert err != ""
        assert "pattern" in err


# ── pod policies ───────────────────────────────────────────────────────────────


class TestPodPolicies:
    """A pod's own policy directory joins the global set and can only add."""

    def test_pod_only_block_denies_only_that_pod(self, policies_dir: Path) -> None:
        pod_dir = current_home().pod_config_dir("p") / "policies"
        pod_dir.mkdir(parents=True)
        _write_policy(
            pod_dir,
            "deploy-block.json",
            {
                "kind": "policy",
                "name": "p-deploy-block",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "make deploy"},
                "then": "block",
            },
        )
        assert (
            _policy.policy_eval_detail(
                "implementer", "pre_tool_call", "make deploy", project="p"
            ).action
            == "block"
        )
        assert (
            _policy.policy_eval_detail(
                "implementer", "pre_tool_call", "make deploy", project="q"
            ).action
            == "allow"
        )

    def test_pod_file_cannot_override_a_global_block(self, policies_dir: Path) -> None:
        """Most-restrictive-wins: an `allow`-shaped pod file never downgrades a global block."""
        _write_policy(
            policies_dir,
            "global-block.json",
            {
                "kind": "policy",
                "name": "global-deploy-block",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "make deploy"},
                "then": "block",
            },
        )
        pod_dir = current_home().pod_config_dir("p") / "policies"
        pod_dir.mkdir(parents=True)
        _write_policy(
            pod_dir,
            "deploy-allow.json",
            {
                "kind": "policy",
                "name": "p-deploy-allow",
                "appliesTo": ["*"],
                "on": "toolCall",
                "when": {"matches": "make deploy"},
                "then": "allow",
            },
        )
        assert (
            _policy.policy_eval_detail(
                "implementer", "pre_tool_call", "make deploy", project="p"
            ).action
            == "block"
        )


# ── short form (ADR 0010) ────────────────────────────────────────────────────────


class TestNormalizePolicy:
    """The short form a person writes normalises to the in-memory canonical dict the engine
    evaluates; a canonical key in an authored policy is refused."""

    _SHORT: ClassVar[dict[str, object]] = {
        "kind": "policy",
        "name": "block-destructive",
        "description": "Gate destructive shell commands behind explicit approval",
        "appliesTo": ["*"],
        "when": {"matches": r"\brm\s+-[rf]"},
        "then": "ask",
        "message": "Destructive command requires operator approval before execution.",
    }
    _CANONICAL: ClassVar[dict[str, object]] = {
        "id": "block-destructive",
        "description": "Gate destructive shell commands behind explicit approval",
        "applies_to": ["*"],
        "hook": "pre_tool_call",
        "match": {"type": "regex", "pattern": r"\brm\s+-[rf]"},
        "action": "require_approval",
        "message": "Destructive command requires operator approval before execution.",
    }

    def test_short_form_normalizes_to_canonical(self) -> None:
        assert _policy.normalize_policy(self._SHORT) == self._CANONICAL

    def test_a_canonical_document_is_refused_naming_the_short_form_keys(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _policy.normalize_policy(self._CANONICAL)

        message = str(exc_info.value)
        for canonical, short in (
            ("id", "name"),
            ("applies_to", "appliesTo"),
            ("hook", "on"),
            ("action", "then"),
            ("match", "when: {matches: ...}"),
        ):
            assert f"replace `{canonical}` with `{short}`" in message

    def test_a_canonical_file_fails_closed_and_the_audit_names_the_short_form_key(
        self, tmp_path: Path
    ) -> None:
        d = tmp_path / "policies"
        d.mkdir()
        with use_home(dataclasses.replace(current_home(), policies_dir_override=d)):
            (d / "p.json").write_text(json.dumps(self._CANONICAL), encoding="utf-8")

            hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "ls src")

            assert hit.action == "block"
            assert "replace `applies_to` with `appliesTo`" in hit.message

    def test_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="policy"):
            _policy.normalize_policy({"kind": "pipeline", "name": "x"})


class TestStructuredPredicates:
    """A `when` predicate can test the tool call itself, not just its rendered text."""

    def test_tool_and_path_predicate(self, tmp_path: Path) -> None:
        d = tmp_path / "policies"
        d.mkdir()
        with use_home(dataclasses.replace(current_home(), policies_dir_override=d)):
            _write_policy(
                d,
                "gh-workflow-write.json",
                {
                    "kind": "policy",
                    "name": "gh-workflow-write",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"tool": "write", "path": ".github/**"},
                    "then": "ask",
                },
            )
            allow_call = _policy.ToolCallFacts("write", {"path": "src/x.py"}, lambda: "")
            assert (
                _policy.policy_eval_detail(
                    "implementer", "pre_tool_call", "", call=allow_call
                ).action
                == "allow"
            )
            ask_call = _policy.ToolCallFacts("write", {"path": ".github/x.yml"}, lambda: "")
            assert (
                _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=ask_call).action
                == "require_approval"
            )


class TestTaskPolicies:
    """A task's block-only documents evaluate in addition to the file policies, in one scope."""

    def _doc(self, **fields: object) -> dict[str, object]:
        return {
            "kind": "policy",
            "name": "mine",
            "appliesTo": ["*"],
            "when": {"tool": "write"},
            "then": "block",
        } | fields

    def test_a_task_document_blocks_under_the_task_restriction_id(self, tmp_path: Path) -> None:
        with use_home(dataclasses.replace(current_home(), policies_dir_override=tmp_path)):
            call = _policy.ToolCallFacts("write", {"path": "a"}, lambda: "")
            doc = _policy.task_policy_document(self._doc())

            with _policy.task_policies([doc]):
                hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)
            outside = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)

            assert (hit.action, hit.policy_id) == ("block", "task-restriction")
            assert outside.action == "allow"

    def test_a_task_document_never_loosens_a_file_policy(self, tmp_path: Path) -> None:
        with use_home(dataclasses.replace(current_home(), policies_dir_override=tmp_path)):
            _write_policy(
                tmp_path,
                "global.json",
                {
                    "kind": "policy",
                    "name": "global-block",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"tool": "write"},
                    "then": "block",
                },
            )
            call = _policy.ToolCallFacts("write", {"path": "a"}, lambda: "")
            with _policy.task_policies([_policy.task_policy_document(self._doc(then="block"))]):
                hit = _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=call)

            assert hit.policy_id == "global-block"

    def test_only_a_valid_block_document_is_accepted(self) -> None:
        with pytest.raises(ValueError, match="only block"):
            _policy.task_policy_document(self._doc(then="warn"))
        with pytest.raises(ValueError, match="mapping"):
            _policy.task_policy_document("block everything")
        with pytest.raises(ValueError, match="match or when"):
            _policy.task_policy_document(
                {"kind": "policy", "name": "x", "appliesTo": ["*"], "then": "block"}
            )

    def test_the_denied_tools_document_blocks_each_named_tool(self) -> None:
        doc = _policy.denied_tools_document(["write", "edit"])
        facts = [_policy.ToolCallFacts(t, {}, lambda: "") for t in ("write", "edit", "read")]

        with _policy.task_policies([doc]):
            actions = [
                _policy.policy_eval_detail("implementer", "pre_tool_call", "", call=f).action
                for f in facts
            ]

        assert actions == ["block", "block", "allow"]
