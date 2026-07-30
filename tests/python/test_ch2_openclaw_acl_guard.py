"""CH-2 guard: `openclaw` binary shell-outs must live behind the ACL.

Knowing the `openclaw` CLI's command grammar (`agents add`, `models auth
setup-token`, …) outside `edges/adapters/openclaw.py` IS the OpenClaw coupling
the ACL exists to hold (ROADMAP §3, TODO.md CH-2). This scans every non-`edges/`
`.py` file under `src/docket` for a subprocess call whose argv opens with the
literal `"openclaw"` and fails, listing offenders. It also asserts `core/` has
zero `subprocess` imports at all (ROADMAP §3: "core has no subprocess") — the
worst offender this card fixed (`core/utils.py:47`) was exactly that.

Phase 18 L-1 (D-14) extends this guard to a second CH-2-shaped leak the same
audit found: daemon *session-JSONL* format knowledge (the on-disk record shape
under ``agents/<id>/sessions/*.jsonl``) had escaped the ACL into
``core/utils.py``'s cost aggregation and ``core/trace.py``'s ``trace_ingest``.
That parsing now lives in ``edges/adapters/openclaw.py``'s ``OpenClawDriver``
(the one shipped ``RuntimeDriver``, see ``core/runtime_driver.py``) —
``test_core_has_no_session_format_knowledge`` fails if it ever regresses back
into ``core/``. Scoped to ``core/`` specifically (not the whole non-edges
tree): unlike the subprocess-argv check above, `cli/`'s own pre-existing,
separately-tracked touches of the daemon's session directory (`docket
maintain sessions`, `docket agents` context stats) are a different, wider
cleanup this card does not attempt — see the L-1 report for that residual gap.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"

# subprocess.run(/.Popen(/... immediately followed (modulo whitespace/newlines —
# real call sites format argv one item per line) by a literal ["openclaw" list.
_OPENCLAW_SUBPROCESS_RE = re.compile(
    r'(?:subprocess|_sp|_sub)\.(?:run|Popen|check_call|check_output)\(\s*\[\s*"openclaw"'
)

_SUBPROCESS_IMPORT_RE = re.compile(
    r"^\s*(?:import subprocess\b|from subprocess import\b)", re.MULTILINE
)

# Phase 18 L-1: two independent, low-false-positive fingerprints of "this code
# parses (or locates) the daemon's session-JSONL record shape" — either one
# regressing into core/ is exactly the leak this guard exists to catch.
#
# 1. Building the daemon's session-log directory path (OPENCLAW_DIR/agents/
#    <id>/sessions/*.jsonl) — the exact Path expression both former leaks used
#    (``_cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"``).
_SESSION_DIR_RE = re.compile(r'"agents"\s*/[^\n]{0,60}?/\s*"sessions"')

# 2. Pulling the daemon's usage/cost sub-record fields out of a parsed JSONL
#    line — real dict `.get(...)` call syntax, not prose, so a docstring that
#    merely *mentions* these key names in passing cannot trip it.
_USAGE_FIELD_RE = re.compile(r'\.get\(\s*"(?:cacheRead|cacheWrite|usage)"\s*,')


def _py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_no_openclaw_subprocess_outside_edges() -> None:
    offenders: list[str] = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC)
        if rel.parts[0] == "edges":
            continue  # edges/adapters/{openclaw,system}.py is the ACL boundary
        text = path.read_text(encoding="utf-8")
        if _OPENCLAW_SUBPROCESS_RE.search(text):
            offenders.append(str(rel))
    assert not offenders, (
        "raw `openclaw` subprocess calls found outside edges/ (ACL boundary): "
        + ", ".join(offenders)
        + " — add/extend a typed wrapper in edges/adapters/openclaw.py instead (CH-2)."
    )


def test_core_has_no_subprocess_imports() -> None:
    offenders: list[str] = []
    for path in _py_files(SRC / "core"):
        text = path.read_text(encoding="utf-8")
        if _SUBPROCESS_IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(SRC)))
    assert not offenders, (
        "core/ must not import subprocess (ROADMAP §3 — 'core has no subprocess'; "
        "all shelling-out belongs behind edges/adapters/): " + ", ".join(offenders)
    )


def test_core_has_no_session_format_knowledge() -> None:
    """Phase 18 L-1: core/ must never parse or locate daemon session JSONL.

    This is the regression guard for the RuntimeDriver port (D-14): both
    ``core/utils.py``'s former ``aggregate_cost``/``cost_history`` and
    ``core/trace.py``'s former ``trace_ingest`` inner loop are exactly what
    this fails on — restore either one's session-directory Path expression or
    its ``usage``/``cacheRead``/``cacheWrite`` field extraction to any file
    under ``core/`` and this test catches it immediately.
    """
    offenders: list[str] = []
    for path in _py_files(SRC / "core"):
        text = path.read_text(encoding="utf-8")
        if _SESSION_DIR_RE.search(text) or _USAGE_FIELD_RE.search(text):
            offenders.append(str(path.relative_to(SRC)))
    assert not offenders, (
        "daemon session-JSONL format knowledge found in core/ (ACL boundary — "
        "Phase 18 L-1 / D-14): " + ", ".join(offenders) + " — session parsing "
        "belongs on edges.adapters.openclaw.OpenClawDriver "
        "(core.runtime_driver.RuntimeDriver), not in core/."
    )
