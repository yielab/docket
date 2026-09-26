"""``docket pod <project> config`` — typed, validated pod dispatch settings.

Closes the gap where `maxReworkCycles`/`turnTimeoutS`/`verifyTimeoutS` were writable only by
hand-editing `.docket-meta.json` or the internal `_json meta-set` debug path, and an invalid
stored value silently fell back to its default instead of refusing dispatch. See
pod-dispatch.spec.md ("Timeout configuration", "Budget gate and auto-pause", "Reviewer verdict
gate and bounded rework") and cli-json-shapes.spec.md ("`docket pod <p> config get --json`").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import pod

SUBJECT = "docket.cli._pod"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "proj") -> None:
    _seed(tmp_path, monkeypatch)
    _pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


def _lead_meta(project: str) -> dict[str, object]:
    path = _cfg.meta_path(f"{project}-lead")
    return dict(json.loads(path.read_text()))


class TestConfigGet:
    def test_defaults_when_nothing_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        capsys.readouterr()
        _pod.dispatch("proj", "config", ["get", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["maxReworkCycles"] == {"value": 1, "source": "default"}
        assert data["budgetUsd"] == {"value": 0.0, "source": "default"}

    def test_invalid_stored_value_refuses_instead_of_showing_a_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        meta = _lead_meta("proj")
        meta["turnTimeoutS"] = "not-a-number"
        _cfg.meta_path("proj-lead").write_text(json.dumps(meta))

        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["get"])
        assert exc.value.exit_code == 1
        assert "turnTimeoutS" in capsys.readouterr().err


class TestConfigSet:
    def test_set_persists_a_validated_value_and_dispatch_reads_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        _pod.dispatch("proj", "config", ["set", "maxReworkCycles", "2"])
        assert _dispatch.pod_max_rework_cycles("proj") == 2
        capsys.readouterr()

    def test_set_approval_mode_refuse_persists_and_dispatch_reads_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        assert _dispatch.pod_approval_mode("proj") == "wait"
        _pod.dispatch("proj", "config", ["set", "approvalMode", "refuse"])
        assert _dispatch.pod_approval_mode("proj") == "refuse"
        capsys.readouterr()

    def test_set_invalid_value_exits_1_and_leaves_meta_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        before = _lead_meta("proj")

        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["set", "turnTimeoutS", "abc"])
        assert exc.value.exit_code == 1
        assert "turnTimeoutS" in capsys.readouterr().err
        assert _lead_meta("proj") == before

    def test_set_unknown_key_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["set", "definitelyNotARealSetting", "x"])
        assert exc.value.exit_code == 1

    def test_set_invalid_approval_mode_exits_1_and_leaves_meta_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        before = _lead_meta("proj")

        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["set", "approvalMode", "x"])
        assert exc.value.exit_code == 1
        assert "approvalMode" in capsys.readouterr().err
        assert _lead_meta("proj") == before


class TestConfigUnset:
    def test_unset_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        _pod.dispatch("proj", "config", ["set", "maxReworkCycles", "3"])
        capsys.readouterr()
        _pod.dispatch("proj", "config", ["unset", "maxReworkCycles"])
        capsys.readouterr()
        assert _dispatch.pod_max_rework_cycles("proj") == 1
