"""A task carries its own pipeline variables: posted, stored, shown, and read by a step's ``when``.

Spec: operator-api.spec.md ("POST /tasks/<pod> -- the task body", ``variables``) and
pod-dispatch.spec.md ("Conditional steps and command steps").
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.support.fakes import FakeDriver
from tests.support.http import get as _get
from tests.support.http import post as _post
from tests.support.pods import seed_pod as _seed_pod
from tests.support.pods import spec as _spec
from tests.support.task_unit_harness import _runner

from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.app import app
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application.repository import TaskRepository

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-task-variables"

_PIPELINE = """name: tiered
steps:
  - build: implementer
  - polish: implementer
    when: {var: tier, is: gold}
"""


@contextmanager
def _live_server() -> Iterator[str]:
    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    _Handler.dispatch_on = False
    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def _steps_by_task(results: list) -> dict[str, list[str]]:  # type: ignore[type-arg]
    return {r.task_id: [h.step_id for h in r.hops] for r in results}


class TestTaskVariablesOverHttp:
    def test_posted_variables_show_on_the_task_and_decide_a_when_step(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as url:
            _, gold = _post(
                f"{url}/tasks/demo", {"description": "a", "variables": {"tier": "gold"}}, _TOKEN
            )
            _, plain = _post(f"{url}/tasks/demo", {"description": "b"}, _TOKEN)

            status, shown = _get(f"{url}/tasks/demo/{gold['task']}", _TOKEN)
            assert status == 200
            record = shown.get("task", shown)
            assert record["variables"] == {"tier": "gold"}
            _, other = _get(f"{url}/tasks/demo/{plain['task']}", _TOKEN)
            assert "variables" not in other.get("task", other)

            results = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_spec(_PIPELINE))

            assert _steps_by_task(results) == {
                gold["task"]: ["build", "polish"],
                plain["task"]: ["build"],
            }

    def test_a_task_variable_wins_over_the_runs_variable(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as url:
            _, task = _post(
                f"{url}/tasks/demo", {"description": "a", "variables": {"tier": "gold"}}, _TOKEN
            )
            _, bare = _post(f"{url}/tasks/demo", {"description": "b"}, _TOKEN)

            results = _sweep.dispatch_pod(
                "demo", runner=FakeDriver(), spec=_spec(_PIPELINE), variables={"tier": "silver"}
            )

            assert _steps_by_task(results) == {
                task["task"]: ["build", "polish"],
                bare["task"]: ["build"],
            }

    def test_a_value_that_is_not_a_string_is_400_and_nothing_is_enqueued(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path), _live_server() as url:
            for bad in ({"tier": 3}, {"tier": None}, {"tier": ["gold"]}, "tier=gold", ["tier"]):
                status, body = _post(
                    f"{url}/tasks/demo", {"description": "x", "variables": bad}, _TOKEN
                )
                assert status == 400, bad
                assert "variables" in body["error"]
            assert TaskRepository.for_pod("demo").list() == []

    def test_a_body_without_the_field_stores_no_variables_key(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as url:
            _post(f"{url}/tasks/demo", {"description": "x", "variables": {}}, _TOKEN)
            _post(f"{url}/tasks/demo", {"description": "y"}, _TOKEN)

            stored = [
                r.model_dump(by_alias=True, mode="json")
                for r in TaskRepository.for_pod("demo").list()
            ]

            assert all("variables" not in r for r in stored)
            assert json.dumps(stored)


class TestTaskVariablesFromTheCli:
    def test_task_add_var_decides_a_when_step_for_that_task_only(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _runner.invoke(app, ["task", "add", "a", "--var", "tier=gold", "--pod", "demo"])
            _runner.invoke(app, ["task", "add", "b", "--pod", "demo"])
            gold, plain = TaskRepository.for_pod("demo").list()

            results = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_spec(_PIPELINE))

            assert _steps_by_task(results) == {
                gold.id: ["build", "polish"],
                plain.id: ["build"],
            }
