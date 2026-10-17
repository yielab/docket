#!/usr/bin/env python3
"""Move the loopback OpenAI-compatible stub out of ``tests/integration/test_harness_cli.py``
into ``tests/integration/llm_stub.py`` (helpers + the ``llm_server`` fixture) and register the
fixture in ``tests/integration/conftest.py``; importers are repointed. Idempotent: a second run
finds the marker gone and exits 0."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "tests" / "integration" / "test_harness_cli.py"
STUB = REPO / "tests" / "integration" / "llm_stub.py"
CONFTEST = REPO / "tests" / "integration" / "conftest.py"

BEGIN = "# ── loopback OpenAI-compatible stub"
END = "# ── subprocess plumbing"
MOVED = ("_ScriptedLLMServer", "_final_response", "_tool_call_response")

STUB_HEADER = '''"""A loopback OpenAI-compatible stub for integration tests: scripted chat-completion bodies,
one per POST, plus the ``llm_server`` fixture that starts and stops them."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

'''

CONFTEST_BODY = '''"""Fixtures shared by every integration test."""

from tests.integration.llm_stub import llm_server

__all__ = ["llm_server"]
'''


def _split(text: str) -> tuple[str, str, str]:
    start = text.index(BEGIN)
    stop = text.index(END)
    return text[:start], text[start:stop], text[stop:]


def _repoint(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"from tests\.integration\.test_harness_cli import \(\n(?P<names>(?:    .*\n)+?)\)\n"
        r"|from tests\.integration\.test_harness_cli import (?P<inline>[^\n(]+)\n"
    )
    match = pattern.search(text)
    if match is None:
        return False
    raw = match.group("names") or match.group("inline")
    entries = [e.strip() for e in (raw.splitlines() if match.group("names") else raw.split(","))]
    keep: list[str] = []
    moved: list[str] = []
    for entry in entries:
        bare = entry.split("#", 1)[0].strip().rstrip(",").strip()
        if not bare or bare == "llm_server":
            continue
        (moved if bare in MOVED else keep).append(entry.rstrip(",") if "#" not in entry else entry)
    lines: list[str] = []
    if keep:
        lines.append("from tests.integration.test_harness_cli import (\n")
        for entry in keep:
            name, _, comment = entry.partition("#")
            name = name.strip().rstrip(",")
            lines.append(f"    {name},  #{comment}\n" if comment else f"    {name},\n")
        lines.append(")\n")
    if moved:
        names = sorted(m.split("#", 1)[0].strip().rstrip(",") for m in moved)
        lines.append(f"from tests.integration.llm_stub import {', '.join(names)}\n")
    text = text[: match.start()] + "".join(lines) + text[match.end() :]
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    if BEGIN not in source:
        print("already moved")
        return 0
    head, block, tail = _split(source)
    body = block.split("\n", 1)[1].lstrip("\n")
    STUB.write_text(STUB_HEADER + "\n" + body.rstrip("\n") + "\n", encoding="utf-8")
    CONFTEST.write_text(CONFTEST_BODY, encoding="utf-8")
    import_line = (
        "from tests.integration.llm_stub import (  # noqa: F401 - re-exported for the harness tests\n"
        "    _final_response,\n    _ScriptedLLMServer,\n    _tool_call_response,\n)\n"
    )
    head = head.replace(
        "from tests.conftest import record_isolation_off, record_isolation_on\n",
        "from tests.conftest import record_isolation_off, record_isolation_on\n" + import_line,
    )
    SOURCE.write_text(head + tail, encoding="utf-8")
    repointed = [
        str(p.relative_to(REPO))
        for p in sorted((REPO / "tests" / "integration").glob("test_*.py"))
        if p != SOURCE and _repoint(p)
    ]
    print("wrote", STUB.relative_to(REPO), CONFTEST.relative_to(REPO))
    print("repointed", *repointed, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
