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
    task = _dispatch.enqueue_task("demo", "evidence please")
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
        ev = _ev.task_evidence("demo", task_id)
        assert ev.v == _ev.EVIDENCE_CONTRACT_VERSION == "1.0.0"
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
        ev = _ev.task_evidence("demo", task_id)
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

    def test_evidence_never_carries_the_internal_touched_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        rec = _dispatch._hop_record(
            _dispatch.HopResult(
                role="implementer",
                member_id="demo-implementer",
                ok=True,
                verify={
                    "cmd": "true",
                    "exitCode": 0,
                    "durationS": 0.1,
                    "outputTail": "",
                    "touched": ["/x/y"],
                },
            )
        )
        _seed_task(task["id"], [rec])
        ev = _ev.task_evidence("demo", task["id"])
        assert ev.hops[0].verify is not None
        assert "touched" not in json.dumps(ev.model_dump(by_alias=True))

    def test_legacy_record_without_the_new_fields_builds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "old")
        _seed_task(task["id"], [{"role": "lead", "member": "demo-lead", "ok": True}])
        ev = _ev.task_evidence("demo", task["id"])
        hop = ev.hops[0]
        assert hop.usage is None and hop.trace is None and hop.verify is None
        assert hop.commit is None and hop.step_id == "lead"

    def test_unknown_task_raises_named_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(_ev.EvidenceNotFound):
            _ev.task_evidence("demo", "task-nope")


def test_schema_check_passes() -> None:
    spec = importlib.util.spec_from_file_location(
        "gen_evidence_schema", ROOT / "scripts" / "gen_evidence_schema.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0
