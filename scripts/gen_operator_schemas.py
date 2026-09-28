#!/usr/bin/env python3
"""gen_operator_schemas.py -- render docs/contracts/operator-v1/{task,question,answer,approval,
inbox,brief,event}.schema.json from the Pydantic models in ``core.operator_contract``.

``question.schema.json``'s ``requestedSchema`` property is rendered from
``operator_contract.QuestionSchema`` rather than the generic dict the Python field carries,
so the published schema documents the MCP elicitation subset precisely.

Usage:
  ./scripts/gen_operator_schemas.py            # regenerate every schema file
  ./scripts/gen_operator_schemas.py --check    # exit 1 if any file on disk is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DOCS_SCHEMA_DIR = ROOT / "docs" / "contracts" / "operator-v1"

sys.path.insert(0, str(SRC))

_NAME_FOR_MODEL: dict[str, str] = {
    "task": "TaskView",
    "question": "Question",
    "answer": "AnswerResult",
    "approval": "ApprovalView",
    "inbox": "InboxView",
    "brief": "TaskBrief",
    "event": "CloudEvent",
}

KINDS: tuple[str, ...] = tuple(_NAME_FOR_MODEL)


def render(kind: str) -> str:
    """Return the generated ``<kind>.schema.json`` content, trailing newline included."""
    from docket.core import operator_contract

    model = getattr(operator_contract, _NAME_FOR_MODEL[kind])
    schema: dict[str, Any] = model.model_json_schema()
    if kind == "question":
        schema["properties"]["requestedSchema"] = (
            operator_contract.QuestionSchema.model_json_schema()
        )
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://docket.dev/schemas/operator-v1/{kind}.schema.json",
        "title": f"docket operator-v1 {kind}",
        **schema,
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def _target(kind: str) -> Path:
    return DOCS_SCHEMA_DIR / f"{kind}.schema.json"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    stale: list[Path] = []
    for kind in KINDS:
        rendered = render(kind)
        target = _target(kind)
        if check_only:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != rendered:
                stale.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")

    if check_only:
        if stale:
            for target in stale:
                print(
                    f"gen_operator_schemas: {target.relative_to(ROOT)} is STALE -- "
                    "run `uv run python scripts/gen_operator_schemas.py` to regenerate.",
                    file=sys.stderr,
                )
            return 1
        print("gen_operator_schemas: all schema files are up to date.")
        return 0

    print(f"gen_operator_schemas: wrote {len(KINDS)} schema file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
