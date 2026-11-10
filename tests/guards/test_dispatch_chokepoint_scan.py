"""Guard: only the tool chokepoint and its listed neighbours import the handler module.

``dispatch_tool`` is the sole path to a tool handler. This scan reads every module under
``src/docket`` and fails when one outside ``ALLOWED_IMPORTERS`` imports ``toolbox``, the
module that holds the handler functions. A second importer is a second way to run a tool,
and a gate that can be skipped is not a gate. It reads the whole source tree, so it is a
guard, not a unit test.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestSinglePathToExecution:
    """The architectural invariant, checked against the tree rather than
    asserted in prose: if a second module can call a handler directly, the gate
    is optional, and an optional gate is not a gate."""

    # agent/tools/mcp_tools.py / agent/tools/mcp_client.py:
    # both reference toolbox.py's `ToolOutcome` -- the inert "what happened"
    # result dataclass every Tool.handler must return -- so an MCP-adapted
    # tool's handler can construct one, exactly as agent/tools/registry.py's own
    # built-in handlers do. Neither file imports, or ever calls, an actual
    # handler *function* (read_file/write_file/edit_file/glob_files/
    # grep_files/run_bash); dispatch_tool remains the only thing that ever
    # invokes a Tool's handler. Confirmed by the unit file's own
    # `test_the_gate_is_consulted_by_dispatch_itself`-style reasoning, and by
    # `tests/integration/test_mcp_client.py`'s `TestGatedExactlyLikeABuiltin`,
    # which dispatches an MCP-adapted tool through the real, unmodified
    # `dispatch_tool` and proves a `pre_tool_call` policy gates it.
    #
    # platform/fetch.py: same shape again --
    # it imports `ToolOutcome` only, to construct the return value its own
    # `fetch_url` handler function produces. `agent/tools/registry.py`'s `fetch`
    # registration calls `fetch_url` directly (the same way it calls
    # `toolbox.read_file` et al.); nothing outside `dispatch_tool` ever does.
    #
    # agent/tools/records_tools.py: imports `resolve_within` and `PathEscapeError` only, so
    # `rec__export` resolves its path inside the hop's roots exactly as `write` does; it calls no
    # handler function.
    ALLOWED_IMPORTERS: ClassVar[set[str]] = {
        "agent/tools/registry.py",
        "hops/application/builtin_tools.py",
        "agent/tools/builtins/toolbox.py",
        "agent/tools/builtins/background.py",
        "agent/tools/mcp_tools.py",
        "agent/tools/mcp_client.py",
        "agent/tools/records_tools.py",
        "platform/fetch.py",
    }

    @staticmethod
    def _imports_toolbox(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if "toolbox" in (node.module or "") or any(
                    alias.name == "toolbox" for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.Import) and any(
                "toolbox" in alias.name for alias in node.names
            ):
                return True
        return False

    def test_only_the_chokepoint_imports_the_handler_module(self) -> None:
        offenders = [
            rel
            for path in sorted((REPO_ROOT / "src" / "docket").rglob("*.py"))
            if (rel := path.relative_to(REPO_ROOT / "src" / "docket").as_posix())
            not in self.ALLOWED_IMPORTERS
            and self._imports_toolbox(ast.parse(path.read_text()))
        ]
        assert not offenders, f"handlers reachable outside the chokepoint from: {offenders}"
