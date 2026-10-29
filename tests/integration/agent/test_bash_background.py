"""A `bash` command that runs in the background: a handle, its log, and no orphan at turn end.

`bash` with `background: true` starts the command in its own session and answers at once with
its pgid and log path; `process_output` reads the log and `process_stop` kills the group. A real
`DocketDriver` turn stops whatever is still alive when it ends and traces each exit with
`reason: turn_end`.
"""

from __future__ import annotations

import dataclasses
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support import pods as _support_pods
from tests.support.fakes import FakeJail
from tests.support.git import pgrep_count as _pgrep_count
from tests.support.model_server import FakeModel, Reply, Request, call, say
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.trace import trace_events

from docket.agent.tools.registry import ToolContext
from docket.hops.application.builtin_tools import builtin_registry
from docket.hops.application.driver import DocketDriver
from docket.kernel import ports as _ports
from docket.kernel.home import current_home, use_home
from docket.models import catalog as _catalog

workspace = _support_pods.workspace

SUBJECT = "docket.agent.tools.builtins.background"

_STARTED = re.compile(r"started pgid=(\d+) log=(\S+)")


def _sleeper(marker: str, seconds: int = 30) -> str:
    return f'python3 -c "import time; time.sleep({seconds})  # {marker}"'


def _handler(name: str) -> Callable[[dict[str, Any], ToolContext], Any]:
    tool = builtin_registry().get(name)
    assert tool is not None, name
    return tool.handler


def _context(workspace: Path, tmp_path: Path, **fields: Any) -> ToolContext:
    return ToolContext(roots=(workspace,), timeout=60, cache_dir=tmp_path / "cache", **fields)


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


class TestBackgroundTool:
    def test_the_call_returns_at_once_with_a_pgid_and_a_log_that_alive_reads_true(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        marker = f"bg-alive-{uuid.uuid4().hex[:8]}"
        events: list[tuple[str, dict[str, Any]]] = []
        ctx = _context(
            workspace, tmp_path, on_process=lambda kind, data: events.append((kind, data))
        )

        started = time.monotonic()
        out = _handler("bash")({"command": _sleeper(marker), "background": True}, ctx)
        elapsed = time.monotonic() - started

        try:
            assert out.ok and elapsed < 1, (out, elapsed)
            found = _STARTED.search(out.content)
            assert found is not None, out.content
            pgid, log = int(found.group(1)), Path(found.group(2))
            assert log == tmp_path / "cache" / "processes" / f"{pgid}.log" and log.exists()
            assert list(ctx.processes) == [pgid]
            assert events == [("started", {"pgid": pgid, "background": True, "tool": "bash"})]

            seen = _handler("process_output")({"pgid": pgid}, ctx)

            assert seen.ok and "alive: true" in seen.content
        finally:
            _handler("process_stop")({"pgid": next(iter(ctx.processes), 0)}, ctx)

    def test_process_stop_kills_the_group_and_records_the_signal(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        marker = f"bg-stop-{uuid.uuid4().hex[:8]}"
        events: list[tuple[str, dict[str, Any]]] = []
        ctx = _context(
            workspace, tmp_path, on_process=lambda kind, data: events.append((kind, data))
        )
        out = _handler("bash")({"command": _sleeper(marker), "background": True}, ctx)
        pgid = int(_STARTED.search(out.content).group(1))  # type: ignore[union-attr]

        stopped = _handler("process_stop")({"pgid": pgid}, ctx)

        assert stopped.ok and stopped.content == f"stopped pgid={pgid}"
        assert not _alive(pgid) and _pgrep_count(marker) == 0
        assert events[-1] == (
            "exited",
            {"pgid": pgid, "signal": "SIGKILL", "tool": "bash"},
        )
        again = _handler("process_output")({"pgid": pgid}, ctx)
        assert again.ok and "alive: false" in again.content
        _handler("process_stop")({"pgid": pgid}, ctx)
        assert [kind for kind, _ in events] == ["started", "exited"]

    def test_process_output_reads_the_log_from_an_offset_and_reports_the_exit(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        ctx = _context(
            workspace, tmp_path, on_process=lambda kind, data: events.append((kind, data))
        )
        out = _handler("bash")({"command": "echo hello; echo world", "background": True}, ctx)
        pgid = int(_STARTED.search(out.content).group(1))  # type: ignore[union-attr]
        deadline = time.monotonic() + 5
        seen = _handler("process_output")({"pgid": pgid}, ctx)
        while "alive: false" not in seen.content and time.monotonic() < deadline:
            time.sleep(0.05)
            seen = _handler("process_output")({"pgid": pgid}, ctx)

        assert "alive: false" in seen.content and "exit: 0" in seen.content
        assert "hello\nworld" in seen.content and "offset: 12" in seen.content
        tail = _handler("process_output")({"pgid": pgid, "offset": 6}, ctx)
        assert "world" in tail.content and "hello" not in tail.content
        assert [kind for kind, _ in events] == ["started", "exited"]
        assert events[-1][1]["exitCode"] == 0

    def test_an_unknown_pgid_is_a_failed_call(self, workspace: Path, tmp_path: Path) -> None:
        ctx = _context(workspace, tmp_path)

        for name in ("process_output", "process_stop"):
            out = _handler(name)({"pgid": 99999}, ctx)
            assert not out.ok and "99999" in out.error

    def test_no_directory_for_the_log_refuses_and_starts_nothing(self, workspace: Path) -> None:
        marker = f"bg-nodir-{uuid.uuid4().hex[:8]}"
        ctx = ToolContext(roots=(workspace,), timeout=60)

        out = _handler("bash")({"command": _sleeper(marker), "background": True}, ctx)

        assert not out.ok and "processes" in out.error
        assert not ctx.processes and _pgrep_count(marker) == 0

    def test_an_unjailed_log_is_under_the_homes_directory_for_the_agent_not_the_scratch_dir(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        ctx = ToolContext(
            agent_id="bg-impl",
            roots=(workspace,),
            timeout=60,
            env={"DOCKET_SCRATCH_DIR": str(tmp_path / "scratch")},
        )

        out = _handler("bash")({"command": "true", "background": True}, ctx)

        found = _STARTED.search(out.content)
        assert found is not None
        assert Path(found.group(2)).parent == current_home().process_logs_dir("bg-impl")

    def test_the_docker_backend_refuses_background_and_starts_nothing(
        self, workspace: Path, tmp_path: Path, fake_jail: FakeJail
    ) -> None:
        marker = f"bg-docker-{uuid.uuid4().hex[:8]}"
        fake_jail.availability = _ports.SandboxAvailability("docker", True)
        ctx = _context(workspace, tmp_path, sandbox="auto")

        out = _handler("bash")({"command": _sleeper(marker), "background": True}, ctx)

        assert not out.ok and "docker" in out.error
        assert not ctx.processes and _pgrep_count(marker) == 0


def _register_model(server: FakeModel) -> None:
    _catalog.save_provider(
        _catalog.ProviderSpec.model_validate(
            {
                "name": "lab",
                "baseUrl": server.base_url,
                "auth": {"type": "none"},
                "models": [{"id": "m", "contextWindow": 32768}],
            }
        )
    )


class TestTheTurnLeavesNoOrphan:
    def test_a_turn_that_ends_with_a_live_process_stops_it_and_traces_turn_end(
        self,
        fake_model: Callable[..., FakeModel],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        workspace: Path,
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        marker = f"bg-turn-{uuid.uuid4().hex[:8]}"
        seen: dict[str, str] = {}

        def _read_back(request: Request) -> Reply:
            started = request.tool_result("start")
            assert started is not None
            seen["pgid"] = _STARTED.search(started).group(1)  # type: ignore[union-attr]
            return call("process_output", call_id="read", pgid=int(seen["pgid"]))

        def _finish(request: Request) -> Reply:
            seen["output"] = request.tool_result("read") or ""
            return say("done")

        server = fake_model(
            sequence=[
                call("bash", call_id="start", command=_sleeper(marker), background=True),
                _read_back,
                _finish,
            ]
        )
        _register_model(server)
        _write_meta("bg-agent", role="implementer", model="lab/m", codebase=str(workspace))

        result = DocketDriver().run_turn(
            "bg-agent",
            "agent:bg-agent:default",
            "start it",
            60,
            {"DOCKET_SCRATCH_DIR": str(tmp_path / "scratch")},
        )

        assert result.ok, result.error
        assert "alive: true" in seen["output"]
        pgid = int(seen["pgid"])
        assert not _alive(pgid) and _pgrep_count(marker) == 0
        events = [e for e in trace_events("bg-agent") if e["event_type"].startswith("process_")]
        assert [e["event_type"] for e in events] == ["process_started", "process_exited"]
        assert events[0]["payload"]["background"] is True
        assert events[1]["payload"] == {
            "pgid": pgid,
            "signal": "SIGKILL",
            "reason": "turn_end",
            "tool": "bash",
        }


class TestEveryRoleGetsALogDirectory:
    def test_an_unjailed_tester_with_no_scratch_dir_starts_a_process_and_reads_it_back(
        self,
        fake_model: Callable[..., FakeModel],
        monkeypatch: pytest.MonkeyPatch,
        workspace: Path,
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        seen: dict[str, str] = {}

        def _read_back(request: Request) -> Reply:
            seen["started"] = request.tool_result("start") or ""
            found = _STARTED.search(seen["started"])
            if found is None:
                return say("refused")
            deadline = time.monotonic() + 5
            while "done" not in Path(found.group(2)).read_text() and time.monotonic() < deadline:
                time.sleep(0.05)
            return call("process_output", call_id="read", pgid=int(found.group(1)))

        def _finish(request: Request) -> Reply:
            seen["output"] = request.tool_result("read") or ""
            return say("done")

        server = fake_model(
            sequence=[
                call(
                    "bash",
                    call_id="start",
                    command="python3 -c \"import time; time.sleep(1); print('done')\"",
                    background=True,
                ),
                _read_back,
                _finish,
            ]
        )
        _register_model(server)
        _write_meta("bg-tester", role="tester", model="lab/m", codebase=str(workspace))

        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            result = DocketDriver().run_turn(
                "bg-tester", "agent:bg-tester:default", "start it", 60, {}
            )

        assert result.ok, result.error
        found = _STARTED.search(seen["started"])
        assert found is not None, seen["started"]
        assert Path(found.group(2)).parent == current_home().process_logs_dir("bg-tester")
        assert "done" in seen["output"]
