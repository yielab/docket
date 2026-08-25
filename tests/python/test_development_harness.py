"""Behavioral tests for the bounded repository-development harness.

These fixtures model the states that make roadmap decisions risky: an explicitly
clear current board above historical work, unavailable Git state, and a snapshot
whose optional details exceed the hook's context budget.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPT = ROOT / ".agents" / "skills" / "docket-roadmap" / "scripts" / "context_snapshot.py"


def _load_snapshot_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docket_context_snapshot", SNAPSHOT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_board(root: Path, text: str) -> None:
    (root / "TODO.md").write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


def test_current_board_clear_never_resurrects_historical_ready_work(tmp_path: Path) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        # TODO

        ## ☑ BOARD CLEAR (current)

        No work is scheduled.

        ## ◉ OLD WAVE ACTIVE (historical record)

        ### OLD-1 — do not schedule me

        **Status:** READY
        """,
    )

    board, cards, closed = module._board_summary(tmp_path)

    assert "BOARD CLEAR" in board
    assert not any(cards.values())
    assert closed == 0


def test_completed_document_without_current_marker_is_not_schedulable(tmp_path: Path) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        # TODO

        ## ☑ WAVE 9 COMPLETE

        ### OLD-READY — stale card

        **Status:** READY
        """,
    )

    board, cards, closed = module._board_summary(tmp_path)

    assert board == "no unambiguous current board marker found"
    assert not any(cards.values())
    assert closed == 0


def test_active_banner_resolves_to_detailed_current_section_before_history(tmp_path: Path) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## ◉ ACTIVE BOARD — Wave 2

        Current-wave summary without cards.

        ## How to use this board

        Instructions are not a card section.

        ## ◉ WAVE 2 ACTIVE

        ### W2-C1 — current ready card

        **Status:** READY

        ## ☑ WAVE 1 COMPLETE

        ### W1-C9 — historical ready-looking card

        **Status:** READY
        """,
    )

    board, cards, closed = module._board_summary(tmp_path)

    assert board == "◉ WAVE 2 ACTIVE"
    assert cards["ready"] == ["W2-C1 — current ready card"]
    assert "W1-C9 — historical ready-looking card" not in cards["ready"]
    assert closed == 0


def test_active_banner_does_not_cross_an_unrelated_h2_into_historical_work(
    tmp_path: Path,
) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## ◉ ACTIVE BOARD (current)

        No current cards are listed.

        ## Historical archive

        ## ◉ OLD WAVE ACTIVE

        ### OLD-1 — stale ready card

        **Status:** READY
        """,
    )

    board, cards, closed = module._board_summary(tmp_path)

    assert board == "◉ ACTIVE BOARD (current)"
    assert not any(cards.values())
    assert closed == 0


def test_missing_current_marker_before_historical_active_section_is_ambiguous(
    tmp_path: Path,
) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## Current board

        No recognized active or clear marker is present.

        ## Historical archive

        ## ◉ OLD WAVE ACTIVE

        ### OLD-1 — stale ready card

        **Status:** READY
        """,
    )

    board, cards, closed = module._board_summary(tmp_path)

    assert board == "no unambiguous current board marker found"
    assert not any(cards.values())
    assert closed == 0


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "oserror"])
def test_git_probe_failures_return_unknown_instead_of_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    module = _load_snapshot_module()

    def failed_run(*args: object, **kwargs: object) -> SimpleNamespace:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd="git", timeout=3)
        if failure == "oserror":
            raise OSError("git unavailable")
        return SimpleNamespace(returncode=1, stdout="", stderr="fatal")

    monkeypatch.setattr(module.subprocess, "run", failed_run)

    assert module._git(tmp_path, "status", "--short") is None


def test_unknown_git_state_blocks_claim_and_parallel_advice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## ◉ WAVE 1 ACTIVE

        ### C1 — ready work

        **Status:** READY
        """,
    )
    monkeypatch.setattr(module, "_git", lambda *args: None)

    output = module.snapshot(tmp_path, max_files=12, max_chars=1800)

    assert "dirty: unknown" in output
    assert "next selection: resolve git status before claim or parallel work" in output
    assert "dirty: clean" not in output


def test_snapshot_keeps_decision_fields_inside_exact_character_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_snapshot_module()
    long_title = "realistic card with a deliberately long ownership boundary " * 8
    cards = "\n".join(f"### C{index} — {long_title}\n\n**Status:** READY" for index in range(8))
    _write_board(tmp_path, f"## ◉ WAVE ACTIVE\n\n{cards}")

    def fake_git(root: Path, *args: str) -> str:
        del root
        if args == ("branch", "--show-current"):
            return "feature/a-very-long-real-world-branch-name"
        return "\n".join(f" M src/changed_{index}.py" for index in range(30))

    monkeypatch.setattr(module, "_git", fake_git)

    output = module.snapshot(tmp_path, max_files=3, max_chars=256)

    assert len(output) <= 256
    for field in ("board:", "next:", "dirty:", "routing:", "authority:"):
        assert field in output
    assert "board: ◉" in output
    assert "next: expand full dirty status" in output
    assert "dirty: incomplete" in output


def test_clipped_dirty_list_requires_full_status_before_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## ◉ WAVE ACTIVE

        ### C1 — apparently independent card

        **Status:** READY
        """,
    )

    def fake_git(root: Path, *args: str) -> str:
        del root
        if args == ("branch", "--show-current"):
            return "main"
        return " M visible.py\n M hidden-collision.py"

    monkeypatch.setattr(module, "_git", fake_git)

    output = module.snapshot(tmp_path, max_files=1, max_chars=1800)

    assert "dirty: incomplete (2 changed paths; --max-files=1)" in output
    assert "next selection: expand full dirty status before claim or parallel work" in output


def test_character_clipped_dirty_paths_also_block_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_snapshot_module()
    _write_board(
        tmp_path,
        """
        ## ◉ WAVE ACTIVE

        ### C1 — ready card

        **Status:** READY
        """,
    )

    def fake_git(root: Path, *args: str) -> str:
        del root
        if args == ("branch", "--show-current"):
            return "main"
        return "\n".join(f" M src/{'nested/' * 30}changed_{index}.py" for index in range(6))

    monkeypatch.setattr(module, "_git", fake_git)

    output = module.snapshot(tmp_path, max_files=12, max_chars=1800)

    assert "dirty: incomplete (6 changed paths; details clipped)" in output
    assert "next selection: expand full dirty status before claim or parallel work" in output


def test_cli_board_clear_ignores_historical_ready_card(tmp_path: Path) -> None:
    _write_board(
        tmp_path,
        """
        ## ☑ BOARD CLEAR (current)

        No task is scheduled.

        ## ◉ OLD WAVE ACTIVE

        ### OLD-1 — stale ready card

        **Status:** READY
        """,
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=5)
    subprocess.run(["git", "add", "TODO.md"], cwd=tmp_path, check=True, timeout=5)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=Fixture",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        timeout=5,
    )

    result = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "board: ☑ BOARD CLEAR (current)" in result.stdout
    assert "OLD-1" not in result.stdout
    assert "next selection: no ready card; run bounded triage/measurement" in result.stdout
    assert "dirty: clean" in result.stdout


def test_cli_survives_a_non_git_fixture_and_reports_unknown_state(tmp_path: Path) -> None:
    _write_board(tmp_path, "## ◉ WAVE ACTIVE")

    result = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "dirty: unknown" in result.stdout
    assert "resolve git status before claim or parallel work" in result.stdout


def test_cli_discovers_repository_root_from_a_nested_working_directory(tmp_path: Path) -> None:
    _write_board(tmp_path, "## ◉ WAVE ACTIVE")
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=5)

    result = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT)],
        cwd=nested,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "board: ◉ WAVE ACTIVE" in result.stdout
    assert "TODO.md missing" not in result.stdout


def test_claude_bridge_imports_the_canonical_contract_without_duplicate_skills() -> None:
    bridge = (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")

    assert "@../AGENTS.md" in bridge
    assert ".agents/skills" in bridge
    assert not (ROOT / ".claude" / "skills").exists()
    for shared in (".claude/CLAUDE.md", ".claude/settings.json"):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", shared], cwd=ROOT, check=False, timeout=5
        )
        assert ignored.returncode == 1


def test_harness_hooks_are_portable_and_use_the_same_snapshot() -> None:
    codex = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    codex_command = codex["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    claude_command = claude["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert (
        codex["hooks"]["SessionStart"][0]["matcher"]
        == (claude["hooks"]["SessionStart"][0]["matcher"])
    )
    for command in (codex_command, claude_command):
        assert "/usr/bin/python" not in command
        assert "python3" in command
        assert "context_snapshot.py" in command
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(ROOT)
        result = subprocess.run(
            ["sh", "-c", command],
            cwd=ROOT / "src",
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "TODO.md missing" not in result.stdout


def test_shared_instructions_use_harness_neutral_skill_routing() -> None:
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "$docket-" not in instructions
    for skill in ("docket-roadmap", "docket-spec-work", "docket-context-runtime"):
        assert skill in instructions
