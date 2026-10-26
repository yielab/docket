"""The files `docket-runtime` ships are computed from the facade's import graph, and stay small.

`packages/docket-runtime/hatch_build.py::runtime_closure` follows the import-time imports of the
facade package (and `_bind`) through `src/docket`. Its closure must hold the chokepoint, its gate
and the ports the facade binds, and none of the product: no task, pipeline, hop or interface
module, and none of the turn loop.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"
SRC = ROOT / "src" / "docket"

# The wheel's build hook imports hatchling; the closure functions do not need it.
_HATCHLING = (
    "hatchling",
    "hatchling.builders",
    "hatchling.builders.hooks",
    "hatchling.builders.hooks.plugin",
    "hatchling.builders.hooks.plugin.interface",
)


def _hook() -> ModuleType:
    stubs = {name: types.ModuleType(name) for name in _HATCHLING}
    stubs[_HATCHLING[-1]].BuildHookInterface = object  # type: ignore[attr-defined]
    spec = importlib.util.spec_from_file_location("runtime_hatch_build", RUNTIME / "hatch_build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    saved = {name: sys.modules.get(name) for name in _HATCHLING}
    sys.modules.update(stubs)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


def _closure() -> tuple[str, ...]:
    return _hook().runtime_closure(SRC, RUNTIME / "src" / "docket_runtime")


def test_the_closure_holds_the_chokepoint_its_gate_and_the_bound_ports() -> None:
    closure = set(_closure())

    assert {
        "agent/tools/registry.py",
        "agent/ports.py",
        "governance/gate.py",
        "governance/approval.py",
        "observability/trace.py",
        "kernel/handoff.py",
        "kernel/ports.py",
        "platform/git.py",
        "sandbox/launch.py",
    } <= closure


def test_the_closure_ships_no_product_module() -> None:
    product = ("interfaces/", "tasks/", "pipeline/", "hops/", "operator/inbox", "teams/pod")
    loop_modules = {"agent/loop.py", "agent/session.py", "agent/context.py", "agent/loop_trace.py"}

    shipped = [
        path
        for path in _closure()
        if path.startswith(product) or path in loop_modules or path == "bootstrap.py"
    ]

    assert shipped == []


def test_every_package_on_the_way_ships_its_init() -> None:
    closure = set(_closure())

    for path in closure:
        for parent in Path(path).parents:
            if parent != Path("."):
                assert (parent / "__init__.py").as_posix() in closure, path


def test_the_closure_follows_import_time_imports_only(tmp_path: Path) -> None:
    source = tmp_path / "docket"
    facade = tmp_path / "docket_runtime"
    for name, text in {
        "__init__.py": "",
        "a/__init__.py": "",
        "a/root.py": (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "from docket.b import used\n"
            "if TYPE_CHECKING:\n    from docket.c import typing_only\n"
            "try:\n    import docket.d\nexcept ImportError:\n    pass\n"
            "def lazy():\n    from docket.e import lazy_only\n"
        ),
        "b/__init__.py": "",
        "b/used.py": "",
        "c/__init__.py": "",
        "c/typing_only.py": "",
        "d/__init__.py": "",
        "e/__init__.py": "",
        "e/lazy_only.py": "",
    }.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(text, encoding="utf-8")
    facade.mkdir()
    (facade / "__init__.py").write_text(
        "from docket_runtime._internal.docket.a.root import lazy\n", encoding="utf-8"
    )

    closure = _hook().runtime_closure(source, facade)

    assert closure == (
        "__init__.py",
        "a/__init__.py",
        "a/root.py",
        "b/__init__.py",
        "b/used.py",
        "d/__init__.py",
    )
