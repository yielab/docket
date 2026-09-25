"""Guard: every `_REMOVED` entry prints its notice and exits 1.

`docket.__main__` only runs `main()` under `if __name__ == "__main__":`, so this guard still
reads `_REMOVED` by parsing the module's AST rather than importing it, to keep this file
import-only and independent of `sys.argv`/subprocess state. This exercises `python -m docket`
only; `tests/integration/test_console_script_entry_point.py` covers the installed
console-script entry point (`[project.scripts]`), a distinct object that must resolve to the
same notices and aliases.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

_MAIN_PY = Path(__file__).resolve().parents[2] / "src" / "docket" / "__main__.py"


def _load_removed() -> dict[str, tuple[str, ...]]:
    tree = ast.parse(_MAIN_PY.read_text(encoding="utf-8"))
    removed: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if target is None and isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "_REMOVED":
            removed = ast.literal_eval(node.value)
        elif (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "_REMOVED"
            and isinstance(node.value, ast.Subscript)
        ):
            removed[ast.literal_eval(target.slice)] = removed[ast.literal_eval(node.value.slice)]
    return removed


_REMOVED = _load_removed()


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DOCKET_HOME": str(tmp_path / ".docket")}
    return subprocess.run(
        [sys.executable, "-m", "docket", *args], capture_output=True, text=True, env=env
    )


@pytest.mark.parametrize("cmd", sorted(_REMOVED))
def test_removed_command_prints_notice_and_exits_1(cmd: str, tmp_path: Path) -> None:
    result = _run([cmd, "some", "extra", "args"], tmp_path)
    assert result.returncode == 1
    for line in _REMOVED[cmd]:
        assert line in result.stdout


def test_no_removed_entry_can_silently_disappear() -> None:
    assert len(_REMOVED) >= 23, "a _REMOVED key vanished without updating this guard"
    assert _REMOVED["wf"] == _REMOVED["workflow"]
    assert _REMOVED["evals"] == _REMOVED["eval"]
