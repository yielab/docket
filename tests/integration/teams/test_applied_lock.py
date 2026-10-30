"""``docket pod update`` writes the authored files into the pod overlay and ``applied.lock``.

A role the repository, the operator and the built-ins all define resolves to the repository's
file after the update; the lock names that file with its sha256, ``configDigest`` is the lock's
hash, ``pod show`` reports drift when an applied file changes, and ``pod validate`` refuses a
reference no file satisfies. See config-format.spec.md, "Scopes, references and the lockfile".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.cli import invoke_pod
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.hops.application import compose as _compose
from docket.kernel.home import current_home
from docket.tasks.domain.task import TaskRecord
from docket.teams import pod
from docket.teams import pod_settings as _pod_settings
from docket.teams import roles as _arch
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.write"

_PROJECT = "locked"
_TASK = TaskRecord(description="ship the feature")


@pytest.fixture()
def seeded(tmp_path: Path) -> Iterator[Path]:
    with _seed_fixture_pod(tmp_path, _PROJECT):
        yield tmp_path


def _role(directory: Path, name: str, hop: str, soul: str = "SOUL ${project}") -> Path:
    """A role file and its instructions file under *directory*'s `roles/`."""
    return _role_in(directory / "roles", name, hop, soul)


def _role_in(roles: Path, name: str, hop: str, soul: str = "SOUL ${project}") -> Path:
    roles.mkdir(parents=True, exist_ok=True)
    path = roles / f"{name}.yaml"
    path.write_text(f"kind: role\nname: {name}\nmodel: cheap\nhopInstruction: {hop}\n")
    (roles / f"{name}.md").write_text(f"{soul}\n")
    return path


def _repository(tmp_path: Path) -> Path:
    return tmp_path / "repo" / ".docket"


def _apply(directory: Path) -> None:
    _write.apply(_pod_apply.plan_apply(_PROJECT, directory))


def _lock() -> dict[str, dict[str, str]]:
    path = current_home().pod_config_dir(_PROJECT) / "applied.lock"
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    return {f"{item['kind']}:{item['name']}": item for item in items}


def _lead_hop() -> str:
    message, _ = _compose._hop_message(_TASK, "lead", [], project=_PROJECT)
    return message


def _show_json() -> dict[str, object]:
    lead = pod.member_id(_PROJECT, "lead")
    shown = invoke_pod(["show", lead, "--pod", _PROJECT, "--json"])
    assert shown.exit_code == 0, shown.output
    report: dict[str, object] = json.loads(shown.stdout)
    return report


def test_the_lock_names_the_repository_file_and_the_hop_prompt_is_that_files(
    seeded: Path,
) -> None:
    """Repository, operator and built-in all name `lead`: the update makes the repository's win."""
    _role_in(current_home().roles_dir, "lead", "OPERATOR-HOP")
    assert "OPERATOR-HOP" in _lead_hop()  # the operator's file beats the built-in

    repo_role = _role(_repository(seeded), "lead", "REPOSITORY-HOP", soul="REPO-SOUL")
    _apply(_repository(seeded))

    item = _lock()["role:lead"]
    assert item["path"] == str(repo_role.resolve())
    assert item["scope"] == "repository"
    expected = hashlib.sha256(
        repo_role.read_bytes() + repo_role.with_suffix(".md").read_bytes()
    ).hexdigest()
    assert item["sha256"] == expected
    hop = _lead_hop()
    assert "REPOSITORY-HOP" in hop
    assert "OPERATOR-HOP" not in hop


def test_config_digest_is_the_sha256_of_the_lock_file(seeded: Path) -> None:
    _role(_repository(seeded), "vetter", "VET")
    _apply(_repository(seeded))
    lock_bytes = (current_home().pod_config_dir(_PROJECT) / "applied.lock").read_bytes()
    settings = _pod_settings.PodSettings.load_for(_PROJECT)
    assert settings.config_digest == hashlib.sha256(lock_bytes).hexdigest()


def test_update_ignores_a_roles_json_and_the_role_is_the_authored_file(
    seeded: Path,
) -> None:
    """A `roles.json` is nothing docket knows: an update neither reads nor removes it."""
    role_file = _role(_repository(seeded), "vetter", "VET")
    wanted = _arch.load_role_file(str(role_file))
    legacy = current_home().pod_config_dir(_PROJECT) / "roles.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"roles": {"vetter": wanted}}))
    assert _arch.load_registry(_PROJECT).get("vetter") is None  # nothing reads roles.json

    _apply(_repository(seeded))

    assert legacy.exists()
    arch = _arch.load_registry(_PROJECT).get("vetter")
    assert arch is not None
    assert arch.to_wire() == _arch.from_wire("vetter", wanted).to_wire()


def test_show_reports_drift_when_an_applied_file_changes(seeded: Path) -> None:
    _role(_repository(seeded), "vetter", "VET")
    _apply(_repository(seeded))
    assert _show_json()["drift"] == "no"

    overlay_md = current_home().pod_config_dir(_PROJECT) / "roles" / "vetter.md"
    overlay_md.write_text("EDITED IN THE OVERLAY\n")

    assert _show_json()["drift"] == "yes"


def test_show_says_nothing_of_a_roles_json(seeded: Path) -> None:
    legacy = current_home().pod_config_dir(_PROJECT) / "roles.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"roles": {}}))
    report = _show_json()
    assert "needsUpdate" not in report


def test_a_prompt_is_applied_into_the_overlay_and_the_next_hop_uses_it(seeded: Path) -> None:
    prompts = _repository(seeded) / "prompts" / "hop"
    prompts.mkdir(parents=True)
    source = prompts / "reviewer.md"
    source.write_text(
        "---\nkind: prompt\nname: reviewer\nversion: 1.1.0\nlayer: hop\nfor: reviewer\n"
        "output: handoff/v1\n---\nPOD-REVIEWER-HOP\n"
    )
    _apply(_repository(seeded))

    assert (current_home().pod_config_dir(_PROJECT) / "prompts" / "hop" / "reviewer.md").is_file()
    item = _lock()["prompt:reviewer"]
    assert item["version"] == "1.1.0"
    message, _ = _compose._hop_message(_TASK, "reviewer", [], project=_PROJECT)
    assert "POD-REVIEWER-HOP" in message


def test_validate_refuses_a_role_reference_no_file_satisfies(tmp_path: Path) -> None:
    directory = tmp_path / "team"
    _role(directory, "vetter", "VET")
    (directory / "pod.yaml").write_text("kind: pod\nname: team\nmembers: [vetter@3]\n")
    result = invoke_pod(["validate", str(directory)])
    assert result.exit_code == 1
    assert "vetter@3" in result.output

    (directory / "pod.yaml").write_text("kind: pod\nname: team\nmembers: [vetter@1]\n")
    assert invoke_pod(["validate", str(directory)]).exit_code == 0


def test_validate_refuses_a_declared_input_nothing_supplies(tmp_path: Path) -> None:
    prompts = tmp_path / "team" / "prompts" / "hop"
    prompts.mkdir(parents=True)
    (prompts / "reviewer.md").write_text(
        "---\nkind: prompt\nname: reviewer\nversion: 1.1.0\nlayer: hop\nfor: reviewer\n"
        "inputs:\n  ticket: string\n---\nReview ${ticket}.\n"
    )
    result = invoke_pod(["validate", str(tmp_path / "team")])
    assert result.exit_code == 1
    assert "ticket" in result.output
