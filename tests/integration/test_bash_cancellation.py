"""Cancellation reaching an in-flight `bash` command.

An already-running tool handler ordinarily runs to completion once dispatched, because a
Python thread cannot be killed safely; a subprocess can, and `bash` is the one handler where a
separate process's cancellation request reaches into a command already running. Pinned:
`run_bash` notices a cancellation callback mid-command and returns promptly with the process
group actually gone (not just at the tool's own timeout); a real turn dispatching one `bash`
call through `run_agent_turn` stops with `stop_reason="run_cancelled"`, with the assistant call
and its cancelled tool result persisted as one atomic session unit and the backend called
exactly once; with no callback, timeout behaviour -- including the exact message -- is
untouched byte for byte; and the same holds under the bwrap sandbox backend, when available.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from docket.core import agent_loop as _loop
from docket.core.llm import ChatResponse, TokenUsage, ToolCall, assistant
from docket.core.session import load_messages
from docket.core.tools import ToolContext, builtin_registry
from docket.edges.adapters import system as _system
from docket.edges.adapters import toolbox

SUBJECT = "docket.edges.adapters.toolbox"

BWRAP_UP = _system.bwrap_available()
needs_bwrap = pytest.mark.skipif(
    not BWRAP_UP, reason="bwrap not installed, or this host disallows unprivileged user namespaces"
)

# A command whose binary (`python3`) is on `SAFE_BINS`, so it reaches
# `run_bash` with a bare "allow" verdict -- these tests are about a signal
# reaching an already-running process, not about the command classifier.
_SLEEP = 'python3 -c "import time; time.sleep({seconds})"'


class _DelayedFlip:
    """A cancellation callback that flips true after a fixed delay, from a
    background timer thread -- mimics a separate CLI process requesting
    cancellation while the tool call is already running."""

    def __init__(self, delay: float) -> None:
        self._event = threading.Event()
        threading.Timer(delay, self._event.set).start()

    def __call__(self) -> bool:
        return self._event.is_set()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def _pgrep_count(marker: str) -> int:
    result = subprocess.run(["pgrep", "-fc", marker], capture_output=True, text=True)
    return int((result.stdout or "0").strip() or "0")


# ── run_bash: signal reaches the in-flight process ──────────────────────────


class TestRunBashCancellation:
    def test_returns_promptly_and_kills_the_process_group(self, workspace: Path) -> None:
        pidfile = workspace / "pid"
        # `exec`s into the sleep rather than forking it, so the shell and the
        # sleeping process are the same pid -- no separate child that could
        # still be an unreaped zombie the instant after the group is killed.
        command = f"echo $$ > {pidfile}; exec {_SLEEP.format(seconds=30)}"
        cancelled = _DelayedFlip(0.2)

        started = time.monotonic()
        out = toolbox.run_bash((workspace,), command, timeout=60, cancelled=cancelled)
        elapsed = time.monotonic() - started

        assert elapsed < 2, f"cancellation was observed after {elapsed:.2f}s, not promptly"
        assert not out.ok
        assert "cancel" in out.error.lower()

        pid = int(pidfile.read_text().strip())
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)

    def test_with_no_callback_the_timeout_path_is_byte_identical(self, workspace: Path) -> None:
        """A caller that never passes `cancelled` sees today's exact behaviour."""
        out = toolbox.run_bash((workspace,), _SLEEP.format(seconds=5), timeout=1, cancelled=None)
        assert not out.ok
        assert out.error == "command timed out after 1s"

    # A callback that is merely present, and never fires, must not change what
    # a command returns -- polling for cancellation must not stop this module
    # from draining output the way `communicate()` always has, or an ordinary
    # verbose command loses its output to a false timeout the moment a caller
    # wires up cancellation at all.
    def test_a_callback_that_never_fires_still_drains_output_over_a_full_pipe(
        self, workspace: Path
    ) -> None:
        """A command writing more than one OS pipe buffer must still complete."""
        command = "python3 -c \"print('x' * 200000)\""
        never_cancelled = lambda: False  # noqa: E731

        baseline_started = time.monotonic()
        baseline = toolbox.run_bash((workspace,), command, timeout=8, cancelled=None)
        baseline_elapsed = time.monotonic() - baseline_started

        started = time.monotonic()
        out = toolbox.run_bash((workspace,), command, timeout=8, cancelled=never_cancelled)
        elapsed = time.monotonic() - started

        assert elapsed < 2, f"took {elapsed:.2f}s (baseline {baseline_elapsed:.2f}s), not promptly"
        assert out.ok
        assert out.content == baseline.content
        assert len(out.content) > 30_000

    @needs_bwrap
    def test_bwrap_variant_leaves_no_orphan(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
        marker = f"w30c1-bwrap-{uuid.uuid4().hex[:8]}"
        cancelled = _DelayedFlip(0.2)

        started = time.monotonic()
        out = toolbox.run_bash(
            (workspace,),
            f"echo {marker}; sleep 30 & sleep 30 & wait",
            timeout=60,
            sandbox="auto",
            cancelled=cancelled,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 2, f"cancellation was observed after {elapsed:.2f}s, not promptly"
        assert not out.ok
        assert "cancel" in out.error.lower()
        time.sleep(1)
        assert _pgrep_count(marker) == 0


# ── a real turn: the amendment reaches dispatch_tool and the loop ──────────


class _OneShotBashBackend:
    """Requests one `bash` call, then a final message it must never reach."""

    def __init__(self, command: str) -> None:
        self._command = command
        self.calls = 0

    def complete(
        self,
        messages: object,
        *,
        tools: object = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        del messages, tools, max_tokens, temperature, timeout
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("the loop must stop on cancellation, not ask for a second turn")
        call = ToolCall(id="bash-1", name="bash", arguments=json.dumps({"command": self._command}))
        return ChatResponse(
            ok=True,
            message=assistant("", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )


class TestAgentTurnBashCancellation:
    def test_a_cancelled_bash_call_stops_the_turn_as_one_atomic_unit(self, workspace: Path) -> None:
        backend = _OneShotBashBackend(_SLEEP.format(seconds=10))
        cancelled = _DelayedFlip(0.2)
        ctx = ToolContext(
            agent_id="demo-agent",
            role="implementer",
            project="demo",
            roots=(workspace,),
            timeout=60,
            cancellation_check=cancelled,
        )
        session_key = "agent:demo-agent:demo"

        started = time.monotonic()
        result = _loop.run_agent_turn(
            backend, builtin_registry(), ctx, session_key, "run the long command"
        )
        elapsed = time.monotonic() - started

        assert elapsed < 3, f"the turn took {elapsed:.2f}s to stop, not promptly"
        assert result.stop_reason == "run_cancelled"
        assert backend.calls == 1

        messages = load_messages(session_key)
        # The user turn, plus exactly one iteration's assistant/tool-result
        # unit -- never a second round trip after the cancelled call.
        assert len(messages) == 3
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        assert messages[2].role == "tool"
        assert "cancel" in messages[2].content.lower()
