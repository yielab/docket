"""Shared cli helpers and fixtures for the docket suite."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from docket.agent.ports import ToolCall
from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import setup_model_credentials as _setup_model_credentials
from docket.kernel.home import Home, use_home

_runner = CliRunner()


def run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


def pod_cli(*args: str) -> Any:
    return CliRunner().invoke(_pod.pod_app, list(args))


def run_2(args: list[str], oc_dir: Path) -> tuple[int, str, str]:
    """Invoke the CLI in-process against *oc_dir* as an isolated DOCKET_HOME."""
    with use_home(Home(oc_dir)):
        result = _runner.invoke(_app, args)
    return result.exit_code, result.stdout, result.stderr


def call(name: str, arguments: str = "{}", call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def add(name: str, value: str) -> bool:
    return _setup_model_credentials._write_credential(name, value, "add")


def reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from docket.models.adapters import openai_http as _llm

    monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=200))
