"""Architecture: the allowed-dependency table of ADR 0030 as import-linter contracts.

Each row of the table (``docs/adr/0030-organize-by-context-and-refactor-by-tool.md``, quoted in
AGENTS.md) is one contract, checked against the real import graph of ``src/docket`` with
function-local imports included. The rule for a row is one function in this file.

``import_contracts_baseline.txt`` lists every import breaking a row today as
``contract | importer -> imported``, fed to its contract as ``ignore_imports``. It only shrinks: a
new violation is not listed, so its contract breaks; a listed import that stopped violating fails
``test_every_baselined_violation_still_breaks_its_contract`` -- delete the line
(``python tests/architecture/test_import_contracts.py --write``). ``bootstrap`` has no contract.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import grimp
import pytest
from grimp import ImportGraph
from importlinter import configuration
from importlinter.application import output
from importlinter.application.contract_utils import AlertLevel, remove_ignored_imports_and_report
from importlinter.application.use_cases import create_report
from importlinter.application.user_options import UserOptions
from importlinter.domain import fields
from importlinter.domain.contract import Contract, ContractCheck, registry

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
BASELINE = Path(__file__).with_name("import_contracts_baseline.txt")
ROOT = "docket"
TYPE_NAME = "docket_allowed_dependencies"

# What each ADR row calls a layer inside a context.
_INNER = {"domain", "application", "adapters"}


def _classify(module: str) -> tuple[str, str]:
    """(context, layer) of a module: layer is one of the ADR table's rows."""
    parts = module.split(".")[1:]
    if not parts:
        return "", "root"
    ctx = parts[0]
    if ctx == "__main__" or ctx == "bootstrap":
        return ctx, "bootstrap"
    if ctx in {"kernel", "agent", "interfaces"}:
        return ctx, ctx
    if ctx in {"platform", "sandbox"}:
        return ctx, "adapters"
    if len(parts) > 1 and parts[1] in _INNER:
        return ctx, parts[1]
    return ctx, "flat"


def _is_context_init(module: str) -> bool:
    return len(module.split(".")) == 2


def _is_ports(module: str) -> bool:
    return "ports" in module.split(".")[2:]


def _allowed_kernel(importer: str, imported: str) -> bool:
    return _classify(imported)[0] == "kernel"


def _allowed_domain(importer: str, imported: str) -> bool:
    (ic, _), (tc, tl) = _classify(importer), _classify(imported)
    return tc == "kernel" or (tc == ic and tl == "domain")


def _allowed_application(importer: str, imported: str) -> bool:
    (ic, _), (tc, tl) = _classify(importer), _classify(imported)
    if tc == "kernel":
        return True
    if tc == ic:
        return tl != "adapters"
    return tc != "interfaces" and _is_context_init(imported)


def _allowed_adapters(importer: str, imported: str) -> bool:
    (ic, _), (tc, tl) = _classify(importer), _classify(imported)
    if tc in {"kernel", ic}:
        return True
    if tc == "platform":
        return _is_context_init(imported)
    return tc != "interfaces" and (tl == "domain" or _is_ports(imported))


def _allowed_agent(importer: str, imported: str) -> bool:
    return _classify(imported)[0] in {"kernel", "agent"}


def _allowed_interfaces(importer: str, imported: str) -> bool:
    tc = _classify(imported)[0]
    return tc in {"kernel", "interfaces", "bootstrap"} or _is_context_init(imported)


# contract name -> (layers of the importing module it governs, rule)
_CONTRACTS: dict[str, tuple[frozenset[str], Any]] = {
    "kernel imports nothing in docket": (frozenset({"kernel"}), _allowed_kernel),
    "domain imports kernel and its own domain": (frozenset({"domain"}), _allowed_domain),
    "application imports kernel, its own context and other contexts' __init__": (
        frozenset({"application", "flat"}),
        _allowed_application,
    ),
    "adapters, platform and sandbox import kernel, own context, ports and domain types": (
        frozenset({"adapters"}),
        _allowed_adapters,
    ),
    "agent imports kernel only": (frozenset({"agent"}), _allowed_agent),
    "interfaces import kernel, bootstrap and contexts' __init__": (
        frozenset({"interfaces"}),
        _allowed_interfaces,
    ),
}


def violations(graph: ImportGraph, name: str) -> list[tuple[str, str]]:
    """Every direct import (importer, imported) that breaks contract ``name`` in ``graph``."""
    layers, rule = _CONTRACTS[name]
    found = []
    for importer in sorted(graph.modules):
        if _classify(importer)[1] not in layers:
            continue
        for imported in sorted(graph.find_modules_directly_imported_by(importer)):
            if imported != ROOT and not rule(importer, imported):
                found.append((importer, imported))
    return found


class AllowedDependenciesContract(Contract):
    """One row of the ADR table: modules in ``name``'s layers import only what its rule allows."""

    type_name = TYPE_NAME

    contract = fields.StringField()
    ignore_imports = fields.SetField(subfield=fields.ImportExpressionField(), required=False)

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        removal = remove_ignored_imports_and_report(
            graph=graph,
            ignore_imports=self.ignore_imports,  # type: ignore[attr-defined]
            unmatched_alerting=AlertLevel.ERROR,
        )
        found = violations(graph, self.contract)  # type: ignore[attr-defined]
        return ContractCheck(
            kept=not found,
            metadata={"violations": found},
            warnings=list(removal.warnings),
            ignored_import_count=len(removal.removed_imports),
        )

    def render_broken_contract(self, check: ContractCheck) -> None:
        for importer, imported in check.metadata["violations"]:
            output.print(f"{importer} -> {imported}")


def _read_baseline() -> dict[str, list[str]]:
    by_contract: dict[str, list[str]] = defaultdict(list)
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            name, _, edge = line.partition(" | ")
            assert name in _CONTRACTS, f"baseline names an unknown contract: {name!r}"
            by_contract[name].append(edge)
    return by_contract


def _run(baseline: dict[str, list[str]]) -> dict[str, ContractCheck]:
    configuration.configure()
    registry.register(AllowedDependenciesContract, TYPE_NAME)
    options = UserOptions(
        session_options={"root_packages": [ROOT]},
        contracts_options=[
            {
                "id": f"c{i}",
                "name": name,
                "type": TYPE_NAME,
                "contract": name,
                "ignore_imports": baseline.get(name, []),
            }
            for i, name in enumerate(_CONTRACTS)
        ],
    )
    report = create_report(options, cache_dir=None)
    assert not report.could_not_run, "import-linter could not run the contracts"
    return {contract.name: check for contract, check in report.get_contracts_and_checks()}


def _write_baseline() -> int:
    graph = grimp.build_graph(ROOT, include_external_packages=False)
    lines = [
        "# imports that break an ADR 0030 dependency row today; shrink-only",
        "# format: contract | importer -> imported; regenerate with",
        "#   python tests/architecture/test_import_contracts.py --write",
    ]
    total = 0
    for name in _CONTRACTS:
        for importer, imported in violations(graph, name):
            lines.append(f"{name} | {importer} -> {imported}")
            total += 1
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


@pytest.mark.parametrize("name", list(_CONTRACTS))
def test_contract_holds_apart_from_the_baseline(name: str) -> None:
    check = _run(_read_baseline())[name]
    new = "\n".join(f"  {a} -> {b}" for a, b in check.metadata.get("violations", []))
    assert check.kept, (
        f"new import(s) break the contract {name!r}:\n{new}\n"
        "Move the dependency behind the allowed seam; do not add it to the baseline."
    )


def test_every_baselined_violation_still_breaks_its_contract() -> None:
    graph = grimp.build_graph(ROOT, include_external_packages=False)
    stale = []
    for name, edges in _read_baseline().items():
        current = {f"{a} -> {b}" for a, b in violations(graph, name)}
        stale += [f"{name} | {edge}" for edge in edges if edge not in current]
    assert not stale, (
        "baselined imports that no longer violate (or no longer exist); delete the lines, "
        "the list only shrinks (python tests/architecture/test_import_contracts.py --write):\n"
        + "\n".join(stale)
    )


def test_the_baseline_has_no_duplicates() -> None:
    lines = [ln for ln in BASELINE.read_text(encoding="utf-8").splitlines() if ln and ln[0] != "#"]
    assert len(lines) == len(set(lines))


def test_every_layer_of_the_table_has_a_contract() -> None:
    covered = set().union(*(layers for layers, _ in _CONTRACTS.values()))
    graph = grimp.build_graph(ROOT, include_external_packages=False)
    layers = {_classify(m)[1] for m in graph.modules}
    # `root` and `bootstrap` import everything, by the table; nothing else may be left out.
    assert layers - {"root", "bootstrap"} <= covered


_BITES: list[tuple[str, str, str, bool]] = [
    ("kernel", "docket.kernel.home", "docket.kernel.errors", True),
    ("kernel", "docket.kernel.home", "docket.platform.store", False),
    ("domain", "docket.tasks.domain.task", "docket.tasks.domain.refs", True),
    ("domain", "docket.tasks.domain.task", "docket.tasks.application.queue", False),
    ("domain", "docket.tasks.domain.task", "docket.governance", False),
    ("application", "docket.tasks.application.queue", "docket.governance", True),
    ("application", "docket.tasks.application.queue", "docket.governance.policy", False),
    ("application", "docket.tasks.application.queue", "docket.tasks.adapters.json_store", False),
    ("application", "docket.tasks.application.queue", "docket.interfaces", False),
    ("adapters", "docket.models.adapters.openai_http", "docket.models.catalog", True),
    ("adapters", "docket.models.adapters.openai_http", "docket.tasks.domain.task", True),
    ("adapters", "docket.models.adapters.openai_http", "docket.tasks.application.queue", False),
    ("adapters", "docket.operator.adapters.ntfy", "docket.platform", True),
    ("adapters", "docket.operator.adapters.ntfy", "docket.platform.redirects", False),
    ("agent", "docket.agent.loop", "docket.kernel.text", True),
    ("agent", "docket.agent.loop", "docket.governance.policy", False),
    ("interfaces", "docket.interfaces.cli.app", "docket.tasks", True),
    ("interfaces", "docket.interfaces.cli.app", "docket.tasks.application.queue", False),
]
_RULES_BY_LAYER = {
    "kernel": _allowed_kernel,
    "domain": _allowed_domain,
    "application": _allowed_application,
    "adapters": _allowed_adapters,
    "agent": _allowed_agent,
    "interfaces": _allowed_interfaces,
}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def declared_exports(source: str) -> list[str] | None:
    """The names of a literal ``__all__`` in ``source``, or None when it declares none."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            assert isinstance(node.value, ast.List | ast.Tuple), "__all__ must be a literal list"
            return [ast.literal_eval(e) for e in node.value.elts]
    return None


def facade_exports() -> dict[str, list[str]]:
    """Context -> the names its ``__init__`` exports; kernel has no facade."""
    found: dict[str, list[str]] = {}
    for init in sorted((SRC / ROOT).glob("*/__init__.py")):
        names = declared_exports(init.read_text(encoding="utf-8"))
        if names is not None:
            found[init.parent.name] = names
    return found


def _submodules(context: str) -> list[str]:
    """Dotted names of the modules and packages directly under ``context``."""
    return [
        f"{ROOT}.{context}.{p.stem if p.is_file() else p.name}"
        for p in sorted((SRC / ROOT / context).iterdir())
        if p.name != "__init__.py" and (p.suffix == ".py" or (p / "__init__.py").exists())
    ]


def names_imported_from_outside() -> dict[str, set[str]]:
    """Context -> the names other modules of ``src`` import with ``from docket.<context> import``."""
    used: dict[str, set[str]] = defaultdict(set)
    for path in sorted((SRC / ROOT).rglob("*.py")):
        importer = _module_name(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
                continue
            parts = node.module.split(".")
            if len(parts) == 2 and parts[0] == ROOT and not importer.startswith(node.module):
                submodules = {m.split(".")[-1] for m in _submodules(parts[1])}
                used[parts[1]].update(a.name for a in node.names if a.name not in submodules)
    return used


def dead_exports(exports: dict[str, list[str]], used: dict[str, set[str]]) -> list[str]:
    """Every ``context.name`` exported by a facade that no module outside the context imports."""
    return [
        f"{ctx}.{name}"
        for ctx, names in sorted(exports.items())
        for name in names
        if name not in used.get(ctx, set())
    ]


def test_every_export_of_a_context_is_imported_from_outside_it() -> None:
    dead = dead_exports(facade_exports(), names_imported_from_outside())
    assert not dead, (
        "names in a context's __all__ that no other context imports; delete them from the "
        "facade (a dead export is dead code, ADR 0030 'After Phase 46'):\n  " + "\n  ".join(dead)
    )


def test_every_name_imported_from_a_facade_is_exported_by_it() -> None:
    exports = facade_exports()
    missing = [
        f"{ctx}.{name}"
        for ctx, names in sorted(names_imported_from_outside().items())
        if ctx in exports
        for name in sorted(names - set(exports[ctx]))
    ]
    assert not missing, "imported from a facade but absent from its __all__:\n  " + "\n  ".join(
        missing
    )


def test_the_dead_export_check_sees_what_it_exists_for() -> None:
    # Without these a check that matched nothing would hold any facade.
    exports = {"teams": ["fleet_of", "used"], "tasks": ["queue"]}
    used = {"teams": {"used"}, "tasks": {"queue"}}
    assert dead_exports(exports, used) == ["teams.fleet_of"]
    assert dead_exports(exports, {**used, "teams": {"used", "fleet_of"}}) == []
    assert declared_exports("__all__ = ['a', 'b']\n") == ["a", "b"]
    assert declared_exports("x = 1\n") is None


@pytest.mark.parametrize(("layer", "importer", "imported", "ok"), _BITES)
def test_each_rule_accepts_and_refuses_what_the_table_says(
    layer: str, importer: str, imported: str, ok: bool
) -> None:
    # Without these a rule that allowed everything would hold any baseline.
    assert _RULES_BY_LAYER[layer](importer, imported) is ok


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        print(f"wrote {_write_baseline()} violations to {BASELINE.relative_to(REPO)}")
    else:
        sys.exit("usage: test_import_contracts.py --write")
