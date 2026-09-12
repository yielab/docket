"""Guard: comment/docstring archaeology and docstring-length counts never rise.

scripts/maint/comment_lint.py finds provenance narration (card ids, phase numbers, dates,
and retrospective "did X" phrasing) in comments and docstrings, plus docstrings over the
length budget. comment-baseline.json records the count reached per kind; a later change may
only lower it, never raise it, so removed drift cannot silently return.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "comment_lint.py"
BASELINE_FILE = REPO / "scripts" / "maint" / "comment-baseline.json"
_SCAN_ROOTS = ("src", "tests")
_MODULE_MAX = 12
_DEF_MAX = 3


def _load_comment_lint_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_comment_lint_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_LINT = _load_comment_lint_module()
_BASELINE: dict[str, int] = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


def _counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for root in _SCAN_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            for finding in _LINT.scan_file(path, _MODULE_MAX, _DEF_MAX):
                counts[finding.kind] = counts.get(finding.kind, 0) + 1
    return counts


def test_counts_do_not_exceed_baseline() -> None:
    counts = _counts()
    regressions = {
        kind: {"now": counts.get(kind, 0), "baseline": limit}
        for kind, limit in _BASELINE.items()
        if counts.get(kind, 0) > limit
    }
    assert not regressions, f"comment hygiene regressed above baseline: {regressions}"
