"""A hop that keeps making model rounds is never swept as a stale claim, whatever a round costs."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from tests.support.home import record_isolation_off, register_local_provider
from tests.support.model_server import Reply, Request, call, say
from tests.support.pods import build_pod
from tests.support.tasks import stored_task, update_task

from docket.hops.application import sweep as _sweep
from docket.kernel import clock as _clock
from docket.kernel.home import Home, use_home
from docket.pipeline.domain.spec import PipelineSpec
from docket.pipeline.domain.step import Step
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.driver_support"

# Past max(CLAIM_STALE_TIMEOUT, lease): the default floor is 1,800 s and no lease is declared.
_LONG_AGO_S = 7200


def _seed_pod(tmp_path: Path, base_url: str) -> None:
    codebase = tmp_path / "code"
    codebase.mkdir()
    subprocess.run(["git", "init", str(codebase)], check=True, capture_output=True)
    (codebase / "a.txt").write_text("a\n")
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    record_isolation_off(home)
    register_local_provider(home, "local", [{"id": "stub"}], base_url=base_url, toolSurface="full")
    build_pod("demo", ("lead", "implementer"), codebase=str(codebase))
    for role in ("lead", "implementer"):
        _fleet.meta_set(f"demo-{role}", "model", "local/stub")


def test_a_hop_making_rounds_without_a_process_is_not_swept(
    tmp_path: Path, fake_model: Any
) -> None:
    """A round ages the claim past the floor; the next round's sweep must still find it live."""
    swept: list[str] = []

    home = Home(tmp_path / ".docket")

    def _task_id() -> str:
        return TaskRepository.for_pod("demo").list()[0].id

    def _age_the_claim(_request: Request) -> Reply:
        old = _clock.now() - timedelta(seconds=_LONG_AGO_S)
        with use_home(home):  # the fake model answers on its own thread
            update_task("demo", _task_id(), claimed_at=old.isoformat())
        return call("read", call_id="c1", path="f1.txt")

    def _sweep_then_read(n: int) -> Callable[[Request], Reply]:
        def _step(_request: Request) -> Reply:
            with use_home(home):
                _lifecycle.sweep_stale_claims("demo")
                swept.append(stored_task("demo", _task_id()).status)
            return call("read", call_id=f"c{n}", path=f"f{n}.txt")

        return _step

    server = fake_model(
        sequence=[
            call("read", call_id="c0", path="f0.txt"),
            _age_the_claim,
            _sweep_then_read(2),
            _sweep_then_read(3),
            say("done"),
        ]
    )
    spec = PipelineSpec(name="solo", steps=[Step(id="build", role="implementer")])
    with use_home(home):
        _seed_pod(tmp_path, server.base_url)
        _queue.enqueue_task_once("demo", "touch nothing", channel="cli")
        _sweep.dispatch_pod("demo", max_tasks=1, spec=spec)

    assert swept == ["running", "running"]
