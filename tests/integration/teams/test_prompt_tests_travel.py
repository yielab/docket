"""A prompt's `tests:` file is applied, exported and locked with the prompt that names it
(pod-blueprints.spec.md, "Pod manifests: apply" and "Pod manifests: export")."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.teams import prompt_tests as _prompt_tests
from docket.teams import prompts as _prompts
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"

_PROJECT = "travelling"
_PROMPT = (
    "---\nkind: prompt\nname: implementer\nversion: 1.0.0\nlayer: hop\nfor: implementer\n"
    "output: handoff/v1\ntests: implementer.tests.yaml\n---\nYou are the Implementer.\n"
)
_TESTS = (
    "cases:\n  - name: hands off\n    input: 'done'\n    assert:\n      - calledHandoff: true\n"
)


@pytest.fixture()
def team(tmp_path: Path) -> Iterator[Path]:
    """A pod, and a blueprint whose implementer prompt names the tests file beside it."""
    hop = tmp_path / "team" / "prompts" / "hop"
    hop.mkdir(parents=True)
    (hop / "implementer.md").write_text(_PROMPT)
    (hop / "implementer.tests.yaml").write_text(_TESTS)
    with _seed_fixture_pod(tmp_path, _PROJECT):
        yield tmp_path / "team"


def _installed() -> Path:
    return current_home().pod_config_dir(_PROJECT) / "prompts" / "hop"


def test_apply_installs_the_tests_file_beside_the_prompt_and_pod_test_can_load_it(
    team: Path,
) -> None:
    _write.apply(_pod_apply.plan_apply(_PROJECT, team))

    assert (_installed() / "implementer.tests.yaml").read_text() == _TESTS
    loaded = _prompts.resolve_prompt("hop", "implementer", project=_PROJECT)
    assert loaded.tests is not None
    assert [case.name for case in _prompt_tests.load_cases(loaded.tests)] == ["hands off"]


def test_the_lock_records_the_tests_file_so_drift_sees_it(team: Path) -> None:
    _write.apply(_pod_apply.plan_apply(_PROJECT, team))

    lock = current_home().pod_config_dir(_PROJECT) / "applied.lock"
    items = {(i["kind"], i["name"]): i for i in json.loads(lock.read_text())["items"]}
    tests = items[("prompt-tests", "implementer.tests")]
    assert tests["applied"] == "prompts/hop/implementer.tests.yaml"
    assert tests["sha256"] == hashlib.sha256(_TESTS.encode()).hexdigest()


def test_export_writes_the_tests_file_back_beside_the_prompt(team: Path) -> None:
    _write.apply(_pod_apply.plan_apply(_PROJECT, team))
    out = team.parent / "export"

    _write.export_pod(_PROJECT, out)

    assert (out / "prompts" / "hop" / "implementer.md").read_text() == _PROMPT
    assert (out / "prompts" / "hop" / "implementer.tests.yaml").read_text() == _TESTS


def test_a_tests_file_that_does_not_exist_is_refused_and_nothing_is_written(
    team: Path,
) -> None:
    (team / "prompts" / "hop" / "implementer.tests.yaml").unlink()

    with pytest.raises(_model.PodApplyError, match=r"implementer\.tests\.yaml"):
        _write.apply(_pod_apply.plan_apply(_PROJECT, team))

    assert not _installed().exists()


def test_a_tests_file_that_escapes_the_prompts_directory_is_refused(team: Path) -> None:
    outside = team.parent / "outside.yaml"
    outside.write_text(_TESTS)
    tests = team / "prompts" / "hop" / "implementer.tests.yaml"
    tests.unlink()
    tests.symlink_to(outside)

    with pytest.raises(_model.PodApplyError, match="escapes"):
        _pod_apply.plan_apply(_PROJECT, team)

    assert not _installed().exists()
