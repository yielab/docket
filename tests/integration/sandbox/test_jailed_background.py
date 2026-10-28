"""A background `bash` command inside the Landlock jail logs to the pod cache and leaves no orphan."""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

import pytest
from tests.support.git import pgrep_count

from docket.agent.tools.registry import ToolContext
from docket.hops.application.builtin_tools import builtin_registry
from docket.sandbox import landlock

SUBJECT = "docket.agent.tools.builtins.background"

pytestmark = pytest.mark.skipif(not landlock.landlock_available(), reason="Landlock not available")

_STARTED = re.compile(r"started pgid=(\d+) log=(\S+)")


def _call(name: str, args: dict[str, object], ctx: ToolContext):  # type: ignore[no-untyped-def]
    tool = builtin_registry().get(name)
    assert tool is not None
    return tool.handler(args, ctx)


def test_a_jailed_background_command_is_stopped_with_the_children_it_forked(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    marker = f"bg-jail-{uuid.uuid4().hex[:8]}"
    seconds = 4000 + uuid.uuid4().int % 900
    ctx = ToolContext(roots=(work,), timeout=60, sandbox="auto", cache_dir=cache)

    started = time.monotonic()
    out = _call(
        "bash",
        {
            "command": f"echo {marker}; sleep {seconds} & sleep {seconds + 1} & wait",
            "background": True,
        },
        ctx,
    )
    elapsed = time.monotonic() - started

    found = _STARTED.search(out.content)
    assert out.ok and found is not None and elapsed < 2, (out, elapsed)
    pgid, log = int(found.group(1)), Path(found.group(2))
    assert log == cache / "processes" / f"{pgid}.log" and "[sandbox: landlock]" in out.content
    deadline = time.monotonic() + 5
    while marker not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pgrep_count(f"sleep {seconds}") >= 1
    assert "alive: true" in _call("process_output", {"pgid": pgid}, ctx).content

    stopped = _call("process_stop", {"pgid": pgid}, ctx)

    assert stopped.ok
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)
    assert pgrep_count(f"sleep {seconds}") == 0
