#!/usr/bin/env python3
"""gen_evidence_schema.py -- render the evidence contract's schema.json (1.1.0).

``core.evidence``'s Pydantic models are the source of truth; this script only serializes
them, so `--check` failing means the wire shape moved without regenerating the published
artifact in the same change.

Usage:
  ./scripts/gen_evidence_schema.py            # regenerate docs/contracts/evidence-v1*/schema.json
  ./scripts/gen_evidence_schema.py --check    # exit 1 if the file on disk is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "docs" / "contracts"
SCHEMA_PATHS = {
    "1.1.0": CONTRACTS / "evidence-v1.1" / "schema.json",
}

sys.path.insert(0, str(ROOT / "src"))


def render(version: str) -> str:
    """Return the generated schema.json content for *version*, trailing newline included."""
    from docket.core import evidence

    model = evidence.TaskEvidence11
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "docket evidence contract",
        "version": version,
        **model.model_json_schema(by_alias=True),
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stale = False
    for version, path in SCHEMA_PATHS.items():
        rendered = render(version)
        rel = path.relative_to(ROOT)
        if "--check" in argv:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current == rendered:
                print(f"gen_evidence_schema: {rel} is up to date.")
                continue
            print(
                f"gen_evidence_schema: {rel} is STALE -- "
                "run `uv run python scripts/gen_evidence_schema.py` to regenerate.",
                file=sys.stderr,
            )
            stale = True
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"gen_evidence_schema: wrote {rel}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
