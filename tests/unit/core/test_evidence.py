"""evidence-v1: the model, the one builder, and the schema artifact."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import evidence as _ev
from docket.core import trace as _trace
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.core.evidence"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod("demo", ("lead", "implementer", "reviewer"), codebase="/src/demo")
    return home


class _Backend:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        return ChatResponse(
            ok=True,
            message=assistant(self._texts.pop(0)),
            finish_reason="stop",
            usage=TokenUsage(7, 3),
        )


def _run_three_hops(monkeypatch: pytest.MonkeyPatch) -> str:
    backend = _Backend(["lead plan", "implementer done", "fine\nAPPROVE"])
    driver = DocketDriver(backend_factory=lambda model: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    task = _dispatch.enqueue_task("demo", "evidence please", channel="cli")
    results = _dispatch.dispatch_pod("demo")
    assert results[0].status == "done"
    return str(task["id"])


def _seed_task(task_id: str, hops: list[dict[str, Any]]) -> None:
    path = _dispatch.pod_task_list_path("demo")
    raw = json.loads(path.read_text())
    for t in raw["tasks"]:
        if t["id"] == task_id:
            t["hops"] = hops
    path.write_text(json.dumps(raw))


class TestTaskEvidence:
    def test_three_hops_each_with_measured_usage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task_id = _run_three_hops(monkeypatch)
        ev = _ev.task_evidence("demo", task_id, "1.1.0")
        assert ev.v == _ev.EVIDENCE_V1_1 == "1.1.0"
        assert (ev.pod, ev.task_id, ev.status) == ("demo", task_id, "done")
        assert [h.role for h in ev.hops] == ["lead", "implementer", "reviewer"]
        for hop in ev.hops:
            assert hop.usage is not None
            assert hop.usage.input == 7 and hop.usage.output == 3
        assert ev.hops[2].verdict == "approve"

    def test_trace_link_resolves_to_the_hops_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task_id = _run_three_hops(monkeypatch)
        ev = _ev.task_evidence("demo", task_id, "1.1.0")
        for hop in ev.hops:
            assert hop.trace is not None
            found = _trace.find_trace(hop.trace.session)
            assert found is not None and found.parent.name == hop.trace.project == "demo"
            window = [
                r
                for r in _trace.read_trace(found)
                if hop.trace.first_ts <= r["ts"] <= hop.trace.last_ts
                and r.get("agent_role") == hop.role
            ]
            assert window, f"no events for {hop.role} inside its recorded window"
            assert any(r["event_type"] == "llm_call" for r in window)

    def test_legacy_record_without_the_new_fields_builds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "old", channel="cli")
        _seed_task(task["id"], [{"role": "lead", "member": "demo-lead", "ok": True}])
        ev = _ev.task_evidence("demo", task["id"], "1.1.0")
        hop = ev.hops[0]
        assert hop.usage is None and hop.trace is None and hop.verify is None
        assert hop.commit is None and hop.step_id == "lead"

    def test_unknown_task_raises_named_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(_ev.EvidenceNotFound):
            _ev.task_evidence("demo", "task-nope", "1.1.0")


_GATED_VERIFY = {
    "cmd": "verifier --base a",
    "exitCode": 1,
    "durationS": 0.2,
    "outputTail": "nope",
    "label": "fail",
    "reasons": ["a reason"],
    "reasonsInvalid": False,
}
_REPO_FILES = {"AGENTS.md": "a" * 64}


def _gated_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    _seed_pod(tmp_path, monkeypatch)
    task = _dispatch.enqueue_task("demo", "gated", channel="cli")
    first = {"role": "implementer", "member": "m", "ok": True, "verify": _GATED_VERIFY}
    second = {"role": "reviewer", "member": "m", "ok": True}
    _seed_task(
        task["id"],
        [
            {**first, "repoFiles": _REPO_FILES},
            {**second, "repoFiles": {**_REPO_FILES, "skills/x/SKILL.md": "b" * 64}},
        ],
    )
    return str(task["id"])


def _schema(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "docs" / "contracts" / name / "schema.json").read_text())


class TestEvidence11:
    def test_gate_and_directives_are_present_and_validate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import jsonschema

        task_id = _gated_task(tmp_path, monkeypatch)
        doc = _ev.task_evidence("demo", task_id, "1.1.0").model_dump(by_alias=True, mode="json")
        assert doc["v"] == "1.1.0"
        assert doc["hops"][0]["gate"] == {"label": "fail", "exitCode": 1, "reasonsInvalid": False}
        assert "gate" not in doc["hops"][1]
        assert doc["directives"] == [
            {"path": "AGENTS.md", "sha256": "a" * 64},
            {"path": "skills/x/SKILL.md", "sha256": "b" * 64},
        ]
        jsonschema.validate(doc, _schema("evidence-v1.1"))

    def test_a_task_with_neither_carries_neither_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import jsonschema

        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "plain", channel="cli")
        plain = {"role": "lead", "member": "m", "ok": True, "verify": {**_GATED_VERIFY}}
        del plain["verify"]["label"]
        _seed_task(task["id"], [plain])
        ev = _ev.task_evidence("demo", task["id"], "1.1.0")
        doc = json.loads(ev.model_dump_json(by_alias=True))
        assert "directives" not in doc and "gate" not in doc["hops"][0]
        jsonschema.validate(doc, _schema("evidence-v1.1"))

    def test_unknown_version_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task_id = _gated_task(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            _ev.task_evidence("demo", task_id, "2.0.0")


class TestRepoFilesOnTheHop:
    def test_round_trips_through_the_persisted_record(self) -> None:
        hop = _dispatch.HopResult(role="lead", member_id="m", ok=True, repo_files=_REPO_FILES)
        rec = _dispatch._hop_record(hop)
        assert rec["repoFiles"] == _REPO_FILES
        assert _dispatch._hop_from_record(rec).repo_files == _REPO_FILES
        assert _dispatch._hop_from_record({"role": "lead"}).repo_files == {}

    def test_dispatch_copies_the_turns_repo_files_onto_the_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        backend = _Backend(["lead plan", "implementer done", "fine\nAPPROVE"])
        driver = DocketDriver(backend_factory=lambda model: backend)
        real = driver.run_turn

        def with_files(*args: Any, **kwargs: Any) -> Any:
            turn = real(*args, **kwargs)
            turn.repo_files = dict(_REPO_FILES)
            return turn

        monkeypatch.setattr(driver, "run_turn", with_files)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)
        task = _dispatch.enqueue_task("demo", "files", channel="cli")
        assert _dispatch.dispatch_pod("demo")[0].status == "done"
        doc = _ev.task_evidence("demo", str(task["id"]), "1.1.0")
        assert [d.path for d in doc.directives or []] == ["AGENTS.md"]


def test_schema_check_passes() -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_evidence_schema", ROOT / "scripts" / "gen_evidence_schema.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0
