"""Build the private runtime implementation without claiming ``docket`` files.

The control-plane wheel owns ``docket``. At build time this hook copies the
runtime closure into ``docket_runtime._internal.docket`` and rewrites its
absolute first-party imports. The closure is computed from the import graph of
the facade package (``runtime_closure``), not listed. The same source material is included in the
sdist, so a wheel rebuilt from an sdist has no dependency on the monorepo's
parent directory.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_PRIVATE = "docket_runtime._internal.docket"
_PUBLIC = "docket"


def _first_party_imports(path: Path) -> set[str]:
    """Every dotted name the module imports at import time (``docket.x`` and ``docket.x.name``).

    Module-level statements only, ``if``/``try`` bodies included, ``if TYPE_CHECKING`` bodies
    excluded. An import inside a function or class body is a lazy dependency of a feature the
    runtime does not ship (for example the task ledger an approval denial reason joins) and is
    not followed."""
    found: set[str] = set()

    def visit(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.If):
                test = node.test
                if getattr(test, "id", getattr(test, "attr", "")) != "TYPE_CHECKING":
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif isinstance(node, ast.With):
                visit(node.body)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:
                    raise ValueError(f"{path}: a relative import cannot be rewritten")
                found.add(node.module)
                found.update(f"{node.module}.{a.name}" for a in node.names)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def _module_file(source: Path, dotted: str) -> Path | None:
    """The file of module ``docket.a.b`` under *source* (the ``docket`` directory), or ``None``
    when the name is not a module (a class or function imported from one)."""
    base = source.joinpath(*dotted.split(".")[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _facade_roots(facade: Path) -> set[str]:
    """The modules of ``docket`` the facade package imports from its private copy."""
    roots: set[str] = set()
    for path in sorted(facade.rglob("*.py")):
        for name in _first_party_imports(path):
            if name == _PRIVATE or name.startswith(_PRIVATE + "."):
                roots.add(_PUBLIC + name[len(_PRIVATE) :])
    return roots


def runtime_closure(source: Path, facade: Path) -> tuple[str, ...]:
    """The files of ``docket`` (relative paths) the facade needs to import, sorted.

    The closure of the facade's import-time imports, plus the ``__init__.py`` of every package
    on the way (importing ``docket.a.b`` runs ``docket/a/__init__.py``). It is computed, not
    listed, so a module the runtime starts importing is shipped and one it stops importing is
    dropped."""
    files: set[Path] = set()
    seen: set[str] = set()
    pending = sorted(_facade_roots(facade))
    while pending:
        dotted = pending.pop()
        if dotted in seen or not (dotted == _PUBLIC or dotted.startswith(_PUBLIC + ".")):
            continue
        seen.add(dotted)
        found = _module_file(source, dotted)
        if found is None:
            continue
        parts = dotted.split(".")
        for depth in range(1, len(parts) + 1):
            pending.append(".".join(parts[:depth]))
        if found not in files:
            files.add(found)
            pending.extend(_first_party_imports(found))
    return tuple(sorted(path.relative_to(source).as_posix() for path in files))


class CustomBuildHook(BuildHookInterface):
    """Stage the namespace-private implementation for a wheel build."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        source = root / "runtime-source" / "docket"
        if not source.is_dir():
            source = root.parents[1] / "src" / "docket"

        staged = Path(
            tempfile.mkdtemp(
                prefix="docket-runtime-build-", dir=os.environ.get("DOCKET_RUNTIME_BUILD_TMPDIR")
            )
        )
        package = staged / "docket_runtime" / "_internal" / "docket"
        for relative in runtime_closure(source, root / "src" / "docket_runtime"):
            original = source / relative
            if not original.is_file():
                raise FileNotFoundError(f"Runtime source file missing: {original}")
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                original.read_text(encoding="utf-8").replace(
                    "docket.", "docket_runtime._internal.docket."
                ),
                encoding="utf-8",
            )

        internal = package.parent
        (internal / "__init__.py").write_text('"""Private implementation."""\n')
        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            raise TypeError("Hatch build data force_include must be a mapping")
        force_include[str(staged / "docket_runtime" / "_internal")] = "docket_runtime/_internal"

    def finalize(self, version: str, build_data: dict[str, object], artifact_path: str) -> None:
        force_include = build_data.get("force_include", {})
        if not isinstance(force_include, dict):
            return
        for path in force_include:
            staged = Path(path).parents[1]
            if staged.name.startswith("docket-runtime-build-"):
                shutil.rmtree(staged, ignore_errors=True)
