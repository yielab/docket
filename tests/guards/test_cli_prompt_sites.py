"""Guard: only `cli/_contract.py` and the listed TTY-checked flows may prompt; confirmations refuse off a TTY.

Layer one is an AST count of direct `input(`/`getpass(` calls per module, so a new prompt site
fails until it is listed here on purpose. Layer two runs every confirming verb with stdin closed
and without `--yes`/`--confirm`: each must exit 1 and name the flag.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, register_local_provider, repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _pod, app
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"

# module -> number of direct prompt calls. _contract.py is the shared confirmation; the rest are
# flows that check for a TTY themselves (first-run setup, enable flows, credential entry, answers).
_PROMPT_SITES: dict[str, int] = {
    "cli/_contract.py": 2,
    "cli/_setup.py": 5,
    "cli/_setup_notify.py": 4,
    "cli/_setup_model.py": 1,
    "cli/_setup_export.py": 1,
    "cli/_agents.py": 1,
    "cli/_task.py": 2,
}


def _prompt_calls(path: Path) -> int:
    count = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in ("input", "getpass"):
            count += 1
    return count


def test_only_the_listed_modules_prompt_directly() -> None:
    found = {
        str(p.relative_to(SRC)): n for p in sorted(SRC.rglob("*.py")) if (n := _prompt_calls(p))
    }
    assert found == _PROMPT_SITES


_runner = CliRunner()

# (argv, flag the refusal must name)
_CONFIRMING: list[tuple[list[str], str]] = [
    (["pod", "remove", "demo-implementer"], "--yes"),
    (["pod", "reset", "demo-implementer"], "--yes"),
    (["pod", "delete"], "--confirm"),
    (["task", "prune", "--force"], "--yes"),
    (["setup", "provider", "remove", "loopback"], "--yes"),
    (["setup", "model", "reset"], "--yes"),
    (["setup", "notify", "remove", "mine"], "--yes"),
    (["setup", "notify", "unbind", "demo-lead"], "--yes"),
    (["setup", "export", "remove", "mine"], "--yes"),
]


def _seed_documents(tmp_path: Path) -> None:
    """One operator channel and one exporter document, so `remove` has something to confirm."""
    channel = tmp_path / "mine-channel.yaml"
    channel.write_text(
        "kind: channel\nname: mine\ndialect: webhook\ncapabilities: [notify]\n"
        "on: [needs_you]\ncontent: minimal\nconfig: {url: ''}\nenabled: false\n"
    )
    exporter = tmp_path / "mine-exporter.yaml"
    exporter.write_text(
        "kind: exporter\nname: mine\ndialect: otlp-http\nendpoint: http://127.0.0.1:4318/v1/traces\n"
        "auth: {type: none}\nprivacy: minimal\nenabled: false\n"
    )
    for argv in (
        ["setup", "notify", "add", str(channel)],
        ["setup", "export", "add", str(exporter), "--no-verify", "--yes"],
    ):
        added = _runner.invoke(app, argv)
        assert added.exit_code == 0, added.output


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".docket"
    (root / "workspaces" / "projects").mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, root)
    record_isolation_off(root)
    code = tmp_path / "code"
    code.mkdir()
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(code))
    register_local_provider(root, "loopback", [{"id": "tiny"}])
    _dispatch.enqueue_task("demo", "a queued task")
    _fleet.upsert_binding("demo-lead", "-1001")
    _mp.write_registry({"lead": "loopback/tiny"})
    _seed_documents(tmp_path)
    monkeypatch.setenv("DOCKET_POD", "demo")
    monkeypatch.setenv("DOCKET_NO_HINTS", "1")
    monkeypatch.chdir(code)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    return root


@pytest.mark.parametrize(
    "argv,flag", _CONFIRMING, ids=lambda v: " ".join(v) if isinstance(v, list) else v
)
def test_a_confirming_verb_refuses_off_a_tty_and_names_its_flag(
    argv: list[str], flag: str, home: Path
) -> None:
    result = _runner.invoke(app, argv, input="")

    assert result.exit_code == 1, result.output
    assert flag in result.output + result.stderr
