"""Install — docket-native home + specialist bootstrap.

There is no external daemon. These tests call ``bootstrap_workstation()`` in-process
with ``DOCKET_HOME``/``FLEET_FILE`` monkeypatched to a temp seed; specialist
registration writes straight to fleet.json (no shell-out to stub), and Step 5
(model credentials) is driven by seeding ``core/secrets.py``'s store
directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _agents, _install
from docket.core import fleet as _fleet
from docket.core import models_policy as _models_policy
from docket.core import secrets as _secrets

# ── seed helpers ───────────────────────────────────────────────────────────────

# install provisions only the shared **org** roles. The project roles
# (programmer/reviewer/tester) become per-pod workers via `docket add`.
_ORG_SPECIALISTS = ("manager", "knowledge", "security")
_PROJECT_ROLES = ("programmer", "reviewer", "tester")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
    # No registry file → built-in role→model defaults apply.
    yield
    os.environ.pop("DOCKET_LLM_BASE_URL", None)
    os.environ.pop("DOCKET_LLM_API_KEY", None)


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint config modules at a temp DOCKET_HOME."""
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "SITES_DIR", home / "Sites", raising=True)
    monkeypatch.setattr(_cfg, "LOG_DIR", home / "logs", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", home / "policies", raising=True)
    monkeypatch.setattr(_secrets, "SECRETS_FILE", home / "secrets.json", raising=True)
    monkeypatch.setattr(_secrets, "SECRETS_META_FILE", home / "secrets.meta.json", raising=True)


def _no_auth() -> None:
    _secrets.save_secrets({})


def _ok_auth() -> None:
    _secrets.save_secrets({"ANTHROPIC_API_KEY": "sk-ant-test-1234567890"})
    os.environ["DOCKET_LLM_BASE_URL"] = "http://127.0.0.1:9999/v1"


def _seed_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Empty DOCKET_HOME with a minimal fleet.json (already-initialized path)."""
    home = tmp_path / ".docket"
    home.mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps({"agents": [], "bindings": []}))
    fleet_file.chmod(0o600)
    _point_at(home, monkeypatch)
    return home


def test_provider_only_fleet_still_runs_first_project_foundation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _fleet.add_local_provider(
        "local",
        "http://127.0.0.1:8081/v1",
        "qwen-live-id",
        "Qwen live",
        16384,
        8192,
    )
    bootstrap_calls: list[dict[str, object]] = []

    def _stop_after_bootstrap(**kwargs: object) -> int:
        bootstrap_calls.append(kwargs)
        return 1

    monkeypatch.setattr(_install, "bootstrap_workstation", _stop_after_bootstrap)

    assert _agents.run_init([]) == 1
    assert bootstrap_calls == [
        {
            "want_gates": True,
            "assume_yes": True,
            "want_portfolio": False,
            "continuing_to_project": True,
        }
    ]


# ── full install run ────────────────────────────────────────────────────────────


def test_install_creates_only_org_specialists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # install registers the org roles only; project roles are NOT global.
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    rc = _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    assert rc == 0

    ids = {a.id for a in _fleet.list_agents()}
    assert ids == set(_ORG_SPECIALISTS)
    # No global programmer/reviewer/tester singleton.
    assert not (ids & set(_PROJECT_ROLES))


def test_install_explains_workstation_vs_project_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    assert _install.bootstrap_workstation(want_gates=False, assume_yes=True) == 0
    out = capsys.readouterr().out
    assert "shared workstation foundation" in out.lower()
    assert "project pods remain separate" in out.lower()
    assert "docket init" in out


def test_specialist_meta_matches_bash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    for spec in _ORG_SPECIALISTS:
        meta_file = home / "workspaces" / spec / _cfg.META_FILE
        assert meta_file.is_file(), f"missing meta for {spec}"
        meta: dict[str, Any] = json.loads(meta_file.read_text())
        assert meta["kind"] == "specialist"
        assert meta["scope"] == "org"  # stamped at provisioning
        assert meta["role"] == spec
        assert meta["name"] == spec
        assert meta["modelSource"] == "policy"
        assert meta["model"].startswith("anthropic/") or "/" in meta["model"]
        assert meta.get("created")  # ISO timestamp present

    # Project roles are not provisioned as global workspaces.
    for role in _PROJECT_ROLES:
        assert not (home / "workspaces" / role / _cfg.META_FILE).is_file()


# ── specialists join the workspace contract ────────────────────────────────


def test_specialist_gets_full_workspace_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A freshly provisioned specialist gets the same durable workspace set a
    project agent gets — SOUL/AGENTS/HEARTBEAT plus the WORKFLOW_AUTO/MEMORY/
    daily-log contract — with 700/600 permissions and a current-version
    contract marker.
    """
    from docket.core import memory as _mem

    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    for spec in _ORG_SPECIALISTS:
        ws = home / "workspaces" / spec
        assert ws.stat().st_mode & 0o777 == 0o700

        for fname in (
            "SOUL.md",
            "AGENTS.md",
            "HEARTBEAT.md",
            _mem.REQUIRED_STARTUP_FILE,
            _mem.MEMORY_FILE,
        ):
            fpath = ws / fname
            assert fpath.is_file(), f"{spec}: missing {fname}"
            assert fpath.stat().st_mode & 0o777 == 0o600, f"{spec}: {fname} not 0600"

        assert (ws / _mem.today_memory_relpath()).is_file(), f"{spec}: missing today's daily log"
        assert _mem.contract_ok(ws), f"{spec}: WORKFLOW_AUTO.md missing/stale contract marker"

        soul = (ws / "SOUL.md").read_text()
        assert f"agent:{spec}:org" in soul
        assert spec in soul

        # TOOLS.md is deliberately NOT written — a specialist has no codebase.
        assert not (ws / "TOOLS.md").exists()

    meta = json.loads((home / "workspaces" / "security" / _cfg.META_FILE).read_text())
    assert meta["sessionKey"] == "agent:security:org"
    assert meta["projectKey"] == "org"


def test_specialist_reprovisioning_preserves_real_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running the workstation foundation bootstrap on an already-provisioned fleet must not
    clobber a HEARTBEAT.md/MEMORY.md the agent has actually written to.
    """
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()
    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    ws = home / "workspaces" / "security"
    hb = ws / "HEARTBEAT.md"
    mem_md = ws / "MEMORY.md"
    hb.write_text("# HEARTBEAT.md — security\n\n## Active Tasks\n- [ ] real in-flight task\n")
    mem_md.write_text("# MEMORY.md — security\n\nreal curated memory, do not lose this\n")
    soul_before = (ws / "SOUL.md").read_text()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    assert "real in-flight task" in hb.read_text()
    assert "real curated memory, do not lose this" in mem_md.read_text()
    assert (ws / "SOUL.md").read_text() == soul_before


def test_specialist_backfills_bare_legacy_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy install could leave specialists with only `.docket-meta.json`
    — a subsequent the workstation foundation bootstrap must backfill the full workspace set
    without needing a fresh agent registration.
    """
    from docket.core import memory as _mem

    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    # Simulate that legacy state: registered + meta only, nothing else.
    ws = home / "workspaces" / "knowledge"
    ws.mkdir(parents=True)
    ws.chmod(0o700)
    (ws / _cfg.META_FILE).write_text(
        json.dumps(
            {
                "kind": "specialist",
                "scope": "org",
                "role": "knowledge",
                "name": "knowledge",
                "model": "anthropic/claude-haiku-4-5",
                "modelSource": "policy",
                "created": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    (ws / _cfg.META_FILE).chmod(0o600)
    _fleet.add_agent("knowledge", "anthropic/claude-haiku-4-5")

    assert not (ws / "SOUL.md").exists()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    assert (ws / "SOUL.md").is_file()
    assert (ws / "AGENTS.md").is_file()
    assert (ws / "HEARTBEAT.md").is_file()
    assert _mem.contract_ok(ws)


def test_install_configures_default_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    assert _fleet.get_default_model() == _cfg.DEFAULT_MODEL


def test_install_creates_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    assert (home / "workspaces" / "projects").is_dir()
    assert (home / "Sites").is_dir()


def test_install_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second run reports specialists already registered and stays clean."""
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    assert _install.bootstrap_workstation(want_gates=False, assume_yes=True) == 0
    assert _install.bootstrap_workstation(want_gates=False, assume_yes=True) == 0

    ids = [a.id for a in _fleet.list_agents()]
    # No duplicate registrations on the second pass.
    assert sorted(ids) == sorted(_ORG_SPECIALISTS)


# ── Step 5: model credentials ────────────────────────────────────────────────────


def test_step5_detects_existing_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "Model provider ready" in out
    assert "ANTHROPIC_API_KEY configured (value hidden)" in out
    # auth_missing is False → next steps must NOT include the credential nudge.
    assert "Store a model-provider credential" not in out


def test_step5_unresolved_default_fails_before_ready_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _no_auth()

    rc = _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    assert rc == 1
    out = capsys.readouterr().out
    assert "anthropic/claude-sonnet-4-6" in out
    assert "no callable OpenAI-compatible endpoint" in out
    assert "docket models provider add" in out
    assert "docket models preset local" in out
    assert "Foundation Ready" not in out
    assert "Continuing with project initialization" not in out


def test_step5_direct_anthropic_key_is_not_endpoint_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _no_auth()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-var")

    rc = _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ANTHROPIC_API_KEY is present but is not an endpoint" in out
    assert "Foundation Ready" not in out


def test_step5_registered_local_endpoint_needs_no_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _no_auth()
    _fleet.add_local_provider(
        "local",
        "http://127.0.0.1:8081/v1",
        "qwen-local",
        "Qwen local",
        16384,
        8192,
    )
    _models_policy.write_registry(
        {
            "default": "local/qwen-local",
            "rank.economy": "local/qwen-local",
            "rank.standard": "local/qwen-local",
            "rank.premium": "local/qwen-local",
            **{f"role.{role}": "local/qwen-local" for role in _models_policy.ALL_ROLES},
        }
    )

    rc = _install.bootstrap_workstation(
        want_gates=False, assume_yes=True, continuing_to_project=True
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Model provider ready" in out
    assert "local/qwen-local" in out
    assert "http://127.0.0.1:8081/v1" in out
    assert "No API key required" in out
    assert "Shared Workstation Foundation Ready" in out


# ── Step 6 security: approval routing + perms hardening ─────────────────────────


def test_install_no_gates_skips_approval_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "Approval routing disabled for this workstation (--no-gates)" in out
    r_state, _mode = _fleet.get_approval_routing()
    assert r_state != "on"


def test_install_with_gates_turns_on_approval_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    rc = _install.bootstrap_workstation(want_gates=True, assume_yes=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Approval routing on" in out
    r_state, r_mode = _fleet.get_approval_routing()
    assert r_state == "on"
    assert r_mode == "session"


def test_install_always_reports_tool_call_gate_always_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regardless of --gates/--no-gates, the real tool-call gate (policy engine +
    high-risk classifier) is unconditionally active -- install must never
    imply otherwise."""
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "policy engine" in out or "high-risk classifier" in out


# ── gates-default-on at the CLI layer ───────────────────────────────────────────
#
# The tests above drive the internal workstation bootstrap directly. These two
# go through the public first-project `init` path to prove its lazy bootstrap
# applies routing by default and still accepts an explicit --no-gates opt-out.


def test_first_init_defaults_to_gates_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from docket.cli import app

    home = tmp_path / ".docket"
    home.mkdir()
    _point_at(home, monkeypatch)
    _ok_auth()
    repo = tmp_path / "project"
    repo.mkdir()
    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert "Approval routing on" in result.output
    r_state, _mode = _fleet.get_approval_routing()
    assert r_state == "on"


def test_first_init_no_gates_flag_opts_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from docket.cli import app

    home = tmp_path / ".docket"
    home.mkdir()
    _point_at(home, monkeypatch)
    _ok_auth()
    repo = tmp_path / "project"
    repo.mkdir()
    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--no-gates"])

    assert result.exit_code == 0
    r_state, _mode = _fleet.get_approval_routing()
    assert r_state != "on"


# ── perms hardening ──────────────────────────────────────────────────────────────


def test_install_hardens_world_readable_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()
    secrets_file = home / "secrets.json"
    secrets_file.write_text("{}")
    secrets_file.chmod(0o644)

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    assert secrets_file.stat().st_mode & 0o777 == 0o600
    assert "Tightened permissions to 600" in capsys.readouterr().out


def test_install_reports_already_hardened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    assert "permissions already owner-only" in capsys.readouterr().out


# ── guardrail policies ───────────────────────────────────────────────────────────


def test_install_seeds_guardrail_policies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """the workstation foundation bootstrap runs the same producer as `docket policies init` —
    the policy engine has nothing to evaluate against an empty $POLICIES_DIR."""
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)

    policies_dir = home / "policies"
    assert policies_dir.is_dir()
    installed = {f.name for f in policies_dir.glob("*.json")}
    assert installed == {f.name for f in _cfg.policy_templates_dir().glob("*.json")}
    assert "Installed" in capsys.readouterr().out


def test_install_policies_step_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth()

    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    capsys.readouterr()
    _install.bootstrap_workstation(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out

    assert "already installed" in out
    # No duplicate/overwritten files — still exactly the shipped template set.
    installed = {f.name for f in (home / "policies").glob("*.json")}
    assert installed == {f.name for f in _cfg.policy_templates_dir().glob("*.json")}


# ── dependency detection (Step 1) ────────────────────────────────────────────────


def test_check_dependencies_passes_with_python_and_git() -> None:
    """The real Step-1 probe finds python3/git on PATH (the real dev/CI
    environment) and does not flag them."""
    missing = _install._check_dependencies()
    assert "python3" not in missing
    assert "git" not in missing


def test_check_dependencies_flags_missing_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `git` on PATH, the real probe reports it missing — and a full
    install aborts with a non-zero exit."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # nothing at all on PATH
    assert "git" in _install._check_dependencies()

    home = _seed_fresh(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(empty))  # _seed_fresh's fixtures don't touch PATH; re-assert
    assert home.exists()
    assert _install.bootstrap_workstation(want_gates=False, assume_yes=True) == 1
