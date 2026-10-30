"""Drive one ``DocketDriver`` turn of ``impl-1`` with a scripted model, and read what it left."""

from __future__ import annotations

from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home
from tests.support.llm import RecordingScriptedBackend


def run_turn(
    backend: RecordingScriptedBackend, env: dict[str, str] | None = None, **kwargs: str
) -> None:
    """Run the turn and assert it succeeded; *kwargs* are ``run_turn``'s trace coordinates."""
    res = DocketDriver(backend_factory=lambda model: backend).run_turn(
        "impl-1", "agent:impl-1:default", "go", 60, env, **kwargs
    )
    assert res.ok, res.error


def tool_replies(backend: RecordingScriptedBackend) -> list[str]:
    """The tool results the model was shown, in order."""
    return [m.content for call in backend.calls[1:] for m in call if m.role == "tool"]


def trace_text() -> str:
    """Every trace line the home holds, as one text."""
    return "\n".join(
        p.read_text(errors="replace") for p in current_home().traces_dir.rglob("*.jsonl")
    )
