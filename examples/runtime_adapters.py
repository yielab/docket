"""Compact index and lazy constructors for artifact-tested runtime adapters.

Run ``python examples/runtime_adapters.py --truth-json`` to inspect the exact
support boundary without installing either optional framework dependency.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docket_runtime import ExecutionLimits, Runtime, ToolContext
    from docket_runtime.adapters.openhands import OpenHandsAdapter
    from docket_runtime.adapters.pydantic_ai import DocketToolset


SUPPORT_TRUTH = {
    "tested_configurations": [
        {
            "adapter": "OpenHands SDK",
            "package": "openhands-sdk",
            "version": "1.44.1",
            "python": "3.12",
        },
        {
            "adapter": "PydanticAI",
            "package": "pydantic-ai",
            "version": "2.37.0",
            "python": "3.11",
        },
    ],
    "governance_boundary": "relevant tools exclusively Docket-backed",
    "outside_proof": [
        "ACP",
        "native/provider tools",
        "plugins/MCP",
        "arbitrary framework configurations",
    ],
    "transport": {
        "a2a_used": False,
        "otlp_used": False,
        "trace": "JSONL preserves project, session, role, call, and decision identity",
    },
}


def build_openhands_adapter(
    *, runtime: Runtime, context: ToolContext, limits: ExecutionLimits
) -> OpenHandsAdapter:
    """Create the tested OpenHands adapter; import its optional SDK lazily."""
    from docket_runtime.adapters.openhands import OpenHandsAdapter

    return OpenHandsAdapter(runtime=runtime, context=context, limits=limits)


def build_pydantic_ai_toolset(
    *, runtime: Runtime, context: ToolContext, limits: ExecutionLimits
) -> DocketToolset:
    """Create the tested PydanticAI toolset; import its optional SDK lazily."""
    from docket_runtime.adapters.pydantic_ai import DocketToolset

    return DocketToolset(runtime=runtime, context=context, limits=limits)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--truth-json",
        action="store_true",
        help="print the exact tested configurations and non-goals as JSON",
    )
    args = parser.parse_args(argv)
    if args.truth_json:
        print(json.dumps(SUPPORT_TRUTH, sort_keys=True))
        return 0

    print("Artifact-tested docket-runtime adapters:")
    for configuration in SUPPORT_TRUTH["tested_configurations"]:
        print(
            f"- {configuration['adapter']}: {configuration['package']}=="
            f"{configuration['version']} on Python {configuration['python']}"
        )
    print(f"Boundary: {SUPPORT_TRUTH['governance_boundary']}")
    print("Use --truth-json for explicit exclusions and transport evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
