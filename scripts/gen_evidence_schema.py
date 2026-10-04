#!/usr/bin/env python3
"""gen_evidence_schema.py -- render the evidence-v1 contract's schema.json.

``core.evidence``'s Pydantic models are the source of truth; this script only serializes
them, so `--check` failing means the wire shape moved without regenerating the published
artifact in the same change.

Usage:
  ./scripts/gen_evidence_schema.py            # regenerate docs/contracts/evidence-v1/schema.json
  ./scripts/gen_evidence_schema.py --check    # exit 1 if the file on disk is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "docs" / "contracts" / "evidence-v1" / "schema.json"

sys.path.insert(0, str(ROOT / "src"))


def render() -> str:
    """Return the generated schema.json content, trailing newline included."""
    from docket.core import evidence

    document = evidence.TaskEvidence.model_json_schema(by_alias=True)
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "docket evidence contract",
        "version": evidence.EVIDENCE_CONTRACT_VERSION,
        **document,
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rendered = render()
    rel = SCHEMA_PATH.relative_to(ROOT)
    if "--check" in argv:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else None
        if current == rendered:
            print(f"gen_evidence_schema: {rel} is up to date.")
            return 0
        print(
            f"gen_evidence_schema: {rel} is STALE -- "
            "run `uv run python scripts/gen_evidence_schema.py` to regenerate.",
            file=sys.stderr,
        )
        return 1
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(rendered, encoding="utf-8")
    print(f"gen_evidence_schema: wrote {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
