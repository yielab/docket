"""A tool result over the output cap is kept whole as an artifact the model can read back."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

from tests.support.driver_harness import _final_response, _ScriptedBackend
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.trace import trace_events

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import artifact_path_in

SUBJECT = "docket.agent.tools.registry"

_POD = "solo-agent"
_ROWS = 4000


def _call(call_id: str, name: str, arguments: dict[str, object]) -> ChatResponse:
    call = ToolCall(id=call_id, name=name, arguments=json.dumps(arguments))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


class _ReadsItsOwnArtifact(_ScriptedBackend):
    """Runs `cat big.txt`, then reads the artifact named in the result at line 2400."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        results = [m for m in messages if m.role == "tool"]
        if not results:
            return _call("b1", "bash", {"command": "cat big.txt"})
        if len(results) == 1:
            path = artifact_path_in(results[0].content) or "no-artifact"
            return _call("r1", "read", {"path": path, "offset": 2400, "limit": 50})
        return _final_response("done")


def _run(tmp_path: Path) -> tuple[_ReadsItsOwnArtifact, str]:
    rows = [f"row {n:05d} " + "x" * 12 for n in range(1, _ROWS + 1)]
    whole = "\n".join(rows)
    (tmp_path / "big.txt").write_text(whole + "\n")
    (current_home().pods_dir / _POD).mkdir(parents=True)
    _write_meta(_POD, role="implementer", codebase=str(tmp_path))
    backend = _ReadsItsOwnArtifact([])
    driver = DocketDriver(backend_factory=lambda model: backend)

    with use_home(dataclasses.replace(current_home(), tool_max_output_chars=2500)):
        result = driver.run_turn(_POD, f"agent:{_POD}:default", "go", 30, {})

    assert result.ok is True, result.error
    return backend, whole


def test_a_bash_result_over_the_cap_ends_with_its_artifact_and_the_file_holds_it_all(
    tmp_path: Path,
) -> None:
    backend, whole = _run(tmp_path)

    first = next(m for m in backend.calls[1] if m.role == "tool").content
    path = artifact_path_in(first)
    assert path is not None
    assert first.endswith(f"[full output: {path} — read it with read(path, offset, limit)]")
    assert "[truncated:" in first
    assert Path(path).read_text() == whole
    assert Path(path).parent == current_home().pod_cache_dir(_POD) / "artifacts"
    assert first.index("row 00001") < first.index("[truncated:") < first.index("row 04000")


def test_read_returns_the_lines_past_the_cut_from_the_artifact(tmp_path: Path) -> None:
    backend, _ = _run(tmp_path)

    window = [m for m in backend.calls[2] if m.role == "tool"][1].content
    lines = window.splitlines()
    assert lines[0] == "2400\trow 02400 xxxxxxxxxxxx"
    assert lines[49] == "2449\trow 02449 xxxxxxxxxxxx"


def test_the_trace_records_the_artifact_path_on_the_tool_result(tmp_path: Path) -> None:
    backend, _ = _run(tmp_path)

    first = next(m for m in backend.calls[1] if m.role == "tool").content
    results = [e for e in trace_events(_POD) if e["event_type"] == "tool_result"]
    assert results[0]["payload"]["artifact"] == artifact_path_in(first)
    assert "artifact" not in results[1]["payload"]
