"""The paths a member is *told* to work in must be inside the roots it is *gated* against.

A pod member learns where the code lives from three docket-written files:
``SOUL.md`` (its system prompt), ``WORKFLOW_AUTO.md`` (the startup contract it
re-reads after every context reset) and, for a resourced Implementer,
``TOOLS.md``. Its tool calls are separately contained by
``docket_runtime._resolve_roots``, which returns the git worktree **alone**
when the member has one.

When those two disagree the failure is silent and expensive: every read of the
advertised path is refused as "resolves outside the allowed roots", the model
retries other spellings of the same path, and the turn dies on the token
budget with no tool call having succeeded. Nothing crashes, so no other test
notices.

These tests pin the agreement rather than any particular path text.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.core.memory as _mem
from docket.core.models import AgentMeta
from docket.core.pod import PodMember
from docket.core.pod_provisioning import provision_member
from docket.edges.adapters.docket_runtime import _resolve_roots

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
    raw = json.loads((_cfg.workspace_dir(member_id) / _cfg.META_FILE).read_text())
    return _resolve_roots(
        AgentMeta.model_validate(raw), str(raw.get("worktreeDir") or ""), member_id
    )


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
    ok, _msg, _reason = provision_member(
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


def test_implementer_soul_names_a_path_inside_its_own_roots(repo: Path) -> None:
    """The Codebase in the system prompt must be readable by the tools it is given."""
    member = _make_member("implementer")
    _provision(member, repo)

    roots = _roots_for(member.member_id)
    soul = (_cfg.workspace_dir(member.member_id) / "SOUL.md").read_text()
    codebase_line = soul.split("## Codebase\n", 1)[1].split("\n", 1)[0].strip()

    assert _inside(Path(codebase_line), roots), (
        f"SOUL.md tells the implementer its codebase is {codebase_line}, "
        f"but dispatch_tool will refuse every path outside {roots}"
    )


def test_implementer_startup_contract_names_a_path_inside_its_own_roots(repo: Path) -> None:
    """Same for WORKFLOW_AUTO.md, which is re-read after every context reset."""
    member = _make_member("implementer")
    _provision(member, repo)

    roots = _roots_for(member.member_id)
    contract = (_cfg.workspace_dir(member.member_id) / _mem.REQUIRED_STARTUP_FILE).read_text()

    outside = [
        p
        for p in _advertised_paths(contract)
        if not _inside(p, roots) and str(p).startswith(str(repo))
    ]
    assert not outside, f"startup contract points outside the allowed roots {roots}: {outside}"


def test_implementer_tools_md_agrees_with_soul(repo: Path) -> None:
    """TOOLS.md already used the worktree; SOUL.md must not contradict it."""
    member = _make_member("implementer")
    _provision(member, repo)

    ws = _cfg.workspace_dir(member.member_id)
    tools = (ws / "TOOLS.md").read_text()
    soul = (ws / "SOUL.md").read_text()
    project_root = tools.split("Project root:", 1)[1].split("\n", 1)[0].strip().strip("`")
    codebase_line = soul.split("## Codebase\n", 1)[1].split("\n", 1)[0].strip()

    assert codebase_line == project_root


def test_worktree_member_is_pointed_at_the_worktree_not_the_origin_repo(repo: Path) -> None:
    """Concretely: the origin checkout is *not* what the implementer is told to edit."""
    member = _make_member("implementer")
    _provision(member, repo)

    ws = _cfg.workspace_dir(member.member_id)
    raw = json.loads((ws / _cfg.META_FILE).read_text())
    worktree = raw.get("worktreeDir")
    assert worktree, "precondition: this member should have been given a worktree"

    soul = (ws / "SOUL.md").read_text()
    assert f"## Codebase\n{worktree}\n" in soul
    # meta keeps the origin repo -- that is how teardown and `docket list` find it.
    assert raw["codebase"] == str(repo)


# ── the members that must NOT change ───────────────────────────────────────────


@pytest.mark.parametrize("role", ["lead", "reviewer", "tester"])
def test_non_worktree_roles_are_still_told_the_codebase(repo: Path, role: str) -> None:
    """Only the Implementer gets a worktree; everyone else keeps the plain codebase."""
    member = _make_member(role)
    _provision(member, repo)

    ws = _cfg.workspace_dir(member.member_id)
    raw = json.loads((ws / _cfg.META_FILE).read_text())
    assert not raw.get("worktreeDir")

    soul = (ws / "SOUL.md").read_text()
    assert f"## Codebase\n{repo}\n" in soul
    contract = (ws / _mem.REQUIRED_STARTUP_FILE).read_text()
    assert f"`{repo}`" in contract
    assert _inside(Path(str(repo)), _roots_for(member.member_id))


def test_implementer_without_a_git_repo_is_unchanged(tmp_path: Path) -> None:
    """A non-repo codebase falls back to the flat workspace -- no worktree, no rewrite."""
    codebase = tmp_path / "plain"
    codebase.mkdir()
    member = _make_member("implementer", project="plainapp")
    _provision(member, codebase)

    ws = _cfg.workspace_dir(member.member_id)
    raw = json.loads((ws / _cfg.META_FILE).read_text())
    assert not raw.get("worktreeDir")
    assert f"## Codebase\n{codebase}\n" in (ws / "SOUL.md").read_text()


# ── the second writer of that path: `docket doctor`'s contract heal ────────────


def test_doctor_contract_heal_keeps_the_member_inside_its_roots(repo: Path) -> None:
    """Healing a stale contract must not restore the unreachable origin path."""
    from docket.cli._doctor import _check_runtime_contract

    member = _make_member("implementer")
    _provision(member, repo)

    ws = _cfg.workspace_dir(member.member_id)
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
