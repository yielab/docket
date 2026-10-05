#!/usr/bin/env python3
"""gen_config_schemas.py -- render
docs/contracts/config-v1/{role,pipeline,policy,pod,exporter,channel,mcp-server}.schema.json from the
Pydantic models in ``core.config_docs``.

Four are short-form models used only for schema generation and error refinement; ``ExporterSpec``,
``ChannelSpec`` and ``McpServerDocument`` are different -- each IS the canonical, only-parsed shape of
its own document kind. All seven are also shipped byte-identical inside the installed package.

Usage:
  ./scripts/gen_config_schemas.py            # regenerate every schema file
  ./scripts/gen_config_schemas.py --check    # exit 1 if any file on disk is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DOCS_SCHEMA_DIR = ROOT / "docs" / "contracts" / "config-v1"
PACKAGE_SCHEMA_DIR = SRC / "docket" / "templates" / "schemas"

sys.path.insert(0, str(SRC))

KINDS: tuple[str, ...] = ("role", "pipeline", "policy", "pod", "exporter", "channel", "mcp-server")


def render(kind: str) -> str:
    """Return the generated ``<kind>.schema.json`` content, trailing newline included."""
    from docket.core import config_docs

    model = config_docs._MODEL_FOR_KIND[kind]
    schema = model.model_json_schema()
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://docket.dev/schemas/config-v1/{kind}.schema.json",
        "title": f"docket {kind} configuration document",
        **schema,
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def _targets(kind: str) -> tuple[Path, Path]:
    return (DOCS_SCHEMA_DIR / f"{kind}.schema.json", PACKAGE_SCHEMA_DIR / f"{kind}.schema.json")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    stale: list[Path] = []
    for kind in KINDS:
        rendered = render(kind)
        for target in _targets(kind):
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
                    f"gen_config_schemas: {target.relative_to(ROOT)} is STALE -- "
                    "run `uv run python scripts/gen_config_schemas.py` to regenerate.",
                    file=sys.stderr,
                )
            return 1
        print("gen_config_schemas: all schema files are up to date.")
        return 0

    print(f"gen_config_schemas: wrote {len(KINDS) * 2} schema file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
