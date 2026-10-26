"""Guard: only the adapter layers import ``subprocess`` (or os.system/os.popen).

The layering rule is that the contexts' domain and application code is pure logic and the
side-effecting layers -- ``platform/``, ``sandbox/``, every ``adapters/`` package, the built-in
tool handlers in ``agent/tools/builtins/`` and ``interfaces/`` -- are the only places a process
is started. Dispatch (``tasks/application/``) *orchestrates* agent turns but delegates the
actual process execution to a driver (``hops/application/driver.py``'s ``DocketDriver``, which itself
never shells out -- it makes in-process HTTP calls) and the ``platform``/``sandbox`` wrappers.
A design-pattern audit once wrongly claimed dispatch ran subprocesses itself; this test locks in
the real invariant so that concern can never become true by regression. (Sibling of
``test_no_ui_in_core_edges.py``.)
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent


_PROCESS_LAYERS = ("platform", "sandbox", "interfaces")


def _may_start_processes(rel: Path) -> bool:
    parts = rel.parts
    return (
        parts[0] in _PROCESS_LAYERS
        or "adapters" in parts[:-1]
        or parts[:3] == ("agent", "tools", "builtins")
    )


def _python_files() -> list[Path]:
    """Every module that is not one of the process-starting layers."""
    return sorted(
        p for p in _SRC_ROOT.rglob("*.py") if not _may_start_processes(p.relative_to(_SRC_ROOT))
    )


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


def test_only_the_adapter_layers_shell_out() -> None:
    files = _python_files()
    assert files, "the scan found no modules: the layout moved and this guard went vacuous"
    offenders = [str(p) for p in files if _shells_out(p)]
    assert not offenders, (
        "only platform/, sandbox/, adapters/, agent/tools/builtins/ and interfaces/ may start "
        f"a process; delegate to them: {offenders}"
    )
