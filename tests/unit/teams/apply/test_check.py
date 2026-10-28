"""``teams.apply.check``: references that must resolve and inputs that must be supplied."""

from __future__ import annotations

from pathlib import Path

from docket.teams.apply import check as _check

SUBJECT = "docket.teams.apply.check"


def _prompt(directory: Path, layer: str, inputs: str) -> None:
    path = directory / "prompts" / layer / "x.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nkind: prompt\nname: x\nversion: 1.0.0\nlayer: {layer}\nfor: reviewer\n{inputs}---\n"
        "Body\n"
    )


def test_a_member_reference_resolves_when_its_role_has_that_major() -> None:
    assert _check.unresolved_members(["vetter@2", "lead"], {"vetter": 2, "lead": 1}) == []


def test_a_member_reference_naming_another_major_or_an_unknown_role_is_named() -> None:
    problems = _check.unresolved_members(["vetter@3", "ghost@1"], {"vetter": 2})

    assert problems == [
        "vetter@3: no role vetter of major 3",
        "ghost@1: no role ghost of major 1",
    ]


def test_a_plain_name_and_a_non_list_are_the_registry_checks_business() -> None:
    assert _check.unresolved_members(["ghost"], {}) == []
    assert _check.unresolved_members("vetter@3", {}) == []


def test_a_member_reference_is_its_role_name() -> None:
    assert _check.member_names(["vetter@2", "lead", "Odd@x"]) == ["vetter", "lead", "Odd@x"]


def test_the_roles_of_a_directory_are_read_with_their_versions(tmp_path: Path) -> None:
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "vetter.yaml").write_text("kind: role\nname: vetter\nmodel: cheap\nversion: 4\n")
    (roles / "vetter.md").write_text("x\n")
    (roles / "bad.yaml").write_text("kind: role\nname: bad\nmodel: huge\n")

    assert _check.directory_role_versions(tmp_path) == {"vetter": 4}


def test_an_input_nothing_supplies_is_named_by_file_and_layer(tmp_path: Path) -> None:
    _prompt(tmp_path, "hop", "inputs:\n  ticket: string\n")

    (problem,) = _check.unsupplied_inputs(tmp_path)

    assert "x.md" in problem and "'ticket'" in problem and "hop" in problem


def test_an_identity_prompt_may_declare_the_variables_a_role_text_is_rendered_with(
    tmp_path: Path,
) -> None:
    _prompt(tmp_path, "identity", "inputs:\n  project: string\n  memberId: string\n")

    assert _check.unsupplied_inputs(tmp_path) == []
