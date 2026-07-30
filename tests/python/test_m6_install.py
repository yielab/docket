"""M6 tests: install — OpenClaw + specialist bootstrap.

These call run_install() in-process with OPENCLAW_DIR monkeypatched to a temp
seed. The openclaw/systemctl shell-outs are stubbed so the run is hermetic:
``_oc.register_agent_cli`` records specialist registrations into a fake
agents.list, and DOCKET_NO_RESTART keeps systemctl untouched. Step 6 auth is
driven by stubbing ``_oc.auth_profiles_summary`` (existing/disabled/missing).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _install
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# ── seed helpers ───────────────────────────────────────────────────────────────

# Phase 10 (AA-2): install provisions only the shared **org** roles. The project
# roles (programmer/reviewer/tester) become per-pod workers via `docket add` (AA-3).
_ORG_SPECIALISTS = ("manager", "knowledge", "security")
_PROJECT_ROLES = ("programmer", "reviewer", "tester")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, fake_openclaw: Path) -> None:
    """Never touch systemctl during install tests.

    ``fake_openclaw`` puts a real `openclaw` shim on PATH so Step 1's dependency
    probe and the version read run their REAL code (they pass because they
    genuinely find the binary — no stubbing of docket's own logic). The daemon's
    state-mutating ``agents add`` is simulated at the ACL boundary by
    ``_fake_registration`` (the only thing that needs a running daemon).
    """
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    # No registry file → built-in role→model defaults apply.


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repoint config + ACL + system modules at a temp OPENCLAW_DIR."""
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "SITES_DIR", oc_dir / "Sites", raising=True)
    monkeypatch.setattr(_cfg, "LOG_DIR", oc_dir / "logs", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    # ACL bound CONFIG_FILE / meta_path directly at import — rebind them.
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make register_agent_cli append to agents.list instead of shelling out."""

    def _fake(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _fake)


def _no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_oc, "auth_profiles_summary", lambda agent="main": [])


def _ok_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _oc.ProfileSummary(
        id="anthropic-main", provider="anthropic", type="token", disabled=False, disabled_reason=""
    )
    monkeypatch.setattr(_oc, "auth_profiles_summary", lambda agent="main": [prof])


def _disabled_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _oc.ProfileSummary(
        id="anthropic-main",
        provider="anthropic",
        type="token",
        disabled=True,
        disabled_reason="usage",
    )
    monkeypatch.setattr(_oc, "auth_profiles_summary", lambda agent="main": [prof])


def _seed_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Empty ~/.openclaw with a minimal openclaw.json (already-initialized path)."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
    cfg_file.chmod(0o600)
    _point_at(oc_dir, monkeypatch)
    _fake_registration(monkeypatch)
    return oc_dir


# ── full install run ────────────────────────────────────────────────────────────


def test_install_creates_only_org_specialists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AA-2: install registers the org roles only; project roles are NOT global.
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    rc = _install.run_install(want_gates=False, assume_yes=True)
    assert rc == 0

    raw = json.loads((oc_dir / "openclaw.json").read_text())
    ids = {a["id"] for a in raw["agents"]["list"]}
    assert ids == set(_ORG_SPECIALISTS)
    # No global programmer/reviewer/tester singleton (the Defect-B fix).
    assert not (ids & set(_PROJECT_ROLES))


def test_specialist_meta_matches_bash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)

    for spec in _ORG_SPECIALISTS:
        meta_file = oc_dir / "workspaces" / spec / _cfg.META_FILE
        assert meta_file.is_file(), f"missing meta for {spec}"
        meta: dict[str, Any] = json.loads(meta_file.read_text())
        assert meta["kind"] == "specialist"
        assert meta["scope"] == "org"  # AA-2: stamped at provisioning
        assert meta["role"] == spec
        assert meta["name"] == spec
        assert meta["modelSource"] == "policy"
        assert meta["model"].startswith("anthropic/") or "/" in meta["model"]
        assert meta.get("created")  # ISO timestamp present

    # Project roles are not provisioned as global workspaces.
    for role in _PROJECT_ROLES:
        assert not (oc_dir / "workspaces" / role / _cfg.META_FILE).is_file()


# ── C-4: specialists join the workspace contract ────────────────────────────────


def test_specialist_gets_full_workspace_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 17 C-4: a freshly provisioned specialist gets the same durable
    workspace set a project agent gets — SOUL/AGENTS/HEARTBEAT plus the
    WORKFLOW_AUTO/MEMORY/daily-log contract — with 700/600 permissions and a
    current-version contract marker.
    """
    from docket.core import memory as _mem

    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)

    for spec in _ORG_SPECIALISTS:
        ws = oc_dir / "workspaces" / spec
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

    meta = json.loads((oc_dir / "workspaces" / "security" / _cfg.META_FILE).read_text())
    assert meta["sessionKey"] == "agent:security:org"
    assert meta["projectKey"] == "org"


def test_specialist_reprovisioning_preserves_real_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running `docket install` on an already-provisioned fleet must not
    clobber a HEARTBEAT.md/MEMORY.md the agent has actually written to.
    """
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)
    _install.run_install(want_gates=False, assume_yes=True)

    ws = oc_dir / "workspaces" / "security"
    hb = ws / "HEARTBEAT.md"
    mem_md = ws / "MEMORY.md"
    hb.write_text("# HEARTBEAT.md — security\n\n## Active Tasks\n- [ ] real in-flight task\n")
    mem_md.write_text("# MEMORY.md — security\n\nreal curated memory, do not lose this\n")
    soul_before = (ws / "SOUL.md").read_text()

    _install.run_install(want_gates=False, assume_yes=True)

    assert "real in-flight task" in hb.read_text()
    assert "real curated memory, do not lose this" in mem_md.read_text()
    assert (ws / "SOUL.md").read_text() == soul_before


def test_specialist_backfills_bare_legacy_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-C-4 install left specialists with only `.docket-meta.json` (the
    exact defect this card fixes) — a subsequent `docket install` must backfill
    the full workspace set without needing a fresh agent registration.
    """
    from docket.core import memory as _mem

    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    # Simulate the pre-C-4 state: registered + meta only, nothing else.
    ws = oc_dir / "workspaces" / "knowledge"
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
    raw = json.loads((oc_dir / "openclaw.json").read_text())
    raw["agents"]["list"].append(
        {"id": "knowledge", "model": "anthropic/claude-haiku-4-5", "metadata": {}}
    )
    (oc_dir / "openclaw.json").write_text(json.dumps(raw))

    assert not (ws / "SOUL.md").exists()

    _install.run_install(want_gates=False, assume_yes=True)

    assert (ws / "SOUL.md").is_file()
    assert (ws / "AGENTS.md").is_file()
    assert (ws / "HEARTBEAT.md").is_file()
    assert _mem.contract_ok(ws)


def test_install_configures_agent_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)

    raw = json.loads((oc_dir / "openclaw.json").read_text())
    defaults = raw["agents"]["defaults"]
    assert defaults["model"] == {"primary": _cfg.DEFAULT_MODEL}
    assert defaults["compaction"] == {"mode": "safeguard"}
    assert defaults["maxConcurrent"] == 4
    assert defaults["subagents"] == {"maxConcurrent": 8}
    assert raw["channels"]["telegram"]["enabled"] is True
    assert raw["channels"]["telegram"]["groups"] == {}


def test_install_creates_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)

    assert (oc_dir / "workspaces" / "projects").is_dir()
    assert (oc_dir / "Sites").is_dir()


def test_install_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second run reports specialists already registered and stays clean."""
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    assert _install.run_install(want_gates=False, assume_yes=True) == 0
    assert _install.run_install(want_gates=False, assume_yes=True) == 0

    raw = json.loads((oc_dir / "openclaw.json").read_text())
    ids = [a["id"] for a in raw["agents"]["list"]]
    # No duplicate registrations on the second pass.
    assert sorted(ids) == sorted(_ORG_SPECIALISTS)


# ── Step 6 auth branches ────────────────────────────────────────────────────────


def test_step6_detects_existing_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "Claude auth already configured" in out
    # auth_missing is False → next steps must NOT include the auth nudge.
    assert "Set up Claude auth" not in out


def test_step6_warns_when_all_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _disabled_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "All Claude auth profiles are currently disabled" in out
    assert "Set up Claude auth" in out  # auth_missing → nudge present


def test_step6_missing_auth_non_tty_does_not_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _no_auth(monkeypatch)
    # Force non-interactive so the chooser is skipped (no openclaw shell-out).
    monkeypatch.setattr(_install.sys.stdin, "isatty", lambda: False)

    rc = _install.run_install(want_gates=False, assume_yes=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No Claude auth configured" in out
    assert "Non-interactive shell" in out
    assert "Set up Claude auth" in out


def test_step6_missing_auth_interactive_invokes_chooser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a TTY + no profile, Step 6 calls the interactive chooser."""
    _seed_fresh(tmp_path, monkeypatch)
    _no_auth(monkeypatch)
    monkeypatch.setattr(_install.sys.stdin, "isatty", lambda: True)
    called: list[bool] = []
    monkeypatch.setattr(_install, "_auth_setup_interactive", lambda: called.append(True) or False)

    _install.run_install(want_gates=False, assume_yes=True)
    assert called == [True]


# ── Step 7 security gates (on by default; want_gates=False simulates --no-gates) ─


def test_install_no_gates_leaves_exec_approvals_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)
    assert not (oc_dir / "exec-approvals.json").exists()


def test_install_with_gates_applies_exec_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)
    # Keep gate application off the live daemon (write directly to the file).
    monkeypatch.setattr(
        "docket.core.security._oc.write_exec_approvals",
        lambda data: _write_local(oc_dir, data),
        raising=False,
    )

    rc = _install.run_install(want_gates=True, assume_yes=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Exec-approval gates applied" in out
    assert (oc_dir / "exec-approvals.json").is_file()


def _write_local(oc_dir: Path, data: dict[str, Any]) -> bool:
    (oc_dir / "exec-approvals.json").write_text(json.dumps(data))
    return False  # not via daemon


# ── FD-5: gates-default-on at the CLI layer ─────────────────────────────────────
#
# The tests above drive run_install() directly with an explicit want_gates=
# True/False, exercising the security step in isolation. The two tests below
# instead go through the real Typer `install` command (docket.cli.app) to prove
# the *CLI flag's own default* now applies gates with zero flags passed, and that
# --no-gates remains a working, explicit opt-out.


def test_install_cli_defaults_to_gates_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from docket.cli import app

    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)
    # Keep gate application off the live daemon (write directly to the file).
    monkeypatch.setattr(
        "docket.core.security._oc.write_exec_approvals",
        lambda data: _write_local(oc_dir, data),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["install", "--yes"])  # no --gates/--no-gates passed

    assert result.exit_code == 0
    assert "Exec-approval gates applied" in result.output
    assert (oc_dir / "exec-approvals.json").is_file()


def test_install_cli_no_gates_flag_still_opts_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from docket.cli import app

    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(app, ["install", "--yes", "--no-gates"])

    assert result.exit_code == 0
    assert not (oc_dir / "exec-approvals.json").exists()


# ── perms hardening (Step 7 / G2) ───────────────────────────────────────────────


def test_install_hardens_world_readable_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # secrets.json is never rewritten by install, so its perms survive to Step 7.
    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)
    secrets = oc_dir / "secrets.json"
    secrets.write_text("{}")
    secrets.chmod(0o644)

    _install.run_install(want_gates=False, assume_yes=True)

    assert secrets.stat().st_mode & 0o777 == 0o600
    assert "Tightened permissions to 600" in capsys.readouterr().out


def test_install_reports_already_hardened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)

    _install.run_install(want_gates=False, assume_yes=True)
    assert "permissions already owner-only" in capsys.readouterr().out


# ── gateway service (Step 8) ────────────────────────────────────────────────────


def test_install_no_service_manager_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_fresh(tmp_path, monkeypatch)
    _ok_auth(monkeypatch)
    # DOCKET_SERVICE_MANAGER=none is set by the autouse fixture.

    _install.run_install(want_gates=False, assume_yes=True)
    out = capsys.readouterr().out
    assert "No service manager detected" in out
    assert _sys.service_manager() == "none"


# ── dependency detection (Step 1) — real probe, both ways ────────────────────────


def test_check_dependencies_passes_with_openclaw(fake_openclaw: Path) -> None:
    """The real Step-1 probe finds `openclaw` on PATH and does not flag it."""
    assert "openclaw" not in _install._check_dependencies()


def test_check_dependencies_flags_missing_openclaw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `openclaw` on PATH, the real probe reports it missing — and a full
    install aborts with a non-zero exit (the genuine 'daemon not installed' path)."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # nothing — not even python3/git
    assert "openclaw" in _install._check_dependencies()

    oc_dir = _seed_fresh(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(empty))  # _seed_fresh ran with a real PATH; re-empty it
    assert oc_dir.exists()
    assert _install.run_install(want_gates=False, assume_yes=True) == 1
