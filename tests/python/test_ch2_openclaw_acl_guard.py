"""CH-2 guard: `openclaw` binary shell-outs must live behind the ACL.

Knowing the `openclaw` CLI's command grammar (`agents add`, `models auth
setup-token`, …) outside `edges/adapters/openclaw.py` IS the OpenClaw coupling
the ACL exists to hold (ROADMAP §3, TODO.md CH-2). This scans every non-`edges/`
`.py` file under `src/docket` for a subprocess call whose argv opens with the
literal `"openclaw"` and fails, listing offenders. It also asserts `core/` has
zero `subprocess` imports at all (ROADMAP §3: "core has no subprocess") — the
worst offender this card fixed (`core/utils.py:47`) was exactly that.
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
