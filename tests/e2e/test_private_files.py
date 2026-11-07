"""A model told not to open docket's private control files is refused when it tries.

The whole product runs for real as ``python -m docket`` subprocesses; only the model is faked, and
it is scripted to read a private file. The pod is a folder pod: its working directory is the root
the file tools allow, and it holds a ``MEMORY.md``. Isolation is off on purpose, so the file tools
and the classifier are what is under test on every machine.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.e2e_workdir import workdir_pod
from tests.support.model_server import FakeModel, Reply, Request, call, say

PROBE = """name: probe
steps:
  - compile: analyst
"""
SECRET = "the private notes of the pod"


def _probe(world: Callable[..., World], model: FakeModel) -> tuple[World, str]:
    w, work_dir = workdir_pod(world, model, pipeline_yaml=PROBE)
    (work_dir / "MEMORY.md").write_text(f"{SECRET}\n", encoding="utf-8")
    (work_dir / "src").mkdir()
    (work_dir / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    task_id = w.add_task("Compile the notes")
    w.docket("run", "--pod", w.pod, "--pipeline", str(w.pipeline), "--timeout", "30", check=False)
    return w, task_id


def _audited(w: World, action: str) -> list[dict[str, str]]:
    return [r for r in oracles.audit_rows(w) if r["action"] == action]


def test_a_read_of_a_private_control_file_is_refused_and_audited(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    seen: dict[str, str | None] = {}

    def report(request: Request) -> Reply:
        seen["memory"] = request.tool_result("memory")
        return say("MEMORY.md could not be read.")

    model = fake_model(script={"analyst": [call("read", "memory", path="MEMORY.md"), report]})

    w, task_id = _probe(world, model)

    assert w.task(task_id)["task"]["status"] == "done"
    refused = _audited(w, "tool.refused")
    assert len(refused) == 1
    assert "kind=private_path" in refused[0]["detail"] and "MEMORY.md" in refused[0]["detail"]
    assert SECRET not in refused[0]["detail"]
    assert seen["memory"] is not None and seen["memory"].startswith("ERROR")
    assert SECRET not in seen["memory"]
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_log_verifies(w)


def test_a_shell_read_of_a_private_control_file_waits_for_a_person_with_isolation_off(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={"analyst": [call("bash", "cat", command="cat MEMORY.md"), say("never reached")]}
    )

    w, task_id = _probe(world, model)

    assert w.task(task_id)["task"]["status"] == "waiting_approval"
    asked = _audited(w, "tool.ask")
    assert len(asked) == 1 and "private control path" in asked[0]["detail"]
    assert len(model.by_role("analyst")) == 1


def test_an_ordinary_file_in_the_same_root_is_read(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    seen: dict[str, str | None] = {}

    def report(request: Request) -> Reply:
        seen["app"] = request.tool_result("app")
        return say("app.py read.")

    model = fake_model(script={"analyst": [call("read", "app", path="src/app.py"), report]})

    w, task_id = _probe(world, model)

    assert w.task(task_id)["task"]["status"] == "done"
    assert seen["app"] is not None and "print('app')" in seen["app"]
    assert _audited(w, "tool.refused") == []
