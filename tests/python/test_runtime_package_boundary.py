"""Guard: the `docket-runtime` library stays CLI-free and dependency-thin.

The runtime slice (`core/llm.py`, `core/tools.py`, `core/session.py`,
`core/agent_loop.py`, `core/policy.py`, `core/approval.py`,
`core/security.py`, `core/audit.py`, `core/trace.py`,
`core/runtime_driver.py`, their real transitive dependencies, and
`edges/store.py` + the relevant `edges/adapters/*`) is packaged as a
separately installable distribution, `docket-runtime`, packaged from
``packages/docket-runtime/pyproject.toml`` via hatchling's `force-include` --
no files move or duplicate in the repository; that file just maps existing
``src/docket/...`` paths into the wheel. This is **packaging only**: a
boundary drawn around code that already exists, pinned by a test, not a
redesign.

This guard does not hand-maintain a second copy of "the file list" -- it
parses the packaging config's own `force-include` table, so the set of files
under test can never silently drift from the set actually shipped in the
wheel. Every file in that table must, at any import depth:

  1. never import `docket.cli` (or a submodule), `docket.ui`, `docket.serve`,
     or `docket.__main__` -- the CLI-facing surface a library must never
     reach into (CLAUDE.md's "core/edges never import ui.py or print" rule,
     extended to the packaging boundary); and
  2. never import a third-party package other than `pydantic` or `filelock`
     -- the two dependencies `packages/docket-runtime/pyproject.toml` itself
     declares, and the number ROADMAP/CLAUDE.md's "two third-party packages"
     claim is measured against.

AST-based, not line-scanning -- modelled on `test_no_subprocess_in_core.py`
and `test_no_openclaw_references.py`. A sibling guard elsewhere in this
suite once scanned source line by line and a constant that happened to wrap
across lines evaded it completely; parsing the real syntax tree is what
avoids that class of miss here.

The third-party check is scoped to **module-level** imports (including inside
a module-level `if`/`try`/`with`, but never inside a function or class body).
This matters for a real, deliberate case already in the shipped set:
`core/archetypes.py`'s `parse_yaml_file()` has a function-local, try/except
-guarded `import yaml` -- optional support for authoring a role as YAML, used
only by the CLI-facing `docket roles add <file.yaml>` path, not by anything
the runtime slice's own call surface (agent_loop/tools/session/policy/
approval/security/audit/trace) reaches. It was verified, not assumed: a bare
venv with only this distribution's two declared dependencies installed
imports every shipped module and exercises `dispatch_tool` end-to-end with
`yaml` absent from `sys.modules` entirely. Module scoping is what keeps this
test asserting a fact that is actually true ("nothing shipped here needs a
third package to *import*") rather than a stricter-sounding claim that isn't
("nothing shipped here ever mentions a third package"), which would force
either declaring an unneeded dependency or deleting optional, already-guarded
functionality -- both barred by the "packaging only" constraint. The
CLI-facing-import check has no such exception and applies at *any* depth,
lazy or not: there is no legitimate optional use of
`docket.cli`/`docket.ui`/`docket.serve`/`docket.__main__` from inside a
library file.

Proven RED before being trusted: a bare `import docket.ui` line and an
unguarded, module-level `import yaml` were planted, one at a time, into
`src/docket/core/llm.py` (a file this table ships) -- both were caught, then
the plant was reverted and
this test passed again.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_PYPROJECT = _REPO_ROOT / "packages" / "docket-runtime" / "pyproject.toml"

# The only two third-party packages the runtime distribution declares
# (packages/docket-runtime/pyproject.toml's own `dependencies`).
_ALLOWED_THIRD_PARTY = {"pydantic", "filelock"}

# CLI-facing modules a library file must never reach into, at any import
# depth (not just module scope) -- a function-local `import docket.ui` would
# be just as real a boundary break as a top-of-file one.
_FORBIDDEN_PREFIXES = ("docket.cli", "docket.ui", "docket.serve", "docket.__main__")

_STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _shipped_source_files() -> dict[str, Path]:
    """The runtime distribution's force-include table, source-path -> resolved Path.

    Keys are exactly as declared (e.g. ``"../../src/docket/core/llm.py"``),
    resolved relative to the packaging pyproject.toml's own directory --
    this is what makes the guard immune to drift: add a file to the wheel
    and this test covers it on the very next run with no edit required here.
    """
    data = tomllib.loads(_RUNTIME_PYPROJECT.read_text())
    table = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert table, (
        f"{_RUNTIME_PYPROJECT} has an empty force-include table -- "
        "the runtime distribution would ship no code at all."
    )
    pyproject_dir = _RUNTIME_PYPROJECT.parent
    resolved = {src: (pyproject_dir / src).resolve() for src in table}
    missing = [src for src, path in resolved.items() if not path.is_file()]
    assert not missing, f"force-include references file(s) that do not exist on disk: {missing}"
    return resolved


def _top_level_module(dotted: str) -> str:
    return dotted.split(".", 1)[0]


def _all_import_nodes(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Every Import/ImportFrom node in the file, at any nesting depth."""
    return [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]


def _module_level_import_nodes(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Import/ImportFrom nodes reachable without entering a function/class body.

    Descends into module-level `if`/`try`/`with` (the standard guarded-import
    shape), but deliberately stops at a `FunctionDef`/`AsyncFunctionDef`/
    `ClassDef` boundary -- a lazy import inside a function is not paid unless
    that function actually runs, so it is not a hard install-time dependency.
    """
    out: list[ast.Import | ast.ImportFrom] = []
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(node)
        elif isinstance(node, (ast.If, ast.Try)):
            stack.extend(getattr(node, "body", []))
            stack.extend(getattr(node, "orelse", []))
            stack.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
        elif isinstance(node, ast.With):
            stack.extend(node.body)
        # FunctionDef / AsyncFunctionDef / ClassDef: deliberately not descended into.
    return out


def _module_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    # ImportFrom: a relative import (`node.level > 0`) inside a shipped module
    # only ever reaches another `docket.*` module (cli/ui are siblings, not
    # ancestors, of core/edges) -- nothing to check.
    return [node.module] if node.module and node.level == 0 else []


def _cli_facing_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in _all_import_nodes(tree):
        for dotted in _module_names(node):
            if dotted.startswith(_FORBIDDEN_PREFIXES) or dotted in _FORBIDDEN_PREFIXES:
                offenders.append(
                    f"line {node.lineno}: forbidden import {dotted!r} (CLI-facing, not runtime)"
                )
    return offenders


def _third_party_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in _module_level_import_nodes(tree):
        for dotted in _module_names(node):
            top = _top_level_module(dotted)
            if top == "docket" or top in _STDLIB or top in _ALLOWED_THIRD_PARTY:
                continue
            offenders.append(
                f"line {node.lineno}: module-level third-party import {dotted!r} "
                f"(top-level {top!r}) is not in the runtime distribution's declared "
                f"dependencies {sorted(_ALLOWED_THIRD_PARTY)}"
            )
    return offenders


def test_shipped_files_never_import_cli_or_ui() -> None:
    shipped = _shipped_source_files()
    violations = {
        src: found for src, path in shipped.items() if (found := _cli_facing_violations(path))
    }
    assert not violations, (
        "docket-runtime must never import the CLI-facing surface, at any depth -- found:\n"
        + "\n".join(f"{src}: {vs}" for src, vs in violations.items())
    )


def test_shipped_files_declare_no_undeclared_third_party_import() -> None:
    shipped = _shipped_source_files()
    violations = {
        src: found for src, path in shipped.items() if (found := _third_party_violations(path))
    }
    assert not violations, (
        "docket-runtime may depend on nothing beyond pydantic + filelock at import "
        "time -- found:\n" + "\n".join(f"{src}: {vs}" for src, vs in violations.items())
    )
