"""The model is told the file state it will be judged on: a missing final newline is visible.

The whole product runs for real as ``python -m docket`` subprocesses over a real git repo; only
the model is faked. The Implementer writes a file with no final newline and reads it back, and
the tool results it received are what the test asserts on.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say

PIPELINE = """name: file-state
steps:
  - implement: implementer
"""


def test_write_and_read_tell_the_model_the_file_has_no_final_newline(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                call("write", "c1", path="app.txt", content="docket smoke ok"),
                call("read", "c2", path="app.txt"),
                call("bash", "c3", command="cat app.txt"),
                say("Done."),
            ]
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    task_id = w.add_task("Write app.txt")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    assert w.task(task_id)["task"]["status"] == "done"
    seen = model.by_role("implementer")[-1]
    wrote, read, shown = (seen.tool_result(c) for c in ("c1", "c2", "c3"))
    assert wrote == "wrote app.txt: 15 bytes, 1 lines, ends with newline: no (overwritten)"
    assert read is not None and read.endswith("[1 lines; no newline at end of file]")
    assert shown == "docket smoke ok\n[output had no trailing newline]"
