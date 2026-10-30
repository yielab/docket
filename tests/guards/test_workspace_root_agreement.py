"""The paths a member is *told* to work in must be inside the roots it is *gated* against.

A pod member learns where the code lives from the hop message and from ``WORKFLOW_AUTO.md``/
``TOOLS.md``; ``SOUL.md`` and ``AGENTS.md`` name no path. Its tool calls are separately
contained by ``docket_runtime._resolve_roots``; a task's worktree reaches the driver as the
pipeline root instead, and the hop message says only that the tools start at the repository root.

When those two disagree the failure is silent and expensive: every read
of the advertised path is refused, the model retries other spellings, the
turn dies on the token budget with no tool call having succeeded, and
nothing crashes. These tests pin the agreement, not any path text.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import docket.teams.agent_memory as _mem
from docket.hops.application.driver_support import _resolve_roots
from docket.kernel.home import current_home
from docket.teams.member_workspace import provision_member
from docket.teams.models import AgentMeta
from docket.teams.pod import PodMember

_MODEL = "anthropic/claude-haiku-4-5-20251001"


def _make_member(role: str, project: str = "myapp") -> PodMember:
    member_id = f"{project}-{role}"
    return PodMember(
        member_id=member_id,
        role=role,
        project=project,
        model=_MODEL,
        session_key=f"agent:{member_id}:{project}",
        index=0,
    )


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    for key, val in (("user.email", "t@t.test"), ("user.name", "T")):
        subprocess.run(
            ["git", "-C", str(path), "config", key, val], check=True, capture_output=True
        )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True
    )


def _roots_for(member_id: str) -> tuple[Path, ...]:
    """Exactly what the driver will gate this member's tool calls against."""
    raw = json.loads(
        (current_home().workspace_dir(member_id) / current_home().meta_file).read_text()
    )
    return _resolve_roots(AgentMeta.model_validate(raw), member_id)


def _advertised_paths(text: str) -> list[Path]:
    """Absolute paths docket wrote into a workspace file as a place to work."""
    return [Path(m) for m in re.findall(r"`?(/[\w./-]+)`?", text) if m.startswith("/")]


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == r or r in path.parents for r in roots)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    codebase = tmp_path / "codebase"
    _init_git_repo(codebase)
    return codebase


def _provision(member: PodMember, codebase: Path) -> None:
    ok, _msg = provision_member(
        member,
        codebase=str(codebase),
        stack="python",
        description="a project",
        project=member.project,
        project_key=f"proj:{member.project}",
        port_range_start=4100,
        port_range_count=10,
        scratch_dir="/tmp/scratch",
    )
    assert ok


# ── the invariant ──────────────────────────────────────────────────────────────


def test_soul_and_agents_name_no_path(repo: Path) -> None:
    """The system prompt carries no root, so it cannot disagree with the tools' roots."""
    member = _make_member("implementer")
    _provision(member, repo)

    ws = current_home().workspace_dir(member.member_id)
    for name in ("SOUL.md", "AGENTS.md"):
        assert not re.search(r"(^|[\s`(])/[\w.-]+/", (ws / name).read_text()), name


@pytest.mark.parametrize("role", ["lead", "implementer", "reviewer"])
def test_the_task_message_names_no_path_and_its_root_is_one_the_tools_accept(
    repo: Path, role: str
) -> None:
    """The hop message states the root without a path, and the root it stands for is gated in."""
    from docket.hops.application import compose
    from docket.tasks.domain.task import TaskRecord
    from docket.teams.workspace import repo_map

    member = _make_member(role)
    _provision(member, repo)

    message, _ = compose._hop_message(TaskRecord(description="x"), role, [], project=member.project)
    root = repo_map.resolve_root("", member.project, role)

    assert repo_map.WORKING_DIRECTORY_LINE in message
    assert not re.search(r"(^|[\s`(])/[\w.-]+/", message)
    assert _inside(Path(root), _roots_for(member.member_id))


def test_implementer_startup_contract_names_a_path_inside_its_own_roots(repo: Path) -> None:
    """Same for WORKFLOW_AUTO.md, which is re-read after every context reset."""
    member = _make_member("implementer")
    _provision(member, repo)

    roots = _roots_for(member.member_id)
    contract = (
        current_home().workspace_dir(member.member_id) / _mem.REQUIRED_STARTUP_FILE
    ).read_text()

    outside = [
        p
        for p in _advertised_paths(contract)
        if not _inside(p, roots) and str(p).startswith(str(repo))
    ]
    assert not outside, f"startup contract points outside the allowed roots {roots}: {outside}"


def test_implementer_tools_md_names_a_root_inside_its_own_roots(repo: Path) -> None:
    """TOOLS.md's project root is a path the tools will accept."""
    member = _make_member("implementer")
    _provision(member, repo)

    tools = (current_home().workspace_dir(member.member_id) / "TOOLS.md").read_text()
    project_root = tools.split("Project root:", 1)[1].split("\n", 1)[0].strip().strip("`")

    assert _inside(Path(project_root), _roots_for(member.member_id))


def test_implementer_has_no_member_worktree(repo: Path) -> None:
    """The per-task worktree is made at claim, so provisioning records only the codebase."""
    member = _make_member("implementer")
    _provision(member, repo)

    raw = json.loads(
        (current_home().workspace_dir(member.member_id) / current_home().meta_file).read_text()
    )
    assert "worktreeDir" not in raw
    assert raw["codebase"] == str(repo)


# ── the members that must NOT change ───────────────────────────────────────────


@pytest.mark.parametrize("role", ["lead", "reviewer"])
def test_other_roles_are_told_the_codebase(repo: Path, role: str) -> None:
    """Every role's startup contract names the plain codebase."""
    member = _make_member(role)
    _provision(member, repo)

    ws = current_home().workspace_dir(member.member_id)
    contract = (ws / _mem.REQUIRED_STARTUP_FILE).read_text()
    assert f"`{repo}`" in contract
    assert _inside(Path(str(repo)), _roots_for(member.member_id))


# ── the second writer of that path: `docket setup --fix`'s contract heal ────────────


def test_doctor_contract_heal_keeps_the_member_inside_its_roots(repo: Path) -> None:
    """Healing a stale contract must keep the member inside its roots."""
    from docket.interfaces.cli.commands.setup_check_config import _check_runtime_contract

    member = _make_member("implementer")
    _provision(member, repo)

    ws = current_home().workspace_dir(member.member_id)
    contract = ws / _mem.REQUIRED_STARTUP_FILE
    contract.write_text("# stale, no contract marker\n", encoding="utf-8")
    assert not _mem.contract_ok(ws)

    _check_runtime_contract([member.member_id])

    roots = _roots_for(member.member_id)
    healed = contract.read_text()
    assert _mem.contract_ok(ws)
    outside = [
        p
        for p in _advertised_paths(healed)
        if not _inside(p, roots) and str(p).startswith(str(repo))
    ]
    assert not outside, f"doctor healed the contract to a path outside {roots}: {outside}"
