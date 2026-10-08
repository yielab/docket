"""Guard: every list/show/status/inbox leaf, and the bare reads, print parseable JSON under `--json`.

A fixture home holds one pod, one queued task and one provider document. A `list`/`show` leaf
that needs an argument gets it from `_ARGS`; a leaf the table does not know fails by name, so a
new reader cannot ship without a JSON mode. Anything printed before the document breaks the parse.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, register_local_provider, repoint_docket_home
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from docket.cli import _pod, app
from docket.core import dispatch as _dispatch
from docket.core.audit import audit_log

_runner = CliRunner()

_READ_NAMES = {"list", "show", "status", "inbox"}

# Bare group reads that take --json without a verb.
_BARE_READS: list[tuple[str, ...]] = [
    ("log",),
    ("setup",),
    ("setup", "model"),
    ("setup", "sandbox"),
]

# Positional arguments a reader needs; "{task}" is the fixture's queued task id.
_ARGS: dict[tuple[str, ...], list[str]] = {
    ("status",): [],
    ("inbox",): [],
    ("task", "list"): [],
    ("task", "show"): ["{task}"],
    ("pod", "show"): [],
    ("setup", "provider", "list"): [],
    ("setup", "provider", "show"): ["loopback"],
    ("setup", "model", "list"): [],
    ("setup", "sandbox", "status"): [],
    ("setup", "notify", "list"): [],
    ("setup", "notify", "show"): ["desktop"],
    ("setup", "export", "list"): [],
    ("setup", "export", "show"): ["langfuse"],
    ("setup", "mcp", "list"): [],
}


def _readers() -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []

    def walk(cmd: object, path: tuple[str, ...]) -> None:
        children = getattr(cmd, "commands", None)
        if children is None:
            if path and path[-1] in _READ_NAMES:
                found.append(path)
            return
        for name, sub in children.items():
            if not getattr(sub, "hidden", False):
                walk(sub, (*path, name))

    root = get_command(app)
    assert isinstance(root, TyperGroup)
    walk(root, ())
    return found


# A bare `setup` report exits 1 while a piece is unconfigured, with the JSON still printed.
_EXIT_OK: dict[tuple[str, ...], tuple[int, ...]] = {("setup",): (0, 1)}

_ALL = sorted({*_readers(), *_BARE_READS})


@pytest.fixture
def fixture_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    code = tmp_path / "code"
    code.mkdir()
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(code))
    register_local_provider(home, "loopback", [{"id": "tiny"}])
    audit_log("pod.create", "demo")
    task = _dispatch.enqueue_task("demo", "a queued task")
    monkeypatch.setenv("DOCKET_POD", "demo")
    monkeypatch.setenv("DOCKET_NO_HINTS", "1")
    monkeypatch.chdir(code)
    return str(task["id"])


def test_no_reader_is_missing_from_the_argument_table() -> None:
    missing = [" ".join(p) for p in _readers() if p not in _ARGS]
    assert not missing, f"add these list/show/status/inbox leaves to _ARGS: {missing}"


@pytest.mark.parametrize("path", _ALL, ids=[" ".join(p) for p in _ALL])
def test_the_reader_prints_one_json_document(path: tuple[str, ...], fixture_home: str) -> None:
    args = [a.replace("{task}", fixture_home) for a in _ARGS.get(path, [])]

    result = _runner.invoke(app, [*path, *args, "--json"])

    assert result.exit_code in _EXIT_OK.get(path, (0,)), (
        f"docket {' '.join(path)} --json exited {result.exit_code}"
    )
    try:
        json.loads(result.stdout)
    except ValueError as err:
        pytest.fail(f"docket {' '.join(path)} --json is not one JSON document: {err}")
