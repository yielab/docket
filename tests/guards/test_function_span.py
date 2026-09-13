"""Ratchet: no function under src/docket grows past 150 lines, and the listed ones only shrink.

``scripts/maint/measure_function_spans.py`` measures every function's span, nested closures
included, because a closure-heavy function is still read as one unit. ``function_span_baseline.txt``
records each function currently over the ceiling with its span; a listed function may not grow and
an unlisted one may not appear. Splitting a function into named phases is what earns a lower entry,
in the same commit as the split, via ``--write``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "measure_function_spans.py"


def _load_measure_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_measure_function_spans_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MEASURE = _load_measure_module()


def test_no_function_exceeds_its_baseline_span() -> None:
    hits = _MEASURE.find_long_functions()
    bad = _MEASURE.regressions(hits, _MEASURE.read_baseline())
    assert not bad, "function span ratchet regressed:\n" + "\n".join(bad)
