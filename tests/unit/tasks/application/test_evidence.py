"""evidence-v1: the model, the one builder, and the schema artifact."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off
from tests.pods import build_pod

from docket.agent import driver as _dr
from docket.agent.driver import DocketDriver
from docket.agent.llm import ChatMessage, ChatResponse, TokenUsage, assistant
from docket.hops.application import record as _record
from docket.kernel.home import Home, use_home
from docket.observability import trace as _trace
from docket.tasks.application import evidence as _ev
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.evidence"
ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed_pod(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        build_pod("demo", ("lead", "implementer", "reviewer"), codebase="/src/demo")
        yield home


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
    task = _queue.enqueue_task_once("demo", "evidence please", channel="cli")[0]
    results = _sweep.dispatch_pod("demo")
    assert results[0].status == "done"
    return str(task["id"])


def _seed_task(task_id: str, hops: list[dict[str, Any]]) -> None:
    path = _settings.pod_task_list_path("demo")
    raw = json.loads(path.read_text())
    for t in raw["tasks"]:
        if t["id"] == task_id:
            t["hops"] = hops
    path.write_text(json.dumps(raw))


class TestTaskEvidence:
    def test_three_hops_each_with_measured_usage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
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
        with _seed_pod(tmp_path):
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

    def test_unknown_task_raises_named_error(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), pytest.raises(_ev.EvidenceNotFound):
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


@contextmanager
def _gated_task(
    tmp_path: Path,
) -> Iterator[str]:
    with _seed_pod(tmp_path):
        task = _queue.enqueue_task_once("demo", "gated", channel="cli")[0]
        first = {"role": "implementer", "member": "m", "ok": True, "verify": _GATED_VERIFY}
        second = {"role": "reviewer", "member": "m", "ok": True}
        _seed_task(
            task["id"],
            [
                {**first, "repoFiles": _REPO_FILES},
                {**second, "repoFiles": {**_REPO_FILES, "skills/x/SKILL.md": "b" * 64}},
            ],
        )
        yield str(task["id"])


def _schema(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "docs" / "contracts" / name / "schema.json").read_text())


class TestEvidence11:
    def test_gate_and_directives_are_present_and_validate(self, tmp_path: Path) -> None:
        import jsonschema

        with _gated_task(tmp_path) as task_id:
            doc = _ev.task_evidence("demo", task_id, "1.1.0").model_dump(by_alias=True, mode="json")
            assert doc["v"] == "1.1.0"
            assert doc["hops"][0]["gate"] == {
                "label": "fail",
                "exitCode": 1,
                "reasonsInvalid": False,
            }
            assert "gate" not in doc["hops"][1]
            assert doc["directives"] == [
                {"path": "AGENTS.md", "sha256": "a" * 64},
                {"path": "skills/x/SKILL.md", "sha256": "b" * 64},
            ]
            jsonschema.validate(doc, _schema("evidence-v1.1"))

    def test_a_task_with_neither_carries_neither_field(self, tmp_path: Path) -> None:
        import jsonschema

        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "plain", channel="cli")[0]
            plain = {"role": "lead", "member": "m", "ok": True, "verify": {**_GATED_VERIFY}}
            del plain["verify"]["label"]
            _seed_task(task["id"], [plain])
            ev = _ev.task_evidence("demo", task["id"], "1.1.0")
            doc = json.loads(ev.model_dump_json(by_alias=True))
            assert "directives" not in doc and "gate" not in doc["hops"][0]
            jsonschema.validate(doc, _schema("evidence-v1.1"))

    def test_unknown_version_is_refused(self, tmp_path: Path) -> None:
        with _gated_task(tmp_path) as task_id, pytest.raises(ValueError):
            _ev.task_evidence("demo", task_id, "2.0.0")


class TestRepoFilesOnTheHop:
    def test_round_trips_through_the_persisted_record(self) -> None:
        hop = _task.HopResult(role="lead", member_id="m", ok=True, repo_files=_REPO_FILES)
        rec = _record._hop_record(hop)
        assert rec["repoFiles"] == _REPO_FILES
        assert _record._hop_from_record(rec).repo_files == _REPO_FILES
        assert _record._hop_from_record({"role": "lead"}).repo_files == {}

    def test_dispatch_copies_the_turns_repo_files_onto_the_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            backend = _Backend(["lead plan", "implementer done", "fine\nAPPROVE"])
            driver = DocketDriver(backend_factory=lambda model: backend)
            real = driver.run_turn

            def with_files(*args: Any, **kwargs: Any) -> Any:
                turn = real(*args, **kwargs)
                turn.repo_files = dict(_REPO_FILES)
                return turn

            monkeypatch.setattr(driver, "run_turn", with_files)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)
            task = _queue.enqueue_task_once("demo", "files", channel="cli")[0]
            assert _sweep.dispatch_pod("demo")[0].status == "done"
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
