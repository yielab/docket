"""G-4b: audit coverage for `models.*` — docket models set/preset/reset.

`docket models set/preset/reset` change the role->model policy for the entire
fleet but wrote no audit entry (a gap ROADMAP Phase 15 G-4 named and left
open — see audit.spec.md's Version 2.0.0/2.1.0 changelog). This module covers
the closing of that gap:

  - Each of `set`/`preset`/`reset` writes exactly one `models.*` audit entry
    naming the role(s) affected (or `default`) and the before/after model, so
    the log alone answers "which role changed, from what, to what, and when"
    (mirrors `agent.add`'s whole-pod-in-one-line style for multi-role writes).
  - The entries carry the same hash-chain fields (`seq`/`prev_hash`) as every
    other family, and `docket audit verify` still walks a log containing them
    without reporting a break.

All tests run `python -m docket` as a subprocess with OPENCLAW_DIR overridden
and DOCKET_NO_RESTART=1, matching the existing `models`/`profile` subprocess
tests in test_m4_wave1.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {"sessionKey": "agent:myshop:default", "projectKey": "default"},
            }
        ],
    },
    "bindings": [],
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


def _make_env(oc_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "OPENCLAW_DIR": str(oc_dir),
        "DOCKET_HOME": str(oc_dir),
        "DOCKET_NO_RESTART": "1",
    }


def _setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))
    return oc_dir


def _run(args: list[str], oc_dir: Path, input_text: str | None = None) -> tuple[int, str, str]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "docket", *args],
        capture_output=True,
        text=True,
        input=input_text,
        env=_make_env(oc_dir),
    )
    return result.returncode, result.stdout, result.stderr


def _audit_entries(oc_dir: Path, action: str) -> list[dict[str, Any]]:
    logf = oc_dir / "audit.log"
    if not logf.is_file():
        return []
    out: list[dict[str, Any]] = []
    for raw in logf.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        entry = json.loads(line)
        if entry.get("action") == action:
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# docket models set
# ---------------------------------------------------------------------------


class TestModelsSetAudit:
    def test_set_role_writes_one_entry_with_before_and_after(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "role=programmer" in detail
        assert "anthropic/claude-sonnet-4-6" in detail  # before (built-in strong default)
        assert "anthropic/claude-haiku-4-5" in detail  # after
        assert "->" in detail

    def test_set_default_key_recorded_as_role_default(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, _err = _run(["models", "set", "default", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 0
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 1
        assert "role=default" in entries[0]["detail"]
        assert "anthropic/claude-haiku-4-5" in entries[0]["detail"]

    def test_set_entry_carries_chain_fields(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        entries = _audit_entries(oc_dir, "models.set")
        assert entries[0]["seq"] == 1
        assert "prev_hash" in entries[0]
        assert "ts" in entries[0] and "user" in entries[0] and "pid" in entries[0]

    def test_set_second_change_shows_the_real_before_value(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["models", "set", "programmer", "openai/gpt-4.1"], oc_dir)
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 2
        # The second entry's "before" must be what the first entry set, not
        # the original built-in default — proof the code reads the live
        # registry rather than a stale constant.
        assert "anthropic/claude-haiku-4-5->openai/gpt-4.1" in entries[1]["detail"]

    def test_set_unknown_role_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["models", "set", "unicorn", "anthropic/claude-haiku-4-5"], oc_dir)
        assert rc == 1
        assert _audit_entries(oc_dir, "models.set") == []

    def test_set_invalid_model_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["models", "set", "programmer", "notamodel"], oc_dir)
        assert rc == 1
        assert _audit_entries(oc_dir, "models.set") == []


# ---------------------------------------------------------------------------
# docket models preset
# ---------------------------------------------------------------------------


class TestModelsPresetAudit:
    def test_preset_apply_writes_one_entry_naming_every_role(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(["models", "preset", "openai"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.preset")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "preset=openai" in detail
        assert "default:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini" in detail
        # cheap-class role
        assert "manager:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano" in detail
        # strong-class role
        assert "programmer:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini" in detail
        # every ALL_ROLES member is named, not just a summary count
        for role in (
            "manager",
            "reviewer",
            "tester",
            "knowledge",
            "programmer",
            "security",
            "repo",
        ):
            assert f"{role}:" in detail

    def test_preset_unknown_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["models", "preset", "notapreset"], oc_dir)
        assert rc == 1
        assert _audit_entries(oc_dir, "models.preset") == []


# ---------------------------------------------------------------------------
# docket models reset
# ---------------------------------------------------------------------------


class TestModelsResetAudit:
    def test_reset_writes_one_entry_with_real_before_values(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        rc, _out, err = _run(["models", "reset"], oc_dir, input_text="y\n")
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.reset")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "programmer:anthropic/claude-haiku-4-5->anthropic/claude-sonnet-4-6" in detail
        assert "default:" in detail

    def test_reset_aborted_confirmation_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        rc, out, _err = _run(["models", "reset"], oc_dir, input_text="n\n")
        assert rc == 0
        assert "Aborted" in out
        assert _audit_entries(oc_dir, "models.reset") == []

    def test_reset_with_no_overrides_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _err = _run(["models", "reset"], oc_dir, input_text="y\n")
        assert rc == 0
        assert "No user overrides" in out
        assert _audit_entries(oc_dir, "models.reset") == []


# ---------------------------------------------------------------------------
# chain integrity across the new family
# ---------------------------------------------------------------------------


class TestModelsAuditChainIntegrity:
    def test_audit_verify_passes_over_a_log_with_models_entries(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["models", "preset", "openai"], oc_dir)
        _run(["models", "reset"], oc_dir, input_text="y\n")

        rc, out, err = _run(["audit", "verify"], oc_dir)
        assert rc == 0, f"stdout: {out}\nstderr: {err}"
        assert "verified clean" in out

    def test_models_entries_interleave_cleanly_with_other_families(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["models", "set", "programmer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["profile", "myshop", "anthropic/claude-opus-4-6"], oc_dir)
        _run(["models", "preset", "openai"], oc_dir)

        rc, out, err = _run(["audit", "verify"], oc_dir)
        assert rc == 0, f"stdout: {out}\nstderr: {err}"
        assert "verified clean" in out
        assert _audit_entries(oc_dir, "models.set")
        assert _audit_entries(oc_dir, "profile.model")
        assert _audit_entries(oc_dir, "models.preset")
