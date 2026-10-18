"""A writing hop's output reaches the next hop as a capped diff, once, through the real dispatch."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, register_local_provider, repoint_docket_home
from tests.integration.llm_stub import _final_response, _tool_call_response

from docket.cli import _pod
from docket.config import HANDOFF_DIFF_MAX_CHARS
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet

SUBJECT = "docket.core.dispatch"

_NOTE = "NOTE-SENTENCE-7731 the finding the critic must see"
_PIPELINE = (
    "name: research-then-critic\n"
    "steps:\n"
    "  - id: researcher\n    role: researcher\n"
    "  - id: critic\n    role: critic\n"
)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_TOOL_MAX_OUTPUT_CHARS", "2500")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _seed_research_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    codebase = tmp_path / "code"
    codebase.mkdir()
    subprocess.run(["git", "init", str(codebase)], check=True, capture_output=True)
    _git(codebase, "config", "user.email", "t@t.test")
    _git(codebase, "config", "user.name", "T")
    (codebase / "README.md").write_text("hello\n")
    _git(codebase, "add", ".")
    _git(codebase, "commit", "-m", "init")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    register_local_provider(home, "local", [{"id": "stub"}], base_url=base_url)
    _pod.build_pod("demo", ("lead", "researcher", "critic"), codebase=str(codebase))
    for role in ("lead", "researcher", "critic"):
        _fleet.meta_set(_pod.pod.member_id("demo", role), "model", "local/stub")
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_PIPELINE, encoding="utf-8")
    digest = hashlib.sha256(_PIPELINE.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


def _run_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, llm_server: Any, note: str
) -> tuple[Any, list[dict[str, Any]]]:
    server = llm_server(
        [
            _tool_call_response("write", {"path": "notes/x.md", "content": note}),
            _final_response("researcher done"),
            _final_response("APPROVE"),
        ]
    )
    _seed_research_pod(tmp_path, monkeypatch, server.base_url)
    _dispatch.enqueue_task("demo", "research the topic", channel="cli")
    (result,) = _dispatch.dispatch_pod("demo", max_tasks=1)
    assert result.status == "done", result.reason
    hops = _dispatch.read_tasks("demo")[0]["hops"]
    return server, hops


def test_critic_first_request_carries_the_researchers_note_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, llm_server: Any
) -> None:
    """The next hop's first request holds the note the previous hop wrote, exactly once."""
    server, _hops = _run_pipeline(tmp_path, monkeypatch, llm_server, _NOTE)

    critic_first = json.dumps(server.requests[2])

    assert critic_first.count(_NOTE) == 1


def test_a_note_past_the_cap_is_cut_with_a_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, llm_server: Any
) -> None:
    """A 50k-character note reaches the critic cut at the cap, and the cut is announced."""
    note = "\n".join(f"line-{i:05d}" for i in range(5000))
    assert len(note) > 50_000
    server, hops = _run_pipeline(tmp_path, monkeypatch, llm_server, note)

    critic_first = json.dumps(server.requests[2])

    assert "line-00001" in critic_first
    assert "line-04999" not in critic_first
    assert "diff cut at" in critic_first
    assert len(hops[0]["artifact"]["diff"]) < HANDOFF_DIFF_MAX_CHARS + 200


def test_a_hop_that_changed_nothing_adds_no_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, llm_server: Any
) -> None:
    """The writing hop's artifact carries the diff; the read-only critic after it carries none."""
    _server, hops = _run_pipeline(tmp_path, monkeypatch, llm_server, _NOTE)

    assert _NOTE in hops[0]["artifact"]["diff"]
    assert hops[1]["artifact"]["diff"] == ""
    assert hops[1]["artifact"]["files_changed"] == []
