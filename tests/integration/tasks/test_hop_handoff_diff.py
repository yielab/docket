"""A writing hop's output reaches the next hop as a capped diff, once, through the real dispatch."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.support.home import record_isolation_off, register_local_provider
from tests.support.model_server import call, say
from tests.support.pods import build_pod

from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"

_NOTE = "NOTE-SENTENCE-7731 the finding the critic must see"
_PIPELINE = "name: research-then-critic\nsteps:\n  - researcher: researcher\n  - critic: critic\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@contextmanager
def _seed_research_pod(tmp_path: Path, base_url: str) -> Iterator[None]:
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
    with use_home(Home(home)):
        record_isolation_off(home)
        register_local_provider(home, "local", [{"id": "stub"}], base_url=base_url)
        build_pod("demo", ("lead", "researcher", "critic"), codebase=str(codebase))
        for role in ("lead", "researcher", "critic"):
            _fleet.meta_set(_pod.pod.member_id("demo", role), "model", "local/stub")
        path = _pod.pod.bound_pipeline_path("demo")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_PIPELINE, encoding="utf-8")
        digest = hashlib.sha256(_PIPELINE.encode("utf-8")).hexdigest()
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)
        yield


@contextmanager
def _run_pipeline(
    tmp_path: Path, fake_model: Any, note: str
) -> Iterator[tuple[Any, list[HopResult]]]:
    server = fake_model(
        sequence=[
            call("write", path="notes/x.md", content=note),
            say("researcher done"),
            call("handoff", verdict="APPROVE"),
        ]
    )
    with _seed_research_pod(tmp_path, server.base_url):
        _queue.enqueue_task_once("demo", "research the topic", channel="cli")
        (result,) = _sweep.dispatch_pod("demo", max_tasks=1)
        assert result.status == "done", result.reason
        hops = TaskRepository.for_pod("demo").list()[0].hops
        yield server, hops


def test_critic_first_request_carries_the_researchers_note_once(
    tmp_path: Path, fake_model: Any
) -> None:
    """The next hop's first request holds the note the previous hop wrote, exactly once."""
    with _run_pipeline(tmp_path, fake_model, _NOTE) as (server, _hops):
        critic_first = json.dumps(server.requests[2].body)

        assert critic_first.count(_NOTE) == 1


def test_a_note_past_the_cap_is_cut_with_a_marker(tmp_path: Path, fake_model: Any) -> None:
    """A 50k-character note reaches the critic cut at the cap, and the cut is announced."""
    note = "\n".join(f"line-{i:05d}" for i in range(5000))
    assert len(note) > 50_000
    with _run_pipeline(tmp_path, fake_model, note) as (server, hops):
        critic_first = json.dumps(server.requests[2].body)

        assert "line-00001" in critic_first
        assert "line-04999" not in critic_first
        assert "diff cut at" in critic_first
        assert len(hops[0].artifact.diff) < current_home().handoff_diff_max_chars + 200


def test_a_hop_that_changed_nothing_adds_no_diff(tmp_path: Path, fake_model: Any) -> None:
    """The writing hop's artifact carries the diff; the read-only critic after it carries none."""
    with _run_pipeline(tmp_path, fake_model, _NOTE) as (_server, hops):
        assert _NOTE in hops[0].artifact.diff
        assert hops[1].artifact.diff == ""
        assert hops[1].artifact.files_changed == []
