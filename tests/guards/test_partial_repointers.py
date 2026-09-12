"""Ratchet: functions that hand-roll a partial DOCKET_HOME copy may never grow.

``test_docket_home_repointer.py`` catches a function that sets ``_cfg.DOCKET_HOME``
directly without calling the shared ``repoint_docket_home`` helper. It does not catch
a function that repoints two or more of the *other* tracked constants and never claims
a home at all -- each such function overrides a named constant deliberately, and the
autouse isolation fixture still covers everything it leaves alone, so none of them can
reach the real ``~/.docket``. The risk is cumulative rather than binary: a threshold, not
a boolean. ``partial_repointer_baseline.txt`` records where that count stands and may
only be lowered -- converting a function to ``repoint_docket_home`` is what earns the
lower number, in the same commit that removes the hand-rolled copy.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "measure_partial_repointers.py"
BASELINE_FILE = Path(__file__).parent / "partial_repointer_baseline.txt"


def _load_measure_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_measure_partial_repointers_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MEASURE = _load_measure_module()


def test_partial_repointer_count_does_not_exceed_baseline() -> None:
    baseline = int(BASELINE_FILE.read_text(encoding="utf-8").strip())
    hits = _MEASURE.find_partial_repointers()
    assert len(hits) <= baseline, (
        f"partial repointers grew to {len(hits)}, above committed baseline {baseline}: "
        f"{[(rel, name, lineno) for rel, name, lineno, _ in hits]}"
    )
