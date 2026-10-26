"""What a built-in tool returns, shared by the tool set and the platform fetch adapter."""

from __future__ import annotations

from dataclasses import dataclass

from docket.kernel import text as _text
from docket.kernel.home import current_home


@dataclass
class ToolOutcome:
    """What happened when a tool ran. Not whether it was allowed to."""

    ok: bool
    content: str = ""
    error: str = ""
    refusal: str = ""


def text_outcome(text: str) -> ToolOutcome:
    """A successful outcome carrying *text*, bounded like a ``read`` result."""
    return ToolOutcome(True, content=_text.cut_output(text, current_home().tool_max_output_chars))
