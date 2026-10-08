"""Drift guard: shell completions must advertise exactly the live Typer command tree.

`_setup_shell.py` renders both scripts by walking the Typer `app` registry. These tests
re-derive the truth from the registry on their own (not through `_setup_shell`'s helpers),
so any drift between the CLI surface and the emitted scripts fails the suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from docket.cli import _setup_shell

REPO_ROOT = Path(__file__).resolve().parents[2]

_ARM = re.compile(r'^\s*"([^"]*)"\) echo "([^"]*)" ;;$', re.MULTILINE)


def _registry() -> dict[str, tuple[list[str], list[str], bool]]:
    """path -> (visible verbs, long options, is a task verb taking a ref), from the registry."""
    from typer.core import TyperGroup
    from typer.main import get_command

    from docket.cli import app

    out: dict[str, tuple[list[str], list[str], bool]] = {}

    def walk(cmd: object, path: str) -> None:
        children = getattr(cmd, "commands", None)
        opts = sorted(
            {o for p in getattr(cmd, "params", []) for o in p.opts if o.startswith("--")}
            | {"--help"}
        )
        has_ref = any(getattr(p, "name", "") == "ref" for p in getattr(cmd, "params", []))
        verbs = [n for n, c in (children or {}).items() if not getattr(c, "hidden", False)]
        out[path] = (verbs, opts, children is None and path.startswith("task ") and has_ref)
        for name in verbs:
            walk(children[name], f"{path} {name}".strip())

    root = get_command(app)
    assert isinstance(root, TyperGroup)
    walk(root, "")
    return out


def _function_arms(script: str, name: str) -> dict[str, str]:
    body = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", script, re.DOTALL | re.MULTILINE)
    assert body, f"script is missing the {name}() function"
    return dict(_ARM.findall(body.group(1)))


def _scripts() -> dict[str, str]:
    return {"bash": _setup_shell.render_bash(), "zsh": _setup_shell.render_zsh()}


@pytest.mark.parametrize("shell", ["bash", "zsh"])
class TestCompletionsMatchRegistry:
    def test_every_group_advertises_exactly_its_live_verbs(self, shell: str) -> None:
        arms = _function_arms(_scripts()[shell], "_docket_verbs")
        expected = {path: " ".join(v) for path, (v, _o, _t) in _registry().items() if v}
        assert arms == expected

    def test_every_command_advertises_its_long_options(self, shell: str) -> None:
        arms = _function_arms(_scripts()[shell], "_docket_options")
        for path, (_verbs, opts, _t) in _registry().items():
            if path == "":
                opts = ["--help", "--version"]
            assert sorted(arms[path].split()) == sorted(opts), path

    def test_the_task_verbs_that_take_a_ref_complete_task_ids(self, shell: str) -> None:
        script = _scripts()[shell]
        arm = re.search(
            r"_docket_takes_task_id\(\) \{\n  case .*?\n    (.*?)\) echo yes", script, re.DOTALL
        )
        assert arm
        listed = set(re.findall(r'"([^"]+)"', arm.group(1)))
        expected = {p for p, (_v, _o, takes) in _registry().items() if takes}
        assert expected >= {"task show", "task approve", "task deny"}
        assert listed == expected

    def test_pods_come_from_lead_workspaces_and_ids_from_task_lists(self, shell: str) -> None:
        script = _scripts()[shell]
        assert "workspaces/projects/*-lead/" in script
        assert "TASK_LIST.json" in script
        assert "$_ids" not in script
