"""`docket maintain <id> rebuild` wiring.

Covers `cli/_agents.py::_maintain_rebuild`: for a legacy flat agent, backup + regenerate
must never touch `memory/*.md` (the rule `clean`/`reset` already enforce: memory is never
bare-deleted); for a pod member (meta carries a `pod` key or a non-empty `role`, written by
`core/pod_provisioning.py`), rebuild must refuse with exit 1 before the confirmation prompt
and before any write. Calls `run_maintain` directly with `sys.stdin.isatty`/`builtins.input`
monkeypatched for the confirm prompt -- no live daemon anywhere in this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _agents
from docket.core import memory as _mem

SUBJECT = "docket.cli._agents"


def _make_flat_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str = "demo") -> Path:
    home = tmp_path / ".docket"
    repoint_docket_home(monkeypatch, home)
    ws = _cfg.PROJECTS_DIR / agent_id
    (ws / "memory").mkdir(parents=True)
    meta = {
        "schemaVersion": 1,
        "kind": "project",
        "name": "Demo Agent",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "codebase": "/tmp/demo",
        "stack": "Python",
        "description": "demo",
        "sessionKey": f"agent:{agent_id}:default",
        "projectKey": "default",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ws / "SOUL.md").write_text("# SOUL.md\noriginal\n", encoding="utf-8")
    (ws / "AGENTS.md").write_text("# AGENTS.md\n", encoding="utf-8")
    (ws / "HEARTBEAT.md").write_text(_mem.heartbeat_seed("Demo Agent"), encoding="utf-8")
    return ws


def _make_pod_member_ws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str = "demo-reviewer"
) -> Path:
    ws = _make_flat_ws(tmp_path, monkeypatch, agent_id)
    meta_path = ws / ".docket-meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["pod"] = "demo"
    meta["role"] = "reviewer"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return ws


def _confirm_with(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr(_agents.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: answer)


def _forbid_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdin reports a TTY, but `input()` raises -- proves rebuild refuses a pod
    member before the confirmation prompt, not merely before any write."""
    monkeypatch.setattr(_agents.sys.stdin, "isatty", lambda: True)

    def _raise(*_a: object, **_k: object) -> str:
        raise AssertionError("confirmation prompt must not run for a pod member")

    monkeypatch.setattr("builtins.input", _raise)


class TestMaintainRebuildFlatAgent:
    def test_memory_logs_survive_rebuild_byte_identical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_flat_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-01-01.md"
        log.write_text("notes\n", encoding="utf-8")
        before = log.read_bytes()
        _confirm_with(monkeypatch, "demo")

        rc = _agents.run_maintain("demo", "rebuild")

        assert rc == 0
        assert log.is_file()
        assert log.read_bytes() == before


class TestMaintainRebuildPodMember:
    def test_pod_member_refused_exit_1_no_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_pod_member_ws(tmp_path, monkeypatch)
        soul = ws / "SOUL.md"
        before = soul.read_bytes()
        _forbid_prompt(monkeypatch)

        rc = _agents.run_maintain("demo-reviewer", "rebuild")

        assert rc == 1
        assert soul.read_bytes() == before
        assert not list(ws.glob(".backup-*"))


class TestMaintainCheckContextBudget:
    """`docket maintain <id> check`'s context-footprint line names the resolved
    static-context budget and its source."""

    def test_unregistered_model_reports_the_plain_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ws = _make_flat_ws(tmp_path, monkeypatch)
        (ws / "TOOLS.md").write_text("# TOOLS.md\n", encoding="utf-8")

        rc = _agents.run_maintain("demo", "check")

        assert rc == 0
        out = capsys.readouterr().out
        assert f"budget {_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT:,} via default" in out

    def test_a_registered_large_window_reports_a_window_share(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import fleet as _fleet

        ws = _make_flat_ws(tmp_path, monkeypatch, agent_id="demo-hosted")
        (ws / "TOOLS.md").write_text("# TOOLS.md\n", encoding="utf-8")
        meta_path = ws / ".docket-meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["model"] = "hosted-test/big-model"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        _fleet.add_local_provider(
            "hosted-test", "http://127.0.0.1:9/v1", "big-model", "Big Model", 200_000, 8_192
        )

        rc = _agents.run_maintain("demo-hosted", "check")

        assert rc == 0
        out = capsys.readouterr().out
        assert "via window" in out
        assert f"budget {_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT:,}" not in out
