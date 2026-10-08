"""`docket pod` helpers: answer, delegate, explain, pregrant and the roster leaves."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from tests.fakes import FakeDriver

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet

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


def _invoke(*args: str, project: str = "demo") -> tuple[int, str]:
    from typer.testing import CliRunner

    result = CliRunner().invoke(_pod.pod_app, [*args, "--pod", project])
    return result.exit_code, result.output


def _meta(member_id: str) -> dict[str, Any]:
    from docket.edges import store as _store

    return dict(_store.read_json(_pod._cfg.meta_path(member_id)))


class TestPodRemove:
    def test_the_lead_is_refused_and_the_pod_is_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("remove", "demo-lead", "--yes")

        assert code == 1
        assert "pod delete" in out
        assert set(_pod.pod_member_ids("demo")) == {"demo-lead", "demo-implementer"}

    def test_off_a_tty_without_yes_refuses_and_names_the_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("remove", "demo-implementer")

        assert code == 1
        assert "--yes" in out
        assert "demo-implementer" in _pod.pod_member_ids("demo")

    def test_yes_removes_the_member_and_its_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("remove", "demo-implementer", "--yes")

        assert code == 0
        assert _pod.pod_member_ids("demo") == ["demo-lead"]
        assert not (home / "workspaces" / "projects" / "demo-implementer").exists()

    def test_a_name_outside_the_pod_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("remove", "other-implementer", "--yes")

        assert code == 1
        assert len(_pod.pod_member_ids("demo")) == 2


class TestPodDelete:
    def test_off_a_tty_without_confirm_refuses_and_names_the_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("delete")

        assert code == 1
        assert "--confirm demo" in out
        assert len(_pod.pod_member_ids("demo")) == 2

    def test_a_wrong_confirm_name_deletes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("delete", "--confirm", "nope")

        assert code == 1
        assert len(_pod.pod_member_ids("demo")) == 2

    def test_a_member_id_is_refused_as_a_pod(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("delete", "--confirm", "demo-lead", project="demo-lead")

        assert code == 1
        assert "member id" in out
        assert len(_pod.pod_member_ids("demo")) == 2

    def test_confirm_with_the_name_removes_every_member_and_audits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import audit as _audit

        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("delete", "--confirm", "demo")

        assert code == 0
        assert _pod.pod_member_ids("demo") == []
        assert [e["action"] for e in _audit.read_audit()].count("pod.delete") == 1


class TestPodAdd:
    def test_an_unknown_role_is_one_line_and_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("add", "wizard")

        assert code == 1
        assert "unknown pod role" in out
        assert "Traceback" not in out
        assert len(_pod.pod_member_ids("demo")) == 2

    def test_a_second_lead_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("add", "lead")

        assert code == 1

    def test_count_and_verify_add_indexed_implementers_with_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("add", "implementer", "--count", "2", "--verify", "make check")

        assert code == 0, out
        assert _meta("demo-implementer-2")["verifyCmd"] == "make check"
        assert _meta("demo-implementer-3")["verifyCmd"] == "make check"


class TestPodSetUnset:
    def test_unset_verify_removes_the_key_from_the_members_meta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _invoke("set", "verify", "make check", "--member", "demo-implementer")[0] == 0
        assert _meta("demo-implementer")["verifyCmd"] == "make check"

        code, _out = _invoke("unset", "verify", "--member", "demo-implementer")

        assert code == 0
        assert "verifyCmd" not in _meta("demo-implementer")

    def test_verify_with_no_member_names_the_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, out = _invoke("set", "verify", "make check")

        assert code == 1
        assert "--member" in out

    def test_member_flag_on_another_key_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("set", "budgetUsd", "5", "--member", "demo-implementer")

        assert code == 1
        assert "budgetUsd" not in _meta("demo-lead")

    def test_a_flag_the_leaf_does_not_declare_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        code, _out = _invoke("set", "budgetUsd", "5", "--clear")

        assert code == 2

    def test_set_and_unset_cover_every_pod_settings_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        assert _invoke("set", "maxReworkCycles", "3")[0] == 0
        assert _meta("demo-lead")["maxReworkCycles"] == 3
        assert _invoke("unset", "maxReworkCycles")[0] == 0
        assert "maxReworkCycles" not in _meta("demo-lead") or (
            _meta("demo-lead")["maxReworkCycles"] is None
        )
        assert _invoke("unset", "nonsense")[0] == 1
