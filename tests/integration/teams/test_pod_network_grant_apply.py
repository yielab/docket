"""A repository's ``.docket/`` can never widen a pod's network: ``networkGrant`` is skipped.

Only the operator's ``docket pod set network open --widen`` writes the grant
(security-gates.spec.md item 7, "The pod grant"); ``pod update`` and ``POST /pods/<p>/apply``
share ``teams.apply.plan``, so planning and applying a directory that carries the key is the
oracle for both.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import pod, pod_settings
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import review as _review
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"

_GRANT = '{"at": "2026-10-30T00:00:00+00:00", "by": "repository"}'


def _repo_config(tmp_path: Path) -> Path:
    directory = tmp_path / "repo-docket"
    directory.mkdir()
    (directory / "pod.yaml").write_text(
        "kind: pod\nname: x\nsettings:\n"
        "  network: open\n"
        f"  networkGrant: '{_GRANT}'\n"
        "  maxReworkCycles: 2\n",
        encoding="utf-8",
    )
    return directory


def test_apply_leaves_no_grant_and_reports_the_key_skipped(tmp_path: Path) -> None:
    project = "granted"
    with _seed_fixture_pod(tmp_path, project):
        _fleet.set_network_mode("none")
        plan = _pod_apply.plan_apply(project, _repo_config(tmp_path))
        skipped = [i for i in plan.items if i.name == "networkGrant"]
        assert [(i.kind, i.action) for i in skipped] == [("setting", "skip")]
        assert "docket pod set network open --widen" in skipped[0].note

        _write.apply(plan)

        meta = json.loads(current_home().meta_path(pod.member_id(project, "lead")).read_text())
        assert "networkGrant" not in meta
        assert meta["maxReworkCycles"] == 2  # the rest of the directory still applies
        assert pod_settings.effective_network(project) == ("none", "global")


def test_apply_does_not_disturb_a_grant_the_operator_recorded(tmp_path: Path) -> None:
    project = "kept"
    with _seed_fixture_pod(tmp_path, project):
        _fleet.set_network_mode("none")
        pod_settings.grant_network(project, by="cli")
        _write.apply(_pod_apply.plan_apply(project, _repo_config(tmp_path)))
        assert pod_settings.effective_network(project) == ("open", "pod-grant")
        grant = json.loads(current_home().meta_path(pod.member_id(project, "lead")).read_text())[
            "networkGrant"
        ]
        assert grant["by"] == "cli"


def test_the_review_never_lists_the_grant_as_something_to_accept(tmp_path: Path) -> None:
    review = _review.classify_directory(_repo_config(tmp_path))
    assert [r.kind for r in review.runs] == ["network"]
    assert all(name != "networkGrant" for _kind, name in review.adds)
