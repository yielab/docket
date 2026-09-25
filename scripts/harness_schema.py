#!/usr/bin/env python3
"""harness_schema.py -- render docs/contracts/harness-v1/schema.json from the Pydantic models.

``core.harness.HarnessEvent``/``HarnessResult`` are the source of truth; this
script only serializes them. An outside consumer pins its own types against
the committed file, so `--check` failing means the wire shape moved without
regenerating the published artifact in the same change.

Usage:
  ./scripts/harness_schema.py            # regenerate schema.json
  ./scripts/harness_schema.py --check    # exit 1 if the file on disk is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCHEMA_PATH = ROOT / "docs" / "contracts" / "harness-v1" / "schema.json"

sys.path.insert(0, str(SRC))


# model_json_schema() writes refs as "#/$defs/X", which resolve against the *document*
# root -- not against the "definitions.<Model>" object they were nested under. Nesting them
# there is why a standard validator raised PointerToNowhere against the published file even
# though pydantic's own validation never looks at it. Hoisting satisfies the refs as written.
def _hoist_defs(definitions: dict[str, object]) -> dict[str, object]:
    """Pull every model's nested ``$defs`` up to one root ``$defs``."""
    root_defs: dict[str, object] = {}
    for model_name, schema in definitions.items():
        nested = schema.pop("$defs", None)  # type: ignore[union-attr]
        if not nested:
            continue
        for def_name, def_body in nested.items():
            if def_name in root_defs and root_defs[def_name] != def_body:
                raise ValueError(
                    f"harness_schema: '{def_name}' from {model_name} collides with an "
                    "earlier definition of the same name but a different body"
                )
            root_defs[def_name] = def_body
    return root_defs


def render() -> str:
    """Return the generated schema.json content, trailing newline included."""
    from docket.core import harness

    definitions = {
        "HarnessEvent": harness.HarnessEvent.model_json_schema(),
        "HarnessResult": harness.HarnessResult.model_json_schema(),
    }
    root_defs = _hoist_defs(definitions)

    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "docket harness contract",
        "version": harness.HARNESS_CONTRACT_VERSION,
        "definitions": definitions,
    }
    if root_defs:
        document["$defs"] = root_defs
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    rendered = render()

    if check_only:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else None
        if current == rendered:
            print(f"harness_schema: {SCHEMA_PATH.relative_to(ROOT)} is up to date.")
            return 0
        print(
            f"harness_schema: {SCHEMA_PATH.relative_to(ROOT)} is STALE -- "
            "run `uv run python scripts/harness_schema.py` to regenerate.",
            file=sys.stderr,
        )
        return 1

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(rendered, encoding="utf-8")
    print(f"harness_schema: wrote {SCHEMA_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
