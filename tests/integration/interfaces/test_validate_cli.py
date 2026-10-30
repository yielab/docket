"""``docket pod validate`` over directories: invalid files first, a kind-less file still loads."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.cli import invoke_pod

from docket.teams import roles as _roles

SUBJECT = "docket.interfaces.cli.commands.pod_config"

_GOOD_ROLE = "kind: role\nname: security-vetter\nscope: pod\nmodel: cheap\n"


def _put_role(roles_dir: Path, file: str, text: str, soul: str = "You vet things.") -> None:
    """Write the role document *text* as *file* with the instructions file it names beside it."""
    (roles_dir / file).write_text(text, encoding="utf-8")
    name = next(ln.split(": ")[1] for ln in text.splitlines() if ln.startswith("name: "))
    (roles_dir / f"{name}.md").write_text(f"{soul}\n", encoding="utf-8")


def _validate(path: Path) -> tuple[int, str]:
    result = invoke_pod(["validate", str(path)])
    return result.exit_code, result.output


def test_a_directory_with_one_good_role_and_one_bad_kind_file_exits_one(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "good.yaml", _GOOD_ROLE)
    (roles_dir / "bad.yaml").write_text("kind: banana\nname: whatever\n", encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "bad.yaml" in out
    assert "good.yaml" in out
    assert out.index("bad.yaml") < out.index("good.yaml")


_ROLE_WITHOUT_KIND = "name: plain-vetter\nscope: pod\nmodel: cheap\n"


def test_a_role_file_without_kind_loads_ok_from_the_roles_directory(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "plain.yaml", _ROLE_WITHOUT_KIND)

    rc, out = _validate(tmp_path)

    assert rc == 0
    assert "ok " in out
    assert "no 'kind:'" not in out


def test_a_canonical_role_file_is_refused_naming_the_short_form_key(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "old.yaml").write_text(
        "kind: role\nname: old\nmodelClass: cheap\nsoulTemplate: x\n", encoding="utf-8"
    )

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "replace `modelClass` with `model`" in out


def test_a_role_template_with_an_unknown_variable_fails_validation(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "typo.yaml", _GOOD_ROLE, soul="You vet ${typo}.")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "soulTemplate" in out


def _role_with_tools(roles_dir: Path, tools: list[str]) -> None:
    _put_role(
        roles_dir,
        "vetter.yaml",
        f"kind: role\nname: vetter\nscope: pod\nmodel: cheap\ntools: [{', '.join(tools)}]\n",
    )


def test_a_role_allow_list_with_a_typo_is_refused_naming_the_role_and_the_name(
    tmp_path: Path,
) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _role_with_tools(roles_dir, ["read", "grpe", "wirte"])

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "vetter" in out
    assert "grpe" in out
    assert "wirte" in out
    assert "grep" in out  # the known names are listed


def test_every_tool_docket_ships_is_accepted_in_a_role_allow_list(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    shipped = [*sorted(_roles.BUILTIN_TOOL_KINDS), "verify", "handoff"]
    _role_with_tools(roles_dir, shipped)

    rc, out = _validate(tmp_path)

    assert rc == 0, out


def test_an_mcp_tool_name_is_accepted_in_a_role_allow_list(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _role_with_tools(roles_dir, ["read", "mcp__docs__lookup"])

    rc, out = _validate(tmp_path)

    assert rc == 0, out


_REFUSED_PIPELINES = {
    "group-run": (
        "  - a: lead\n  - g:\n      run: echo hi\n      parallel:\n        - c: reviewer\n",
        "parallel group carries only",
    ),
    "run-and-input": (
        "  - a: lead\n  - ask:\n      run: echo hi\n      input:\n        from: a\n",
        "'input'",
    ),
    "forward-bad-max": (
        "  - a: implementer\n    verify: true\n"
        "    on:\n      fail: {goto: b, max: 0}\n  - b: tester\n",
        "'max'",
    ),
    "child-on": (
        "  - a: lead\n  - g:\n      parallel:\n"
        "        - c: reviewer\n          on:\n            pass: nowhere\n",
        "'on'",
    ),
    "child-input": (
        "  - a: lead\n  - g:\n      parallel:\n"
        "        - c:\n            input:\n              from: ghost\n",
        "'input'",
    ),
    "canonical-step": (
        "  - id: a\n    role: lead\n",
        "'- a: <role>'",
    ),
}


@pytest.mark.parametrize("name", sorted(_REFUSED_PIPELINES))
def test_pod_validate_refuses_a_pipeline_the_executor_cannot_run(tmp_path: Path, name: str) -> None:
    body, field = _REFUSED_PIPELINES[name]
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    (pipelines / "p.yaml").write_text("kind: pipeline\nname: p\nsteps:\n" + body, encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert field in out


_PROMPT = """---
kind: prompt
name: nudge
version: 1.0.0
layer: hop
for: reviewer
inputs:
  who: string
---
Hello ${who}.
"""


def test_a_prompt_using_an_undeclared_input_makes_validate_exit_one_and_name_it(
    tmp_path: Path,
) -> None:
    hop = tmp_path / "prompts" / "hop"
    hop.mkdir(parents=True)
    (hop / "good.md").write_text(_PROMPT, encoding="utf-8")
    (hop / "bad.md").write_text(_PROMPT.replace("${who}", "${nobody}"), encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "bad.md:10" in out
    assert "${nobody}" in out
    assert "good.md" in out
    assert out.index("bad.md") < out.index("good.md")


_SENDER = "kind: mcp-server\nname: mailer\ncommand: send-mail\naccess: send\n"
_READER = "kind: mcp-server\nname: mailbox\ncommand: read-mail\naccess: read\n"


def _acting_directory(tmp_path: Path, tools: str) -> Path:
    """A directory with a read server, a send server and one role whose allow-list is *tools*."""
    (tmp_path / "mcp-servers").mkdir()
    (tmp_path / "mcp-servers" / "mailer.yaml").write_text(_SENDER, encoding="utf-8")
    (tmp_path / "mcp-servers" / "mailbox.yaml").write_text(_READER, encoding="utf-8")
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(
        roles_dir,
        "actor.yaml",
        f"kind: role\nname: actor\nscope: pod\nmodel: cheap\ntools: {tools}\n",
    )
    return tmp_path


def test_a_role_naming_a_send_tool_and_fetch_is_refused_naming_the_role_and_both_tools(
    tmp_path: Path,
) -> None:
    rc, out = _validate(_acting_directory(tmp_path, "[mcp__mailer__send, fetch]"))

    assert rc == 1
    assert "actor" in out and "mcp__mailer__send" in out and "fetch" in out


def test_a_role_naming_a_send_tool_and_a_read_servers_tool_is_refused(tmp_path: Path) -> None:
    rc, out = _validate(_acting_directory(tmp_path, "[mcp__mailer__send, mcp__mailbox__list]"))

    assert rc == 1
    assert "mcp__mailbox__list" in out


def test_a_role_naming_only_a_send_tool_validates(tmp_path: Path) -> None:
    rc, _out = _validate(_acting_directory(tmp_path, "[read, mcp__mailer__send]"))

    assert rc == 0


def test_a_single_role_file_naming_a_send_and_a_read_tool_is_refused(tmp_path: Path) -> None:
    directory = _acting_directory(tmp_path, "[mcp__mailer__send, fetch]")

    rc, out = _validate(directory / "roles" / "actor.yaml")

    assert rc == 1 and "fetch" in out
