"""`docket pod` helpers: answer, delegate, explain and pregrant."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import typer
from tests.conftest import record_isolation_off, repoint_docket_home
from tests.fakes import FakeDriver

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions

SUBJECT = "docket.cli._pod"

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
"""


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _bind_ask_pipeline(project: str) -> None:
    digest = hashlib.sha256(_ASK_PIPELINE_YAML.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ASK_PIPELINE_YAML, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def _seed_parked_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    _seed_pod(tmp_path, monkeypatch)
    _bind_ask_pipeline("demo")
    _dispatch.enqueue_task("demo", "needs a decision")
    _dispatch.dispatch_pod("demo", runner=FakeDriver())
    return _dispatch.read_tasks("demo")[0]


def _give_options(project: str, task_id: str) -> None:
    """Turn the parked task's question into a v1.1 one with options, as a Lead consult writes."""
    from docket.edges import store as _store

    path = _dispatch.pod_task_list_path(project)
    doc = _store.read_json(path)
    for task in doc["tasks"]:
        if task["id"] == task_id:
            task["question"].update(
                {
                    "kind": "clarification",
                    "options": [
                        {"id": "opt1", "label": "Root", "description": "At the root."},
                        {"id": "opt2", "label": "Search", "description": "Search for it."},
                    ],
                    "recommendation": {"optionId": "opt2", "rationale": "safer"},
                }
            )
    _store.write_json(path, doc)


class TestPodDelegateBrief:
    def test_an_invalid_brief_exits_nonzero_and_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps({"acceptance": ["missing objective"]}))

        with pytest.raises(typer.Exit):
            _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        assert _dispatch.read_tasks("demo") == []

    def test_malformed_json_exits_nonzero_and_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text("not json")

        with pytest.raises(typer.Exit):
            _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        assert _dispatch.read_tasks("demo") == []

    def test_a_valid_brief_is_enqueued_and_stored_on_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--brief` passes the validated document through to the task."""
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps({"objective": "fix the flaky test"}))

        _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["brief"]["objective"] == "fix the flaky test"

    def test_delegate_without_brief_is_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        _pod._pod_delegate("demo", ["fix", "it"])

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["description"] == "fix it"


class TestDelegateInterruptionSummary:
    """`delegate`'s own one-line forecast, printed after queuing (ADR 0016 SS10)."""

    def test_a_clean_pod_says_nothing_will_ask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        capsys.readouterr()

        _pod._pod_delegate("demo", ["fix", "it"])

        assert _interruptions.NOTHING_WILL_ASK in capsys.readouterr().out

    def test_a_role_gate_is_named_in_the_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_delegate("demo", ["fix", "it"])

        out = capsys.readouterr().out
        assert "May ask you:" in out
        assert "explain interruptions" in out


class TestPodExplain:
    """``docket pod <p> explain interruptions [--json]`` (ADR 0016 SS10)."""

    def test_no_pod_is_an_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        record_isolation_off(tmp_path / ".docket")
        with pytest.raises(typer.Exit):
            _pod._pod_explain("nope", ["interruptions"])

    def test_missing_topic_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod._pod_explain("demo", [])

    def test_a_clean_pod_prints_nothing_will_ask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions"])

        assert _interruptions.NOTHING_WILL_ASK in capsys.readouterr().out

    def test_a_role_gate_is_listed_with_the_park_posture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions"])

        out = capsys.readouterr().out
        assert "requireApprovalRoles" in out
        assert "approvalMode resolves to" in out

    def test_json_output_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions", "--json"])

        body = json.loads(capsys.readouterr().out)
        assert body["pod"] == "demo"
        kinds = {item["kind"] for item in body["interruptions"]}
        assert "role_gate" in kinds
        assert "mode" in kinds
