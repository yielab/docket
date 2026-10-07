"""Pod targeting (``cli/_target.py``): flag, then DOCKET_POD, then the deepest codebase
containing the working directory."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import app
from docket.cli._target import TargetError, resolve_pod
from docket.edges import store

SUBJECT = "docket.cli._target"


def _register(pod: str, root: Path) -> None:
    aid = f"{pod}-lead"
    root.mkdir(parents=True, exist_ok=True)
    meta = _cfg.meta_path(aid)
    meta.parent.mkdir(parents=True, exist_ok=True)
    store.write_json(meta, {"pod": pod, "codebase": str(root)})


@pytest.fixture
def pods(tmp_path: Path) -> Path:
    base = tmp_path / "x"
    _register("a", base)
    _register("b", base / "sub")
    (base / "sub" / "deep").mkdir()
    return base


def test_deeper_codebase_wins(pods: Path) -> None:
    assert resolve_pod(None, env={}, cwd=pods / "sub" / "deep") == "b"
    assert resolve_pod(None, env={}, cwd=pods) == "a"


def test_env_beats_directory(pods: Path) -> None:
    assert resolve_pod(None, env={"DOCKET_POD": "a"}, cwd=pods / "sub") == "a"


def test_flag_beats_env_and_directory(pods: Path, tmp_path: Path) -> None:
    assert resolve_pod("b", env={"DOCKET_POD": "a"}, cwd=tmp_path) == "b"


def test_no_match_names_lookup_flag_and_fix(pods: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(TargetError) as exc:
        resolve_pod(None, env={}, cwd=outside)
    assert str(exc.value) == (
        f"No pod for {outside} (looked for a registered codebase containing it). "
        "Run 'docket init' here, or pass --pod <name>."
    )


def test_same_depth_names_both(tmp_path: Path) -> None:
    root = tmp_path / "r"
    _register("p1", root)
    _register("p2", root)
    with pytest.raises(TargetError) as exc:
        resolve_pod(None, env={}, cwd=root)
    assert "p1" in str(exc.value) and "p2" in str(exc.value)


def test_status_outside_any_pod_exits_1(
    pods: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("DOCKET_POD", raising=False)
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 1
    assert "No pod for" in result.output.replace("\n", " ")
