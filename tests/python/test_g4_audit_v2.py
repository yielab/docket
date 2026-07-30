"""G-4: Audit v2 — coverage expansion, tamper-evidence chain, kill-switch removal.

Covers:
  - New audit_log() call sites (keys.*, profile.*, scope.*, agent.add/delete,
    persona.*) each write exactly one line with the right dotted-verb action
    and no secret values (pod.add/pod.remove coverage lives in
    test_pod_provisioning.py, which already has the pod-daemon fixtures).
  - The hash chain (seq + prev_hash, GENESIS_HASH): verifies clean on a fresh
    log, detects a hand-tampered middle line at the point the chain actually
    breaks, tolerates pre-chain legacy lines and malformed JSON without
    crashing the viewer or verifier, and documents (rather than bridges) a
    rotation boundary.
  - `docket audit verify` (cli/_audit.py's run_audit_verify).

Every fixture repoints ``_cfg.AUDIT_LOG`` explicitly — the conftest-wide
``_isolate_audit_log`` autouse fixture is a safety net, not a substitute for
tests that need to actually inspect what got written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket import cli
from docket.cli import _audit as audit_cli
from docket.cli import _keys as keys_cli
from docket.cli._agents import run_add, run_delete
from docket.core import audit as _audit
from docket.edges.adapters import openclaw as _oc

# ── shared helpers ───────────────────────────────────────────────────────────


def _entries(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e["action"] == action]


def _seed_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aid: str = "demo") -> Path:
    """A minimal, non-pod project agent: workspace + meta + openclaw.json entry."""
    oc_dir = tmp_path / ".openclaw"
    ws = oc_dir / "workspaces" / "projects" / aid
    ws.mkdir(parents=True)
    meta = {
        "kind": "project",
        "name": "Demo",
        "role": "repo",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": f"agent:{aid}:default",
        "projectKey": "default",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
                    "list": [{"id": aid, "model": "anthropic/claude-sonnet-4-6", "metadata": {}}],
                },
                "bindings": [],
                "channels": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", oc_dir / "audit.log", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    return oc_dir


@pytest.fixture()
def audit_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bare OPENCLAW_DIR for exercising core/audit.py directly."""
    d = tmp_path / ".openclaw"
    d.mkdir()
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    return d


# ── hash chain: core/audit.py ───────────────────────────────────────────────


class TestChainWriting:
    def test_first_entry_is_seq_1_with_genesis_prev_hash(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        entries = _audit.read_audit()
        assert entries[0]["seq"] == 1
        assert entries[0]["prev_hash"] == _audit.GENESIS_HASH

    def test_second_entry_chains_to_the_first(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        entries = _audit.read_audit()
        assert entries[1]["seq"] == 2
        assert entries[1]["prev_hash"] == _audit._hash_entry(entries[0])

    def test_timestamps_are_millisecond_resolution(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        ts = _audit.read_audit()[0]["ts"]
        # YYYY-MM-DDTHH:MM:SS.mmmZ
        assert ts.endswith("Z")
        assert "." in ts
        millis = ts.split(".")[1].rstrip("Z")
        assert len(millis) == 3
        assert millis.isdigit()


class TestChainVerify:
    def test_missing_log_reports_nothing_to_verify(self, audit_home: Path) -> None:
        result = _audit.verify_chain()
        assert result.exists is False
        assert result.break_at is None

    def test_fresh_log_verifies_clean(self, audit_home: Path) -> None:
        for i in range(5):
            _audit.audit_log("keys.add", f"KEY_{i}")
        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.chained == 5
        assert result.legacy == 0
        assert result.total_lines == 5

    def test_tampered_middle_line_detected_at_right_position(self, audit_home: Path) -> None:
        for i in range(5):
            _audit.audit_log("keys.add", f"KEY_{i}")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()

        # Tamper the 3rd line's payload (seq=3) without touching its prev_hash.
        tampered = json.loads(lines[2])
        tampered["detail"] = "TAMPERED"
        lines[2] = json.dumps(tampered)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = _audit.verify_chain()
        assert result.break_at is not None
        # Line 3's own prev_hash (pointing at line 2) is untouched, so the
        # mismatch only becomes provable at line 4, whose stored prev_hash no
        # longer matches the (now-tampered) line 3's recomputed hash.
        assert result.break_at.line == 4
        assert "prev_hash mismatch" in result.break_at.reason
        # Everything before the break was still counted as chained.
        assert result.chained == 3
        # total_lines (G-4b) still reports the full file length even though
        # counting stopped at the break.
        assert result.total_lines == 5

    def test_malformed_json_line_reported_not_crashed(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        logf.write_text("{not valid json\n", encoding="utf-8")
        result = _audit.verify_chain()
        assert result.break_at is not None
        assert result.break_at.line == 1
        assert "malformed" in result.break_at.reason
        assert result.total_lines == 1

    def test_legacy_unchained_line_is_not_tampering(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        legacy = {
            "ts": "2026-06-01T00:00:00Z",
            "user": "alice",
            "pid": 1,
            "action": "gates.enable",
            "detail": "",
        }
        logf.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        logf.chmod(0o600)

        _audit.audit_log("keys.add", "AFTER_LEGACY")

        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.legacy == 1
        assert result.chained == 1
        # The chain restarts fresh right after the legacy line.
        entries = _audit.read_audit()
        assert entries[1]["seq"] == 1
        assert entries[1]["prev_hash"] == _audit.GENESIS_HASH

    def test_legacy_lines_dont_crash_the_viewer(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        logf.write_text(
            '{"ts": "x", "user": "a", "pid": 1, "action": "gates.enable", "detail": ""}\n',
            encoding="utf-8",
        )
        rc = audit_cli.run_audit()
        assert rc == 0

    def test_rotation_starts_a_fresh_chain_and_is_reported(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")
        _audit.audit_log("keys.add", "SECOND")

        assert (audit_home / "audit.log.1").exists()
        result = _audit.verify_chain()
        assert result.rotated_backup is True
        assert result.break_at is None
        assert result.chained == 1  # only "SECOND" is in the current file
        assert result.total_lines == 1  # rotated-away "FIRST" isn't in this count either


class TestAuditVerifyCommand:
    def test_verify_missing_log(self, audit_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = audit_cli.run_audit_verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Nothing to verify" in out

    def test_verify_clean_log(self, audit_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _audit.audit_log("keys.add", "A")
        rc = audit_cli.run_audit_verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "verified clean" in out

    def test_verify_tampered_log_fails_with_line_number(
        self, audit_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[0])
        e["detail"] = "TAMPERED"
        lines[0] = json.dumps(e)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = audit_cli.run_audit_verify()
        captured = capsys.readouterr()
        assert rc == 1
        assert "line 2" in captured.err

    def test_verify_tampered_log_reports_total_lines(
        self, audit_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # G-4b: VerifyResult.total_lines is rendered in the one place it adds
        # information chained+legacy can't (how much of the file lies beyond
        # the detected break, since counting stops there).
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        _audit.audit_log("keys.add", "C")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[0])
        e["detail"] = "TAMPERED"
        lines[0] = json.dumps(e)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = audit_cli.run_audit_verify()
        captured = capsys.readouterr()
        assert rc == 1
        assert "line 2 of 3" in captured.err


# ── new call-site coverage ───────────────────────────────────────────────────


class TestKeysAudit:
    @pytest.fixture()
    def keys_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        d = tmp_path / ".openclaw"
        d.mkdir()
        monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
        monkeypatch.setenv("DOCKET_NO_RESTART", "1")
        monkeypatch.setattr(
            keys_cli._getpass, "getpass", lambda *a, **k: "sk-ant-testvalue00000000000000"
        )
        return d

    def test_keys_add_writes_one_entry_no_secret_value(self, keys_home: Path) -> None:
        rc = keys_cli._keys_add("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.add")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"
        assert "sk-ant-testvalue" not in json.dumps(entries)

    def test_keys_rotate_writes_one_entry_no_secret_value(self, keys_home: Path) -> None:
        keys_cli._keys_add("ANTHROPIC_API_KEY")
        rc = keys_cli._keys_rotate("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.rotate")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"
        assert "sk-ant-testvalue" not in json.dumps(entries)

    def test_keys_remove_writes_one_entry(self, keys_home: Path) -> None:
        keys_cli._keys_add("ANTHROPIC_API_KEY")
        rc = keys_cli._keys_remove("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.remove")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"


class TestScopeAudit:
    def test_scope_set_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_scope("demo", "set", "beta")
        entries = _entries("scope.set")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=beta"

    def test_scope_reset_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_scope("demo", "reset", None)
        entries = _entries("scope.reset")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"


class TestProfileAudit:
    def test_profile_budget_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_profile("demo", None, budget="5")
        entries = _entries("profile.budget")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=$5"

    def test_profile_model_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_profile("demo", "anthropic/claude-haiku-4-5", budget=None)
        entries = _entries("profile.model")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=anthropic/claude-haiku-4-5 (pinned)"


class TestPersonaAudit:
    def test_persona_set_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_persona("demo", "set", "Orion 🔭")
        entries = _entries("persona.set")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=Orion 🔭"

    def test_persona_clear_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_persona("demo", "set", "Orion 🔭")
        cli.cmd_persona("demo", "clear", None)
        entries = _entries("persona.clear")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"


class TestAgentAddDeleteAudit:
    def test_agent_add_declarative_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        (oc_dir / "workspaces" / "projects").mkdir(parents=True)
        cfg_file = oc_dir / "openclaw.json"
        cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
        monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
        monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", oc_dir / "audit.log", raising=True)
        monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
        monkeypatch.setenv("DOCKET_NO_RESTART", "1")

        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                {
                    "id": "declaredagent",
                    "name": "Declared",
                    "codebase": "",
                    "stack": "",
                    "model": "",
                    "description": "",
                }
            )
        )

        rc = run_add(["--from", str(spec_file)])
        assert rc == 0

        entries = _entries("agent.add")
        assert len(entries) == 1
        assert entries[0]["detail"].startswith("declaredagent model=")
        assert entries[0]["detail"].endswith("source=declarative")

    def test_agent_delete_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        responses = iter(["n", "demo"])  # keep workspace, confirm id
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(responses))

        rc = run_delete("demo")
        assert rc == 0

        entries = _entries("agent.delete")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"
