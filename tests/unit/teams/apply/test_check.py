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


_KINDS = {"mail": "send", "inbox": "read", "notes": "write"}


def test_a_role_naming_a_send_tool_and_fetch_is_named_with_both_tools() -> None:
    roles = {"actor": (("mcp__mail__send", "fetch"), ())}

    (problem,) = _check.send_conflicts(roles, _KINDS, {})

    assert "actor" in problem and "mcp__mail__send" in problem and "fetch" in problem
    assert "send" in problem and "read" in problem


def test_a_role_naming_a_send_tool_and_a_read_servers_tool_or_the_server_is_named() -> None:
    roles = {
        "one": (("mcp__mail__send", "mcp__inbox__list"), ()),
        "two": (("mcp__mail", "mcp__inbox"), ()),
    }

    problems = _check.send_conflicts(roles, _KINDS, {})

    assert len(problems) == 2
    assert "mcp__inbox__list" in problems[0] and "mcp__inbox" in problems[1]


def test_a_send_tool_beside_write_tools_and_unknown_servers_is_accepted() -> None:
    roles = {
        "actor": (("mcp__mail__send", "write", "mcp__notes__save", "mcp__ghost__x", "grep"), ())
    }

    assert _check.send_conflicts(roles, _KINDS, {}) == []


def test_a_read_only_role_and_a_send_only_role_are_accepted() -> None:
    roles = {
        "reader": (("fetch", "mcp__inbox__list"), ()),
        "actor": (("mcp__mail__send",), ()),
    }

    assert _check.send_conflicts(roles, _KINDS, {}) == []


def test_a_role_that_denies_fetch_does_not_hold_it() -> None:
    roles = {"actor": (("mcp__mail__send", "fetch"), ("fetch",))}

    assert _check.send_conflicts(roles, _KINDS, {}) == []


def test_steps_that_all_narrow_the_role_satisfy_the_rule() -> None:
    roles = {"actor": (("mcp__mail__send", "fetch"), ())}
    steps = {"actor": [("mcp__mail__send",), ("fetch",)]}

    assert _check.send_conflicts(roles, _KINDS, steps) == []


def test_one_step_that_does_not_narrow_the_role_leaves_the_conflict() -> None:
    roles = {"actor": (("mcp__mail__send", "fetch"), ())}
    steps = {"actor": [("mcp__mail__send",), None]}

    assert len(_check.send_conflicts(roles, _KINDS, steps)) == 1


def test_a_step_that_narrows_to_both_still_conflicts() -> None:
    roles = {"actor": (("mcp__mail__send", "fetch", "grep"), ())}
    steps = {"actor": [("mcp__mail__send", "fetch")]}

    (problem,) = _check.send_conflicts(roles, _KINDS, steps)

    assert "step" in problem


_SERVICE_KINDS = {
    **_KINDS,
    "svc__crm__get_contact": "read",
    "svc__crm__create_contact": "send",
    "svc__billing__get_invoice": "read",
}


def test_a_role_naming_a_send_operation_and_a_read_operation_is_named_with_both() -> None:
    roles = {"actor": (("svc__crm__create_contact", "svc__crm__get_contact"), ())}

    (problem,) = _check.send_conflicts(roles, _SERVICE_KINDS, {})

    assert "svc__crm__create_contact" in problem and "svc__crm__get_contact" in problem


def test_a_service_named_whole_counts_as_every_operation_of_it() -> None:
    roles = {
        "both": (("svc__crm",), ()),
        "split": (("svc__crm__create_contact", "svc__billing"), ()),
    }

    problems = _check.send_conflicts(roles, _SERVICE_KINDS, {})

    assert len(problems) == 2
    assert "role 'both'" in problems[0] and "role 'split'" in problems[1]


def test_a_send_operation_beside_a_read_operation_of_another_unknown_service_is_accepted() -> None:
    roles = {"actor": (("svc__crm__create_contact", "svc__ghost__x", "write"), ())}

    assert _check.send_conflicts(roles, _SERVICE_KINDS, {}) == []


def test_a_role_denying_read_does_not_hold_a_read_operation() -> None:
    roles = {"actor": (("svc__crm__create_contact", "svc__crm__get_contact"), ("read",))}

    assert _check.send_conflicts(roles, _SERVICE_KINDS, {}) == []


def test_the_operations_a_directory_declares_are_read_from_its_services(tmp_path: Path) -> None:
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "crm.yaml").write_text(
        "kind: service\nname: crm\nbaseUrl: https://api.example.com\noperations:\n"
        "  - {name: get_contact, method: GET, path: /c}\n"
        "  - {name: create_contact, method: POST, path: /c}\n"
    )
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "actor.yaml").write_text(
        "kind: role\nname: actor\nmodel: cheap\ntools: [svc__crm]\n"
    )
    (tmp_path / "roles" / "actor.md").write_text("x\n")

    (problem,) = _check.directory_send_problems(tmp_path, "acme")

    assert "actor" in problem and "svc__crm" in problem
