"""CH-4 guard: core/ must never import ``subprocess`` (or os.system/os.popen).

The layering rule (CLAUDE.md) is that ``core/`` is pure domain logic and ``edges/``
is the only side-effecting layer — every shell-out goes through ``edges/adapters/``.
``core/dispatch.py`` in particular *orchestrates* agent turns but delegates the
actual process execution to the ACL (``_oc.agent_run``) and the system adapter
(``_sys.run_verify_cmd``). A 2026-07-20 design-pattern audit wrongly claimed dispatch
ran subprocesses itself; this test locks in the real invariant so that concern can
never become true by regression. (Sibling of ``test_ch3_no_ui_in_core_edges.py``.)
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent


def _python_files(subdir: str) -> list[Path]:
    return sorted((_SRC_ROOT / subdir).rglob("*.py"))


def _shells_out(path: Path) -> bool:
    """True if *path* imports ``subprocess`` or references os.system/os.popen/os.exec*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "subprocess" or alias.name.startswith("subprocess.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                return True
        elif isinstance(node, ast.Attribute) and (
            isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and (node.attr in ("system", "popen") or node.attr.startswith("exec"))
        ):
            # os.system(...) / os.popen(...) / os.execv(...) etc.
            return True
    return False


def test_core_never_shells_out() -> None:
    offenders = [str(p) for p in _python_files("core") if _shells_out(p)]
    assert not offenders, (
        "core/ must be process-free — delegate execution to edges/adapters "
        f"(_oc.agent_run / _sys.*): {offenders}"
    )
