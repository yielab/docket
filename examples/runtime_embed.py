"""Minimal external consumer of the public ``docket_runtime`` facade."""

from __future__ import annotations

import json
import os
from pathlib import Path

from docket_runtime import Runtime, Tool, ToolCall, ToolContext, ToolOutcome


def main() -> None:
    home = Path(os.environ["DOCKET_HOME"])
    policies = home / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "embedding-approval.json").write_text(
        json.dumps(
            {
                "id": "approve-embedded-tool",
                "applies_to": ["*"],
                "hook": "pre_tool_call",
                "match": {"type": "regex", "pattern": "embedded_echo"},
                "action": "require_approval",
                "message": "embedding host approval",
            }
        ),
        encoding="utf-8",
    )

    runtime = Runtime(approval_stub=lambda token: token.startswith("apr-"))
    runtime.register(
        Tool(
            "embedded_echo",
            "Return one bounded value from the embedding host.",
            {"type": "object"},
            lambda arguments, context: ToolOutcome(True, "governed"),
        )
    )
    result = runtime.dispatch(
        ToolCall("example-call", "embedded_echo", "{}"),
        ToolContext(agent_id="embedded-host", project="runtime-example"),
    )
    if not result.ok or result.content != "governed":
        raise RuntimeError(f"governed dispatch failed: {result.denial_kind or result.content}")
    print("RUNTIME EMBED PASS")


if __name__ == "__main__":
    main()
