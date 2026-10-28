"""`GET /metrics` and `docket log --summary` carry the cache-hit ratio and tokens per accepted task."""

from __future__ import annotations

import shutil
import threading
import urllib.request
from pathlib import Path

import pytest
from tests.support.http import metric_sample
from tests.support.pods import seed_pod
from typer.testing import CliRunner

from docket.interfaces.cli.app import app
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.parts import TaskUsage
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import TaskRecord

SUBJECT = "docket.observability.figures"

TRACE_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "traces" / "dispatch-3-hops.jsonl"
)

runner = CliRunner()


def _scrape() -> list[str]:
    """`GET /metrics` from a server started now, so it serves the home in force."""

    class _Handler(_DocketHandler):
        serve_token = "unused"

    server = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode().splitlines()
    finally:
        server.shutdown()


def _seed_trace() -> None:
    target = current_home().traces_dir / "demo-project"
    target.mkdir(parents=True)
    shutil.copy(TRACE_FIXTURE, target / "s1.jsonl")


def _settle(project: str, goal: str, status: Status, usage: dict[str, int]) -> TaskRecord:
    queued, _ = _queue.enqueue_task_once(project, goal, channel="cli")

    def _fn(task: TaskRecord) -> None:
        task.status = status
        task.usage = TaskUsage.model_validate(usage)

    updated = TaskRepository.for_pod(project).update(queued.id, _fn)
    assert updated is not None
    return updated


def _seed_tasks(project: str) -> None:
    # Counted tokens: (1000 - 400) + 50 = 650 and (200 - 0) + 100 = 300; the failed one is out.
    _settle(project, "first", Status.done, {"input": 1000, "cached": 400, "output": 50})
    _settle(project, "second", Status.done, {"input": 200, "cached": 0, "output": 100})
    _settle(project, "third", Status.failed, {"input": 90000, "cached": 0, "output": 9000})


def test_metrics_shows_the_cache_hit_of_the_recording_role(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_trace()

        lines = _scrape()

    # Two implementer calls in the fixture: (0 + 20) cached over (120 + 180) input.
    assert metric_sample(lines, 'docket_cache_hit_ratio{role="implementer"}') == pytest.approx(
        20 / 300
    )
    assert not any("docket_tokens_per_accepted_task" in ln for ln in lines if ln[0] != "#")


def test_metrics_shows_the_counted_tokens_of_done_tasks_only(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_tasks("demo")

        lines = _scrape()

    assert metric_sample(lines, "docket_tokens_per_accepted_task ") == (650 + 300) / 2


def test_log_summary_prints_tokens_per_accepted_task_and_cache_hit(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        _seed_tasks("demo")
        _seed_trace()

        result = runner.invoke(app, ["log", "--summary"])

    assert result.exit_code == 0, result.output
    assert "tokens per accepted task: 475 counted (2 done tasks)" in result.output
    assert "cache hit: 6.7% (20 of 300 input tokens)" in result.output


def test_log_summary_with_no_done_task_says_so(tmp_path: Path) -> None:
    with seed_pod(tmp_path):
        result = runner.invoke(app, ["log", "--summary"])

    assert result.exit_code == 0, result.output
    assert "tokens per accepted task: no done task with usage yet" in result.output
    assert "cache hit: no llm_call recorded yet" in result.output
