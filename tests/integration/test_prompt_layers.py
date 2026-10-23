"""A pod member's system prompt is the same bytes for two tasks in different worktrees."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.pods import build_pod

from docket.cli import _pod
from docket.core import archetypes as _arch
from docket.core import identity as _identity
from docket.core import tools as _tools
from docket.kernel.home import Home, use_home

SUBJECT = "docket.core.identity"

_MEMBER = "demo-implementer"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "AGENTS.md").write_text("REPO-CONVENTION-LINE\n")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    return path


@pytest.fixture
def pod_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(_checkout(tmp_path / "origin")))
        yield home


def test_two_worktrees_compose_a_byte_identical_system_prompt(
    tmp_path: Path, pod_home: Path
) -> None:
    first = _checkout(tmp_path / "wt-one")
    second = _checkout(tmp_path / "wt-two")

    one = _identity.compose_agent_prompt(_MEMBER, project_roots=(first,))
    two = _identity.compose_agent_prompt(_MEMBER, project_roots=(second,))

    assert one.text == two.text
    assert one.text
    assert str(first) not in one.text and str(tmp_path) not in one.text


def test_tool_schemas_do_not_depend_on_the_worktree() -> None:
    first = _arch.registry_for_role(_tools.builtin_registry(), "implementer", "demo").specs()
    second = _arch.registry_for_role(_tools.builtin_registry(), "implementer", "demo").specs()
    assert first == second


def test_a_pod_task_prompt_holds_no_heartbeat_or_tools_text_and_no_roots(
    tmp_path: Path, pod_home: Path
) -> None:
    ws = pod_home / "workspaces" / "projects" / _MEMBER
    (ws / "HEARTBEAT.md").write_text("## Active Tasks\nLEDGER-SENTINEL\n")
    (ws / "TOOLS.md").write_text("TOOLS-SENTINEL\n")

    text = _identity.compose_agent_prompt(_MEMBER, project_roots=(_checkout(tmp_path / "wt"),)).text

    assert "LEDGER-SENTINEL" not in text and "TOOLS-SENTINEL" not in text
    assert "Project tools are restricted" not in text
    assert "Docket live runtime contract" in text


def test_layers_run_stable_first(tmp_path: Path, pod_home: Path) -> None:
    ws = pod_home / "workspaces" / "projects" / _MEMBER
    (ws / "MEMORY.md").write_text("## Facts\nMEMORY-SENTINEL\n")

    composition = _identity.compose_agent_prompt(
        _MEMBER, project_roots=(_checkout(tmp_path / "wt"),)
    )
    text = composition.text
    order = [
        text.index("# SOUL.md"),
        text.index("# AGENTS.md"),
        text.index("# Docket live runtime contract"),
        text.index("REPO-CONVENTION-LINE"),
        text.index("MEMORY-SENTINEL"),
    ]

    assert order == sorted(order)
    assert "## Session Startup" not in text
    assert "## Method" in text


def test_a_fresh_member_composes_no_memory_section(tmp_path: Path, pod_home: Path) -> None:
    composition = _identity.compose_agent_prompt(
        _MEMBER, project_roots=(_checkout(tmp_path / "wt"),)
    )

    assert "MEMORY.md" not in [section.name for section in composition.sections]
    assert "Runtime-loaded Docket workspace state" not in composition.text


def test_each_role_is_told_the_root_its_tools_use(tmp_path: Path, pod_home: Path) -> None:
    from docket.core import dispatch as _dispatch

    origin = str(tmp_path / "origin")
    worktree = _checkout(tmp_path / "wt")
    in_place = {"description": "do it"}
    claimed = {"description": "do it", "worktree": {"dir": str(worktree)}}

    lead, _ = _dispatch._hop_message(claimed, "lead", [], project="demo")
    implementer, _ = _dispatch._hop_message(claimed, "implementer", [], project="demo")
    in_place_implementer, _ = _dispatch._hop_message(in_place, "implementer", [], project="demo")

    assert f"Working directory: {origin}" in lead and str(worktree) not in lead
    assert f"Working directory: {worktree}" in implementer and origin not in implementer
    assert f"Working directory: {origin}" in in_place_implementer
    assert "src/ (1 file)" in implementer
