"""A team kept in the repository rebuilds in a fresh docket home and runs there.

One home exports its pod into the repository's ``.docket/``; a second home, with nothing in it,
clones that repository, reviews and accepts what it brings, and runs a task. The product runs
for real as ``python -m docket`` subprocesses; only the model is faked.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, say, write_file

PIPELINE = """name: kept-in-the-repo
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 1
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

TURN_TIMEOUT = "120"


def _masked(text: str, *worlds: World) -> str:
    for w in worlds:
        text = text.replace(str(w.root), "<world>")
    return text


def _block(shown: str, start: str, end: str) -> str:
    """The lines of ``pod show`` from the heading *start* up to the heading *end*."""
    lines = shown.splitlines()
    return "\n".join(lines[lines.index(start) : lines.index(end)])


def _keep_the_team_in_the_repo(w: World) -> None:
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "turnTimeoutS", TURN_TIMEOUT)
    w.docket("pod", "set", "pipeline", str(w.pipeline))
    w.docket("pod", "export")
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "keep the team in the repository")


def _a_fresh_home_on_a_clone(source: World, model: FakeModel, root: Path) -> World:
    fresh = World(root, model)
    shutil.rmtree(fresh.repo)
    subprocess.run(
        ["git", "clone", "-q", str(source.repo), str(fresh.repo)], check=True, env=fresh.env
    )
    return fresh


def test_a_team_exported_to_the_repo_rebuilds_in_a_fresh_home_and_runs(
    world: Callable[..., World], fake_model: Callable[..., FakeModel], tmp_path: Path
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [write_file("app.txt", "fixed\n"), say("app.txt says fixed.")],
            "reviewer": [say("APPROVE")],
        }
    )
    kept = world(model)
    _keep_the_team_in_the_repo(kept)
    fresh = _a_fresh_home_on_a_clone(kept, model, tmp_path / "fresh")
    assert fresh.home != kept.home and not (fresh.home / "fleet.json").exists()

    refused = fresh.docket("init", "e2e", "--json", check=False)
    review = refused.json()
    assert refused.code != 0 and review["status"] == "needs_review", refused.describe()
    assert review["items"] == [
        {"kind": "verify", "name": "implement", "runs": "sh checks/verify.sh"}
    ]
    assert fresh.docket("pod", "show", check=False).code != 0

    fresh.docket("init", "e2e", "--accept", review["reviewCode"])
    fresh.docket("setup", "sandbox", "off")
    plan_kept = _masked(kept.docket("pod", "plan").out, kept)
    plan_fresh = _masked(fresh.docket("pod", "plan").out, fresh)
    assert "Source: bound pipeline" in plan_fresh and plan_fresh == plan_kept
    shown_kept = kept.docket("pod", "show").out
    shown_fresh = fresh.docket("pod", "show").out
    settings_fresh = _block(shown_fresh, "Settings", "Dispatch")
    assert _block(shown_kept, "Members", "Settings") == _block(shown_fresh, "Members", "Settings")
    assert settings_fresh == _block(shown_kept, "Settings", "Dispatch")
    assert f"turnTimeoutS             {TURN_TIMEOUT}" in settings_fresh

    head_before = fresh.head()
    task_id = fresh.add_task("Make app.txt say fixed")
    fresh.docket("run", "--timeout", "30")

    assert oracles.trace_skeleton(fresh, fresh.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "approve"),
        ("session_end", "lead", "done"),
    ]
    assert fresh.task(task_id)["task"]["status"] == "done"
    assert "+fixed" in fresh.docket("task", "diff", task_id).out
    assert not (kept.home / "workspaces" / "projects" / "e2e-implementer" / "tasks").exists()
    oracles.assert_checkout_untouched(fresh, head_before)
    oracles.assert_sentinel_untouched(fresh)
    oracles.assert_audit_covers_tool_calls(fresh, fresh.pod, task_id)
    oracles.assert_transitions_legal(["pending", "done"])
    oracles.assert_log_verifies(fresh)
