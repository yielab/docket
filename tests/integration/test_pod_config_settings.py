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
            _pod.dispatch("proj", "config", ["set", "approvalMode", "x"])
        assert exc.value.exit_code == 1


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


_CUSTOM_PIPELINE = (
    "name: custom-bound\n"
    "steps:\n"
    "  - id: kickoff\n"
    "    role: lead\n"
    "  - id: assemble\n"
    "    role: implementer\n"
)


class TestConfigSetPipeline:
    """``pod config set/unset pipeline`` -- the CLI's validate-plan-store contract.
    See ``test_dispatch.py::TestBoundPipeline`` for the resolution/refusal behavior."""

    def test_set_validates_plans_and_binds_a_valid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        pipeline_file = tmp_path / "custom.yaml"
        pipeline_file.write_text(_CUSTOM_PIPELINE)

        _pod.dispatch("proj", "config", ["set", "pipeline", str(pipeline_file)])
        capsys.readouterr()

        digest = _lead_meta("proj")["pipeline"]
        assert isinstance(digest, str) and len(digest) == 64
        stored = pod.bound_pipeline_path("proj")
        assert stored.read_text() == _CUSTOM_PIPELINE
        spec = _dispatch.effective_pipeline("proj", None)
        assert [step.id for step in spec.steps] == ["kickoff", "assemble"]

    def test_set_refuses_when_a_step_targets_a_role_the_pod_lacks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)  # lead + implementer only, no reviewer
        pipeline_file = tmp_path / "needs-reviewer.yaml"
        pipeline_file.write_text("name: x\nsteps:\n  - id: r\n    role: reviewer\n")
        before = _lead_meta("proj")

        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["set", "pipeline", str(pipeline_file)])
        assert exc.value.exit_code == 1
        assert "reviewer" in capsys.readouterr().err
        assert _lead_meta("proj") == before
        assert not pod.bound_pipeline_path("proj").exists()

    def test_set_refuses_on_an_invalid_pipeline_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        pipeline_file = tmp_path / "broken.yaml"
        pipeline_file.write_text("not: a valid\npipeline: [shape\n")

        with pytest.raises(typer.Exit) as exc:
            _pod.dispatch("proj", "config", ["set", "pipeline", str(pipeline_file)])
        assert exc.value.exit_code == 1
        capsys.readouterr()

    def test_unset_removes_the_stored_copy_and_restores_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _build(tmp_path, monkeypatch)
        pipeline_file = tmp_path / "custom.yaml"
        pipeline_file.write_text(_CUSTOM_PIPELINE)
        _pod.dispatch("proj", "config", ["set", "pipeline", str(pipeline_file)])
        capsys.readouterr()

        _pod.dispatch("proj", "config", ["unset", "pipeline"])
        capsys.readouterr()

        assert not pod.bound_pipeline_path("proj").exists()
        spec = _dispatch.effective_pipeline("proj", None)
        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]
