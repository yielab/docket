"""Test-side role overlays: write a pod's ``roles.json`` without going through ``docket pod``."""

from __future__ import annotations

import json
from pathlib import Path


def write_vetter_overlay(path: Path, denied_tools: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "roles": {
                    "vetter": {
                        "name": "vetter",
                        "version": 1,
                        "scope": "pod",
                        "modelClass": "cheap",
                        "soulTemplate": "x",
                        "agentsTemplate": "y",
                        "gateContract": {"kind": "none"},
                        "toolProfile": "read-only",
                        "deniedTools": denied_tools,
                    }
                }
            }
        )
    )
