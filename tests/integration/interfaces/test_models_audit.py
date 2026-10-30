"""Audit coverage for `models.*` — docket setup model set/preset/reset.

`docket setup model set/preset/reset` change the role->model policy for the entire fleet. Covers: each
writes exactly one `models.*` audit entry naming the role(s) affected (or `default`) and the
before/after model, so the log alone answers "which role changed, from what, to what, and when";
and those entries carry the same hash-chain fields (`seq`/`prev_hash`) as every other family, so
`docket log verify` walks a log containing them without reporting a break.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support.home import register_local_provider
from tests.support.pods import setup_agent as _setup_agent
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.kernel.home import Home, use_home

SUBJECT = "docket.interfaces.cli.commands.setup_model"

_runner = CliRunner()

META: dict[str, Any] = {
    "kind": "project",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}


def _register_openai(oc_dir: Path) -> None:
    (oc_dir / "state").mkdir(parents=True, exist_ok=True)
    (oc_dir / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    register_local_provider(oc_dir, "openai", [{"id": "gpt-4.1-mini"}])


def _run(args: list[str], oc_dir: Path, input_text: str | None = None) -> tuple[int, str, str]:
    with use_home(Home(oc_dir)):
        result = _runner.invoke(_app, args, input=input_text)
    return result.exit_code, result.stdout, result.stderr


def _audit_entries(oc_dir: Path, action: str) -> list[dict[str, Any]]:
    logf = oc_dir / "state" / "audit.log"
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
# docket setup model set
# ---------------------------------------------------------------------------


class TestModelsSetAudit:
    def test_set_role_writes_one_entry_with_before_and_after(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, err = _run(
            ["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir
        )
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "role=implementer" in detail
        assert "anthropic/claude-sonnet-4-6" in detail  # before (built-in strong default)
        assert "anthropic/claude-haiku-4-5" in detail  # after
        assert "->" in detail

    def test_set_default_key_recorded_as_role_default(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _out, _err = _run(
            ["setup", "model", "set", "default", "anthropic/claude-haiku-4-5"], oc_dir
        )
        assert rc == 0
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 1
        assert "role=default" in entries[0]["detail"]
        assert "anthropic/claude-haiku-4-5" in entries[0]["detail"]

    def test_set_entry_carries_chain_fields(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        entries = _audit_entries(oc_dir, "models.set")
        assert entries[0]["seq"] == 1
        assert "prev_hash" in entries[0]
        assert "ts" in entries[0] and "user" in entries[0] and "pid" in entries[0]

    def test_set_second_change_shows_the_real_before_value(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["setup", "model", "set", "implementer", "openai/gpt-4.1"], oc_dir)
        entries = _audit_entries(oc_dir, "models.set")
        assert len(entries) == 2
        # The second entry's "before" must be what the first entry set, not
        # the original built-in default — proof the code reads the live
        # registry rather than a stale constant.
        assert "anthropic/claude-haiku-4-5->openai/gpt-4.1" in entries[1]["detail"]

    def test_set_unknown_role_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(
            ["setup", "model", "set", "unicorn", "anthropic/claude-haiku-4-5"], oc_dir
        )
        assert rc == 1
        assert _audit_entries(oc_dir, "models.set") == []

    def test_set_invalid_model_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["setup", "model", "set", "implementer", "notamodel"], oc_dir)
        assert rc == 1
        assert _audit_entries(oc_dir, "models.set") == []


# ---------------------------------------------------------------------------
# docket setup model preset
# ---------------------------------------------------------------------------


class TestModelsPresetAudit:
    def test_preset_apply_writes_one_entry_naming_every_role(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _register_openai(oc_dir)
        rc, _out, err = _run(["setup", "model", "preset", "openai"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.preset")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "preset=openai" in detail
        assert "default:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini" in detail
        # cheap-class role
        assert "lead:anthropic/claude-haiku-4-5->openai/gpt-4.1-nano" in detail
        # strong-class role
        assert "implementer:anthropic/claude-sonnet-4-6->openai/gpt-4.1-mini" in detail
        # every ALL_ROLES member is named, not just a summary count
        for role in (
            "lead",
            "implementer",
            "reviewer",
            "researcher",
            "analyst",
            "writer",
            "reviewer",
            "operator",
            "monitor",
        ):
            assert f"{role}:" in detail

    def test_preset_unknown_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, _, _err = _run(["setup", "model", "preset", "notapreset"], oc_dir)
        assert rc == 1
        assert _audit_entries(oc_dir, "models.preset") == []


# ---------------------------------------------------------------------------
# docket setup model reset
# ---------------------------------------------------------------------------


class TestModelsResetAudit:
    def test_reset_writes_one_entry_with_real_before_values(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        rc, _out, err = _run(["setup", "model", "reset", "--yes"], oc_dir)
        assert rc == 0, f"exit {rc}\nstderr: {err}"
        entries = _audit_entries(oc_dir, "models.reset")
        assert len(entries) == 1
        detail = entries[0]["detail"]
        assert "implementer:anthropic/claude-haiku-4-5->anthropic/claude-sonnet-4-6" in detail
        assert "default:" in detail

    def test_reset_without_yes_off_a_terminal_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        rc, _out, err = _run(["setup", "model", "reset"], oc_dir)
        assert rc == 1
        assert "--yes" in err
        assert _audit_entries(oc_dir, "models.reset") == []

    def test_reset_with_no_overrides_writes_no_entry(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        rc, out, _err = _run(["setup", "model", "reset", "--yes"], oc_dir)
        assert rc == 0
        assert "No overrides" in out
        assert _audit_entries(oc_dir, "models.reset") == []


# ---------------------------------------------------------------------------
# chain integrity across the new family
# ---------------------------------------------------------------------------


class TestModelsAuditChainIntegrity:
    def test_audit_verify_passes_over_a_log_with_models_entries(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["setup", "model", "preset", "openai"], oc_dir)
        _run(["setup", "model", "reset"], oc_dir, input_text="y\n")

        rc, out, err = _run(["log", "verify"], oc_dir)
        assert rc == 0, f"stdout: {out}\nstderr: {err}"
        assert "verified clean" in out

    def test_models_entries_interleave_cleanly_with_other_families(self, tmp_path: Path) -> None:
        oc_dir = _setup_agent(tmp_path)
        _register_openai(oc_dir)
        _run(["setup", "model", "set", "implementer", "anthropic/claude-haiku-4-5"], oc_dir)
        _run(["setup", "model", "set", "reviewer", "anthropic/claude-opus-4-6"], oc_dir)
        _run(["setup", "model", "preset", "openai"], oc_dir)

        rc, out, err = _run(["log", "verify"], oc_dir)
        assert rc == 0, f"stdout: {out}\nstderr: {err}"
        assert "verified clean" in out
        assert _audit_entries(oc_dir, "models.set")
        assert _audit_entries(oc_dir, "models.preset")
