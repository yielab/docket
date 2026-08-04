"""Guard: no `contextlib.suppress(Exception)` wraps a dispatch call.

``serve.py`` used to have four places where a pod-dispatch call was
wrapped in a bare ``with contextlib.suppress(Exception):`` — the webhook
handler, the schedule-triggered dispatch, and two blocks in the sweep loop
(driving every pod's queue, and the schedule check that triggers dispatch in
turn). Every one of those discarded the exception with no id, no record, no
trace of what happened.

This is a "grep-pinned" regression test (sibling in
spirit to ``test_no_subprocess_in_core.py``'s AST-based guard): it scans
``serve.py`` for every ``with contextlib.suppress(Exception):`` block and
fails if any of them still mentions dispatch in its body. ``trace.sweep_all()``
and ``approval.approval_sweep_expired()`` are unrelated sweeps and are
intentionally left alone — this guard is scoped to banning suppression
around dispatch specifically.
"""

from __future__ import annotations

import re
from pathlib import Path

import docket.serve as serve

_SERVE_PY = Path(serve.__file__)

_SUPPRESS_LINE_RE = re.compile(r"^(\s*)with\s+contextlib\.suppress\(Exception\)\s*:\s*$")


def _suppress_exception_blocks(text: str) -> list[str]:
    """Return the indented body text of every top-level suppress(Exception) block."""
    lines = text.splitlines()
    blocks: list[str] = []
    for i, line in enumerate(lines):
        m = _SUPPRESS_LINE_RE.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        body_lines: list[str] = []
        for follow in lines[i + 1 :]:
            if follow.strip() == "":
                body_lines.append(follow)
                continue
            follow_indent = len(follow) - len(follow.lstrip(" "))
            if follow_indent <= indent:
                break
            body_lines.append(follow)
        blocks.append("\n".join(body_lines))
    return blocks


def test_serve_py_still_uses_suppress_for_unrelated_sweeps() -> None:
    """Sanity check the test helper itself against a known-good line (trace/approval
    sweeps stay suppressed — they are out of this card's scope)."""
    text = _SERVE_PY.read_text(encoding="utf-8")
    assert "with contextlib.suppress(Exception):" in text, (
        "expected the trace/approval sweep guards to remain — if they were removed "
        "entirely this test's premise (scoped exclusion) no longer applies"
    )


def test_no_suppress_exception_block_mentions_dispatch() -> None:
    text = _SERVE_PY.read_text(encoding="utf-8")
    offenders = [
        block for block in _suppress_exception_blocks(text) if re.search(r"dispatch", block, re.I)
    ]
    assert not offenders, (
        "serve.py must not silently discard a dispatch exception via "
        "contextlib.suppress(Exception) -- every dispatch call site must record "
        "its outcome in the run registry (core.runs) instead. Offending "
        "block(s):\n" + "\n---\n".join(offenders)
    )


def test_webhook_dispatch_call_site_uses_run_registry() -> None:
    text = _SERVE_PY.read_text(encoding="utf-8")
    assert "from docket.core import runs as _runs" in text, (
        "serve.py's dispatch call sites (webhook/schedule/sweep) must go "
        "through core.runs so every attempt is queryable"
    )


def test_dispatch_all_pods_no_longer_called_unguarded_in_serve() -> None:
    """The sweep loop used to call dispatch_all_pods() inside a bare suppress,
    losing per-pod granularity. That is replaced with one run record per pod
    (dispatchable_pods() + dispatch_pod() through core.runs.execute)."""
    text = _SERVE_PY.read_text(encoding="utf-8")
    assert "dispatch_all_pods" not in text
    assert "dispatchable_pods" in text
