"""Guard: every tests/agent file declares its lane headers; unit/ stays subprocess-free.

A file under tests/agent/ that reads prose or builds an artifact must name the defect it
guards (REASON) and the condition that retires it (RETIRE_WHEN), per the lane contract.
A file under tests/unit/ must never import subprocess -- CLI behaviour there is exercised
in-process; a real process boundary belongs to tests/integration/.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO / "tests" / "agent"
UNIT_DIR = REPO / "tests" / "unit"
_REQUIRED_HEADERS = ("LANE", "REASON", "RETIRE_WHEN")


def _module_constant_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_every_agent_file_declares_lane_headers() -> None:
    problems = []
    for path in sorted(AGENT_DIR.rglob("test_*.py")):
        declared = _module_constant_names(path)
        missing = [h for h in _REQUIRED_HEADERS if h not in declared]
        if missing:
            problems.append(f"{path}: missing {missing}")
    assert not problems, "\n".join(problems)


def _imports_subprocess(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            return True
    return False


def test_unit_lane_never_imports_subprocess() -> None:
    offenders = [str(p) for p in sorted(UNIT_DIR.rglob("*.py")) if _imports_subprocess(p)]
    assert not offenders, f"subprocess imported under tests/unit/: {offenders}"
