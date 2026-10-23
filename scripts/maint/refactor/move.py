#!/usr/bin/env python3
"""Execute ``refactor/target-map.toml``: move modules and definitions, rewrite every reference.

Schema. Module moves apply first; a definition's ``from`` and ``to`` may use either spelling of a
moved module, and a ``from`` naming a package moves every module under it::

    # whole-module moves, applied first
    [[module]]
    from = "docket.core.trace"
    to = "docket.observe.trace"

    # named definitions moved in list order (functions, classes, module-level assignments)
    [[definition]]
    from = "docket.core.dispatch"
    to = "docket.tasks.claim"
    names = ["claim_next", "_ClaimState"]

A definition leaves with its decorators and leading comments, lands at the end of the destination
(created when missing) and brings the imports it needs; code left behind imports what it lost. A
definition that uses code left behind imports it from the source: leaf-first order avoids cycles.

Rewritten in ``src``, ``tests``, ``benchmarks``, ``scripts``, ``examples`` and ``packages``:
``import`` and ``from`` statements (split per destination, relative ones made absolute when they
would break), ``alias.name`` on a module alias, ``setattr(alias, "name", ...)``, whole-string
dotted targets and ``SUBJECT``, ``src/docket/...`` path strings. A ``tests/unit`` file at the
mirror path of its ``SUBJECT`` moves to the mirror of the new one; one whose tests touch several
destinations is split by symbol, each part keeping the fixtures and helpers it uses. Dotted names
and paths in ``specs/``, ``docs/`` (not ``cycles-ended/`` or ``adr/``), ``CONTRIBUTING.md``,
``AGENTS.md`` and ``.agents/skills/`` follow. Changed Python files then go through
``ruff check --fix`` and ``ruff format`` with the root's own configuration. Strings built from
path segments, comments and prose are left for the gate to find. ``refactor/retired.txt`` gains
``retired: <id> -> ?`` for each test with no counterpart afterwards.

Flags: ``--dry-run`` lists the plan and writes nothing; ``--check`` exits 1 unless the tree already
is the mapping's result; ``--report FILE`` writes file and test-id moves as JSON. A second run
changes nothing. Exit status: 0 done or clean, 1 not clean under ``--check``, 2 problems (nothing
is written).
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path

import libcst as cst
from libcst.metadata import GlobalScope, MetadataWrapper, ScopeProvider

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "docket"
SRC_PREFIX = "src/docket/"
CODE_DIRS = ("src", "tests", "benchmarks", "scripts", "examples", "packages")
DOC_DIRS = ("specs", "docs", ".agents/skills")
DOC_FILES = ("CONTRIBUTING.md", "AGENTS.md")
DOC_EXCLUDED = ("docs/cycles-ended/", "docs/adr/")
SKIPPED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
SKIPPED_AT_ROOT = {"build", "dist"}
FIXTURE_TREES = "/fixtures/refactor/"
UNIT_DIR = "tests/unit/"
MAP_FILE = "refactor/target-map.toml"
RETIRED_FILE = "refactor/retired.txt"
SETATTR_NAMES = {"setattr", "delattr", "getattr", "hasattr", "object"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DOTTED_STRING = re.compile(rf"{PACKAGE}(?:\.\w+)+(?:[:.]\w+)*")
DOTTED_TOKEN = re.compile(rf"(?<![\w.]){PACKAGE}(?:\.\w+)+")
PATH_TOKEN = re.compile(r"(?<![\w./-])((?:[\w-]+/)+[\w-]+\.py)(::\w+)?(?!\w)")


class PlanError(Exception):
    """A mapping or tree the tool cannot execute."""


# --------------------------------------------------------------------------- mapping


@dataclasses.dataclass(frozen=True)
class ModuleMove:
    src: str
    dst: str


@dataclasses.dataclass(frozen=True)
class DefMove:
    src: str
    dst: str
    names: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Mapping:
    modules: tuple[ModuleMove, ...]
    definitions: tuple[DefMove, ...]


def _dotted(value: object, where: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"{PACKAGE}(\.\w+)+", value):
        raise PlanError(f"{where}: expected a dotted name under {PACKAGE!r}, got {value!r}")
    return value


def parse_mapping(text: str) -> Mapping:
    data = tomllib.loads(text)
    unknown = set(data) - {"module", "definition"}
    if unknown:
        raise PlanError(f"target map: unknown table {sorted(unknown)}")
    modules: list[ModuleMove] = []
    for i, entry in enumerate(data.get("module", [])):
        if set(entry) != {"from", "to"}:
            raise PlanError(f"[[module]] #{i + 1}: keys must be exactly from and to")
        src, dst = (
            _dotted(entry["from"], f"module #{i + 1}"),
            _dotted(entry["to"], f"module #{i + 1}"),
        )
        if src == dst:
            raise PlanError(f"[[module]] #{i + 1}: from and to are both {src}")
        modules.append(ModuleMove(src, dst))
    defs: list[DefMove] = []
    seen: set[tuple[str, str]] = set()
    for i, entry in enumerate(data.get("definition", [])):
        if set(entry) != {"from", "to", "names"}:
            raise PlanError(f"[[definition]] #{i + 1}: keys must be exactly from, to and names")
        src, dst = (
            _dotted(entry["from"], f"definition #{i + 1}"),
            _dotted(entry["to"], f"definition #{i + 1}"),
        )
        names = entry["names"]
        if not (
            isinstance(names, list)
            and names
            and all(isinstance(n, str) and IDENT.fullmatch(n) for n in names)
        ):
            raise PlanError(
                f"[[definition]] #{i + 1}: names must be a non-empty list of identifiers"
            )
        if src == dst:
            raise PlanError(f"[[definition]] #{i + 1}: from and to are both {src}")
        for name in names:
            if (src, name) in seen:
                raise PlanError(f"[[definition]] #{i + 1}: {src}.{name} is listed twice")
            seen.add((src, name))
        defs.append(DefMove(src, dst, tuple(names)))
    for kind, items in (
        ("module from", [m.src for m in modules]),
        ("module to", [m.dst for m in modules]),
    ):
        dup = {x for x in items if items.count(x) > 1}
        if dup:
            raise PlanError(f"target map: duplicate {kind} {sorted(dup)}")
    return Mapping(tuple(modules), tuple(defs))


# --------------------------------------------------------------------------- names


def dotted_text(node: cst.BaseExpression | None) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = dotted_text(node.value)
        return None if base is None else f"{base}.{node.attr.value}"
    return None


def make_dotted(text: str) -> cst.Name | cst.Attribute:
    first, *rest = text.split(".")
    node: cst.Name | cst.Attribute = cst.Name(first)
    for part in rest:
        node = cst.Attribute(value=node, attr=cst.Name(part))
    return node


def module_of_path(path: str) -> str:
    """Dotted name of a repo-relative ``.py`` path; a package for ``__init__.py``."""
    rel = path[len(SRC_PREFIX) :] if path.startswith(SRC_PREFIX) else None
    if rel is not None:
        parts = [PACKAGE, *rel[: -len(".py")].split("/")]
    else:
        parts = path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def path_of_module(dotted: str, *, package: bool = False) -> str:
    rel = "/".join(dotted.split(".")[1:])
    return f"{SRC_PREFIX}{rel}/__init__.py" if package else f"{SRC_PREFIX}{rel}.py"


@dataclasses.dataclass
class RenameSet:
    """Old-to-new names. ``modules`` has prefix semantics (a package carries its children)."""

    modules: dict[str, str]
    defs: dict[str, dict[str, str]]
    known: set[str]

    def map_module(self, name: str) -> str | None:
        parts = name.split(".")
        for i in range(len(parts), 1, -1):
            prefix = ".".join(parts[:i])
            if prefix in self.modules:
                return ".".join([self.modules[prefix], *parts[i:]])
        return None

    def rewrite_dotted(self, text: str) -> str | None:
        parts = text.split(".")
        for i in range(len(parts), 1, -1):
            owner, name = ".".join(parts[: i - 1]), parts[i - 1]
            if name in self.defs.get(owner, {}):
                return ".".join([self.defs[owner][name], name, *parts[i:]])
            prefix = ".".join(parts[:i])
            if prefix in self.modules:
                return ".".join([self.modules[prefix], *parts[i:]])
        return None


# --------------------------------------------------------------------------- tree


def _skipped(rel: str) -> bool:
    parts = rel.split("/")
    return (
        bool(set(parts) & SKIPPED_PARTS)
        or parts[0] in SKIPPED_AT_ROOT
        or FIXTURE_TREES in f"/{rel}"
    )


def _doc_selected(rel: str) -> bool:
    if not rel.endswith(".md") or any(rel.startswith(x) for x in DOC_EXCLUDED):
        return False
    return rel in DOC_FILES or any(rel.startswith(d + "/") for d in DOC_DIRS)


class Tree:
    """Repo files in scope as text, keyed by repo-relative posix path. ``disk`` never changes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.disk: dict[str, str] = {}
        for base, dirs, names in os.walk(root):
            rel_base = Path(base).relative_to(root).as_posix()
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in SKIPPED_PARTS and (rel_base != "." or d not in SKIPPED_AT_ROOT)
            )
            for name in sorted(names):
                rel = name if rel_base == "." else f"{rel_base}/{name}"
                if _skipped(rel):
                    continue
                code = rel.endswith(".py") and rel.split("/")[0] in CODE_DIRS
                if code or _doc_selected(rel) or rel == RETIRED_FILE:
                    self.disk[rel] = (root / rel).read_text(encoding="utf-8")
        self.files = dict(self.disk)
        self.renames: dict[str, str] = {}
        self.origin_of: dict[str, str] = {}

    def py_paths(self) -> list[str]:
        return sorted(p for p in self.files if p.endswith(".py"))

    def final_path(self, path: str) -> str:
        return self.renames.get(path, path)

    def context_path(self, path: str) -> str:
        return self.origin_of.get(path, path)


# --------------------------------------------------------------------------- libcst helpers


def small(stmt: cst.CSTNode) -> cst.BaseSmallStatement | None:
    if isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1:
        return stmt.body[0]
    return None


def is_import_line(stmt: cst.CSTNode) -> bool:
    node = small(stmt)
    return isinstance(node, (cst.Import, cst.ImportFrom))


def is_future(stmt: cst.CSTNode) -> bool:
    node = small(stmt)
    return isinstance(node, cst.ImportFrom) and dotted_text(node.module) == "__future__"


def is_docstring(stmt: cst.CSTNode) -> bool:
    node = small(stmt)
    return isinstance(node, cst.Expr) and isinstance(node.value, cst.SimpleString)


def stmt_names(stmt: cst.CSTNode) -> list[str]:
    """Names a top-level statement binds as a definition: a def, a class, or ``NAME = ...``."""
    if isinstance(stmt, (cst.FunctionDef, cst.ClassDef)):
        return [stmt.name.value]
    node = small(stmt)
    if isinstance(node, cst.Assign) and len(node.targets) == 1:
        target = node.targets[0].target
        return [target.value] if isinstance(target, cst.Name) else []
    if isinstance(node, cst.AnnAssign) and isinstance(node.target, cst.Name):
        return [node.target.value]
    return []


class _NodeIds(cst.CSTVisitor):
    def __init__(self) -> None:
        self.ids: set[int] = set()

    def on_visit(self, node: cst.CSTNode) -> bool:
        self.ids.add(id(node))
        return True


class ModuleRefs:
    """Which top-level statement uses a name another top-level statement binds."""

    def __init__(self, module: cst.Module) -> None:
        self.module = module
        self.owner: dict[int, int] = {}
        for i, stmt in enumerate(module.body):
            ids = _NodeIds()
            stmt.visit(ids)
            for node_id in ids.ids:
                self.owner[node_id] = i
        self.bound: dict[int, set[str]] = defaultdict(set)
        self.uses: dict[int, set[tuple[str, int]]] = defaultdict(set)
        if not module.body:
            return
        scopes = MetadataWrapper(module, unsafe_skip_copy=True).resolve(ScopeProvider)
        distinct = {id(s): s for s in scopes.values() if s is not None}
        if not distinct:
            return
        glob = next(iter(distinct.values())).globals
        assert isinstance(glob, GlobalScope)
        for assignment in glob.assignments:
            idx = self.owner.get(id(getattr(assignment, "node", None)))
            if idx is not None:
                self.bound[idx].add(assignment.name)
        for scope in distinct.values():
            for access in scope.accesses:
                self._record(access)

    def _record(self, access: object) -> None:
        node = getattr(access, "node", None)
        scope = getattr(access, "scope", None)
        use_idx = self.owner.get(id(node))
        if use_idx is None or scope is None:
            return
        if isinstance(node, cst.Name):
            names = [node.value]
        elif isinstance(node, cst.Attribute):
            text = dotted_text(node)
            names = [text, text.split(".")[0]] if text else []
        elif isinstance(node, cst.SimpleString):
            names = IDENT.findall(
                node.evaluated_value if isinstance(node.evaluated_value, str) else ""
            )
        else:
            return
        for name in names:
            for assignment in scope[name]:
                if not isinstance(assignment.scope, GlobalScope):
                    continue
                def_idx = self.owner.get(id(getattr(assignment, "node", None)))
                if def_idx is not None and def_idx != use_idx:
                    self.uses[use_idx].add((assignment.name, def_idx))

    def defining(self, name: str) -> list[int]:
        return [i for i, stmt in enumerate(self.module.body) if name in stmt_names(stmt)]


class _TopLevelNames(cst.CSTVisitor):
    """Names bound at module level, without entering functions, classes or comprehensions."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def _target(self, node: cst.CSTNode) -> None:
        if isinstance(node, cst.Name):
            self.names.add(node.value)
        elif isinstance(node, (cst.Tuple, cst.List)):
            for element in node.elements:
                self._target(element.value)
        elif isinstance(node, cst.StarredElement):
            self._target(node.value)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self.names.add(node.name.value)
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self.names.add(node.name.value)
        return False

    def visit_Lambda(self, node: cst.Lambda) -> bool:
        return False

    def visit_AssignTarget(self, node: cst.AssignTarget) -> bool:
        self._target(node.target)
        return True

    def visit_AnnAssign(self, node: cst.AnnAssign) -> bool:
        self._target(node.target)
        return True

    def visit_AugAssign(self, node: cst.AugAssign) -> bool:
        self._target(node.target)
        return True

    def visit_For(self, node: cst.For) -> bool:
        self._target(node.target)
        return True

    def visit_AsName(self, node: cst.AsName) -> bool:
        self._target(node.name)
        return True

    def visit_ImportAlias(self, node: cst.ImportAlias) -> bool:
        if node.asname is None:
            text = dotted_text(node.name)
            if text:
                self.names.add(text.split(".")[0])
        return True

    def visit_ListComp(self, node: cst.ListComp) -> bool:
        return False

    def visit_SetComp(self, node: cst.SetComp) -> bool:
        return False

    def visit_DictComp(self, node: cst.DictComp) -> bool:
        return False

    def visit_GeneratorExp(self, node: cst.GeneratorExp) -> bool:
        return False


def top_level_names(module: cst.Module) -> set[str]:
    visitor = _TopLevelNames()
    module.visit(visitor)
    return visitor.names


class _GlobalNames(cst.CSTVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Global(self, node: cst.Global) -> bool:
        self.names.update(item.name.value for item in node.names)
        return False


def check_globals(path: str, text: str, problems: list[str]) -> None:
    """A ``global`` name must be bound at module level in the file that declares it."""
    if "global " not in text:
        return
    module = cst.parse_module(text)
    visitor = _GlobalNames()
    module.visit(visitor)
    for name in sorted(visitor.names - top_level_names(module)):
        problems.append(f"{path}: `global {name}` but {name} is not defined in this module")


def insert_position(body: Sequence[cst.CSTNode]) -> int:
    last = -1
    for i, stmt in enumerate(body):
        if is_import_line(stmt):
            last = i
    if last >= 0:
        return last + 1
    pos = 0
    while pos < len(body) and (is_docstring(body[pos]) or is_future(body[pos])):
        pos += 1
    return pos


def add_imports(module: cst.Module, lines: Sequence[cst.SimpleStatementLine]) -> cst.Module:
    if not lines:
        return module
    body = list(module.body)
    pos = insert_position(body)
    body[pos:pos] = lines
    return module.with_changes(body=body)


def future_line() -> cst.SimpleStatementLine:
    names = [cst.ImportAlias(name=cst.Name("annotations"))]
    return cst.SimpleStatementLine(
        body=[cst.ImportFrom(module=cst.Name("__future__"), names=names)]
    )


def add_future(module: cst.Module) -> cst.Module:
    body = list(module.body)
    pos = 1 if body and is_docstring(body[0]) else 0
    body.insert(pos, future_line())
    return module.with_changes(body=body)


def import_line(
    module: str, name: str | None = None, asname: str | None = None
) -> cst.SimpleStatementLine:
    """``import module [as x]`` or ``from module import name [as x]``."""
    alias = cst.AsName(name=cst.Name(asname)) if asname else None
    stmt: cst.BaseSmallStatement
    if name is None:
        stmt = cst.Import(names=[cst.ImportAlias(name=make_dotted(module), asname=alias)])
    else:
        stmt = cst.ImportFrom(
            module=make_dotted(module), names=[cst.ImportAlias(name=cst.Name(name), asname=alias)]
        )
    return cst.SimpleStatementLine(body=[stmt])


def resolve_from(node: cst.ImportFrom, package: Sequence[str]) -> str | None:
    """Absolute module of a ``from`` import, or None when a relative one leaves the package."""
    base = dotted_text(node.module) or ""
    level = len(node.relative)
    if level == 0:
        return base
    if level - 1 > len(package):
        return None
    anchor = list(package[: len(package) - (level - 1)])
    return ".".join([*anchor, base] if base else anchor)


def package_parts(path: str) -> list[str]:
    parts = module_of_path(path).split(".")
    return parts if path.endswith("__init__.py") else parts[:-1]


# --------------------------------------------------------------------------- per-file scan


@dataclasses.dataclass
class Scan:
    """Module aliases and names a file binds from modules that lose definitions."""

    alias_of: dict[str, str] = dataclasses.field(default_factory=dict)
    top_level: set[str] = dataclasses.field(default_factory=set)
    name_from: dict[str, tuple[str, str]] = dataclasses.field(default_factory=dict)
    names: set[str] = dataclasses.field(default_factory=set)
    used: dict[str, set[str]] = dataclasses.field(default_factory=lambda: defaultdict(set))
    bad: list[str] = dataclasses.field(default_factory=list)


class _Scanner(cst.CSTVisitor):
    def __init__(self, rn: RenameSet, package: Sequence[str]) -> None:
        self.rn = rn
        self.package = package
        self.scan = Scan()
        self.depth = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self.depth += 1
        return True

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.depth -= 1

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self.depth += 1
        return True

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self.depth -= 1

    def visit_Name(self, node: cst.Name) -> bool:
        self.scan.names.add(node.value)
        return False

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        value = node.value
        if isinstance(value, cst.Name):
            module = self.scan.alias_of.get(value.value)
            if module in self.rn.defs and node.attr.value in self.rn.defs[module]:
                self.scan.used[module].add(node.attr.value)
        node.value.visit(self)
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        module = resolve_from(node, self.package)
        if module is None or isinstance(node.names, cst.ImportStar):
            return False
        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            local = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else alias.name.value
            )
            self.scan.names.add(local)
            full = f"{module}.{alias.name.value}"
            if full in self.rn.known:
                self.scan.alias_of[local] = full
                if self.depth == 0:
                    self.scan.top_level.add(local)
            elif module in self.rn.defs:
                self.scan.name_from[local] = (module, alias.name.value)
        return False

    def visit_Import(self, node: cst.Import) -> bool:
        for alias in node.names:
            name = dotted_text(alias.name)
            if name is None:
                continue
            if alias.asname and isinstance(alias.asname.name, cst.Name):
                self.scan.names.add(alias.asname.name.value)
                if name in self.rn.known:
                    self.scan.alias_of[alias.asname.name.value] = name
                    if self.depth == 0:
                        self.scan.top_level.add(alias.asname.name.value)
            elif name in self.rn.defs:
                self.scan.bad.append(
                    f"`import {name}` without an alias: use `from ... import` or `as`"
                )
        return False

    def visit_Call(self, node: cst.Call) -> bool:
        target = setattr_target(node, self.scan.alias_of, self.rn)
        if target is not None:
            self.scan.used[target[0]].add(target[1])
        return True


def setattr_target(
    node: cst.Call, alias_of: dict[str, str], rn: RenameSet
) -> tuple[str, str] | None:
    """``(module, name)`` for ``setattr(alias, "name", ...)``-style calls on a module alias."""
    func = node.func
    called = func.attr.value if isinstance(func, cst.Attribute) else getattr(func, "value", "")
    if called not in SETATTR_NAMES or len(node.args) < 2:
        return None
    first, second = node.args[0].value, node.args[1].value
    if not (isinstance(first, cst.Name) and isinstance(second, cst.SimpleString)):
        return None
    module = alias_of.get(first.value)
    value = second.evaluated_value
    if module in rn.defs and isinstance(value, str) and value in rn.defs[module]:
        return module, value
    return None


def scan_module(module: cst.Module, rn: RenameSet, package: Sequence[str]) -> Scan:
    scanner = _Scanner(rn, package)
    module.visit(scanner)
    return scanner.scan


def dest_aliases(scan: Scan, rn: RenameSet) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Local name per destination module, and the destinations that need a new import per source."""
    underscore = any(a.startswith("_") for a, m in scan.alias_of.items() if m in rn.defs)
    reuse: dict[str, str] = {}
    same: dict[str, str] = {}
    for local, module in scan.alias_of.items():
        final = rn.map_module(module) or module
        same.setdefault(final, local)
        if local in scan.top_level:
            reuse.setdefault(final, local)
    taken = set(scan.names)
    alias: dict[str, str] = {}
    needs: dict[str, list[str]] = defaultdict(list)
    for source in sorted(scan.used):
        for name in sorted(scan.used[source]):
            dest = rn.defs[source][name]
            if dest in alias:
                continue
            if dest in reuse:
                alias[dest] = reuse[dest]
                continue
            parent, _, last = dest.rpartition(".")
            lead = "_" if underscore else ""
            choices = [f"{lead}{last}", f"{lead}{parent.rpartition('.')[2]}_{last}"]
            if dest in same:
                choices.insert(0, same[dest])
            pick = next((c for c in choices if c not in taken or c == same.get(dest)), None)
            if pick is None:
                scan.bad.append(f"no free local name for {dest}")
                continue
            taken.add(pick)
            alias[dest] = pick
            needs[source].append(dest)
    return alias, needs


# --------------------------------------------------------------------------- python rewrite


class Rewriter(cst.CSTTransformer):
    """Rewrite one file's imports, module-alias uses and dotted strings."""

    def __init__(self, rn: RenameSet, scan: Scan, package: Sequence[str], moving: bool) -> None:
        super().__init__()
        self.rn = rn
        self.scan = scan
        self.package = package
        self.moving = moving
        self.alias, self.needs = dest_aliases(scan, rn)
        self.problems: list[str] = list(scan.bad)
        self._dotted: dict[int, str] = {}
        self._inner: set[int] = set()

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        return False

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        if id(node) in self._inner:
            return True
        text = dotted_text(node)
        if text and text.startswith(PACKAGE + "."):
            new = self.rn.rewrite_dotted(text)
            if new and new != text:
                self._dotted[id(node)] = new
                inner = node.value
                while isinstance(inner, cst.Attribute):
                    self._inner.add(id(inner))
                    inner = inner.value
        return True

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if id(original_node) in self._dotted:
            return make_dotted(self._dotted[id(original_node)])
        if id(original_node) in self._inner:
            return updated_node
        value = updated_node.value
        if isinstance(value, cst.Name):
            module = self.scan.alias_of.get(value.value)
            if module in self.rn.defs and updated_node.attr.value in self.rn.defs[module]:
                dest = self.rn.defs[module][updated_node.attr.value]
                if dest in self.alias:
                    return updated_node.with_changes(value=cst.Name(self.alias[dest]))
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        target = setattr_target(original_node, self.scan.alias_of, self.rn)
        if target is None:
            return updated_node
        dest = self.rn.defs[target[0]][target[1]]
        if dest not in self.alias:
            return updated_node
        first = updated_node.args[0].with_changes(value=cst.Name(self.alias[dest]))
        return updated_node.with_changes(args=[first, *updated_node.args[1:]])

    def leave_SimpleString(
        self, original_node: cst.SimpleString, updated_node: cst.SimpleString
    ) -> cst.BaseExpression:
        raw = updated_node.value
        if re.match(r"[A-Za-z]*[fFbB][A-Za-z]*['\"]", raw):
            return updated_node
        value = updated_node.evaluated_value
        if not isinstance(value, str):
            return updated_node
        if DOTTED_STRING.fullmatch(value):
            head = re.split(r"[:]", value, maxsplit=1)
            new = self.rn.rewrite_dotted(head[0])
            if new and new != head[0]:
                return updated_node.with_changes(value=raw.replace(head[0], new, 1))
        elif f"{SRC_PREFIX}" in value:
            new_value = rewrite_paths(value, self.rn, {})
            if new_value != value:
                return updated_node.with_changes(value=raw.replace(value, new_value, 1))
        return updated_node

    def _dest_imports(self, source: str) -> list[cst.SimpleStatementLine]:
        lines = []
        for dest in self.needs.get(source, []):
            parent, _, last = dest.rpartition(".")
            local = self.alias[dest]
            lines.append(import_line(parent, last, local if local != last else None))
        return lines

    def _import_from(self, node: cst.ImportFrom) -> list[cst.SimpleStatementLine] | None:
        module = resolve_from(node, self.package)
        if module is None:
            return None
        relative = len(node.relative) > 0
        if isinstance(node.names, cst.ImportStar):
            if module in self.rn.defs:
                self.problems.append(f"`from {module} import *` cannot be split")
                return None
            new = self.rn.map_module(module)
            if new is None and not (relative and self.moving):
                return None
            return [
                cst.SimpleStatementLine(
                    body=[node.with_changes(module=make_dotted(new or module), relative=[])]
                )
            ]
        groups: dict[str, list[cst.ImportAlias]] = {}
        changed = False
        extra: list[cst.SimpleStatementLine] = []
        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            name = alias.name.value
            asname = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else None
            )
            full = f"{module}.{name}"
            target, item_name, item_as = module, name, asname
            moved_module = self.rn.map_module(full)
            if moved_module is not None:
                target, _, item_name = moved_module.rpartition(".")
                item_as = asname or (name if item_name != name else None)
                changed = True
            elif name in self.rn.defs.get(module, {}):
                target = self.rn.defs[module][name]
                changed = True
            elif (new_module := self.rn.map_module(module)) is not None:
                target = new_module
                changed = True
            if full in self.rn.defs:
                extra.extend(self._dest_imports(full))
            new_alias = cst.ImportAlias(
                name=cst.Name(item_name),
                asname=cst.AsName(name=cst.Name(item_as)) if item_as else None,
            )
            groups.setdefault(target, []).append(new_alias)
        if not changed and not (relative and self.moving):
            return None if not extra else [cst.SimpleStatementLine(body=[node]), *extra]
        lines: list[cst.SimpleStatementLine] = []
        for target, aliases in groups.items():
            keep_relative = relative and target == module and not self.moving
            lines.append(
                cst.SimpleStatementLine(
                    body=[
                        cst.ImportFrom(
                            module=node.module if keep_relative else make_dotted(target),
                            relative=node.relative if keep_relative else [],
                            names=aliases,
                        )
                    ]
                )
            )
        return lines + extra

    def _import(self, node: cst.Import) -> list[cst.SimpleStatementLine]:
        extra: list[cst.SimpleStatementLine] = []
        for alias in node.names:
            name = dotted_text(alias.name)
            if name and name in self.rn.defs and alias.asname:
                extra.extend(self._dest_imports(name))
        return extra

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.BaseStatement | cst.FlattenSentinel[cst.BaseStatement] | cst.RemovalSentinel:
        if len(original_node.body) != 1:
            return updated_node
        stmt = original_node.body[0]
        lines: list[cst.SimpleStatementLine] | None
        if isinstance(stmt, cst.ImportFrom):
            lines = self._import_from(stmt)
        elif isinstance(stmt, cst.Import):
            extra = self._import(stmt)
            lines = [updated_node, *extra] if extra else None
        else:
            return updated_node
        if lines is None:
            return updated_node
        first = (
            lines[0].with_changes(
                leading_lines=original_node.leading_lines,
                trailing_whitespace=original_node.trailing_whitespace,
            )
            if lines[0] is not updated_node
            else lines[0]
        )
        merged = [first, *lines[1:]]
        return merged[0] if len(merged) == 1 else cst.FlattenSentinel(merged)


def rewrite_python(
    text: str, rn: RenameSet, context_path: str, moving: bool, problems: list[str]
) -> str:
    try:
        module = cst.parse_module(text)
    except cst.ParserSyntaxError as exc:
        problems.append(f"{context_path}: cannot parse ({exc.message})")
        return text
    package = package_parts(context_path)
    scan = scan_module(module, rn, package)
    rewriter = Rewriter(rn, scan, package, moving)
    new = module.visit(rewriter)
    problems.extend(f"{context_path}: {p}" for p in rewriter.problems)
    return new.code


# --------------------------------------------------------------------------- text rewrite


def rewrite_paths(text: str, rn: RenameSet, file_moves: dict[str, str]) -> str:
    def swap(match: re.Match[str]) -> str:
        token, name = match.group(1), (match.group(2) or "")[2:]
        found = _new_path_token(token, name, rn, file_moves)
        return match.group(0) if found is None else found + (f"::{name}" if name else "")

    return PATH_TOKEN.sub(swap, text)


def _new_path_token(token: str, name: str, rn: RenameSet, file_moves: dict[str, str]) -> str | None:
    if not name and token in file_moves:
        return file_moves[token]
    match = re.fullmatch(r"((?:src/)?docket/)?(.*)\.py", token)
    if match is None:
        return None
    prefix, rel = match.group(1) or "", match.group(2)
    if not prefix and "/" not in rel:
        return None
    package = rel.endswith("__init__")
    dotted = ".".join([PACKAGE, *rel.split("/")])
    if package:
        dotted = dotted.removesuffix(".__init__")
    new = rn.defs.get(dotted, {}).get(name) if name else rn.map_module(dotted)
    if new is None or new == dotted:
        return None
    new_rel = "/".join(new.split(".")[1:])
    new_rel = f"{new_rel}/__init__" if package else new_rel
    return f"{prefix}{new_rel}.py"


def rewrite_text(text: str, rn: RenameSet, file_moves: dict[str, str]) -> str:
    def dotted(match: re.Match[str]) -> str:
        return rn.rewrite_dotted(match.group(0)) or match.group(0)

    return DOTTED_TOKEN.sub(dotted, rewrite_paths(text, rn, file_moves))


# --------------------------------------------------------------------------- definitions


def _is_module_file(dotted: str, files: dict[str, str]) -> str | None:
    for candidate in (path_of_module(dotted), path_of_module(dotted, package=True)):
        if candidate in files:
            return candidate
    return None


def _package_children(dotted: str, files: dict[str, str]) -> list[str]:
    folder = path_of_module(dotted, package=True).removesuffix("__init__.py")
    return [p for p in files if p.startswith(folder) and p.endswith(".py")]


def plan_modules(tree: Tree, mapping: Mapping, problems: list[str]) -> dict[str, str]:
    """Old path to new path for every file a module or package move carries."""
    renames: dict[str, str] = {}
    for move in mapping.modules:
        old_file = _is_module_file(move.src, tree.files)
        if old_file is None:
            if not _is_module_file(move.dst, tree.files):
                problems.append(
                    f"module {move.src}: not found, and {move.dst} does not exist either"
                )
            continue
        sources = (
            _package_children(move.src, tree.files)
            if old_file.endswith("__init__.py")
            else [old_file]
        )
        for path in sources:
            rest = module_of_path(path)[len(move.src) :]
            package = path.endswith("__init__.py")
            new = path_of_module(move.dst + rest, package=package)
            if new in tree.files and new not in renames.values() and new != path:
                problems.append(f"module {move.src}: {new} already exists")
            renames[path] = new
    chained = sorted(set(renames) & set(renames.values()))
    if chained:
        problems.append(f"a module move lands on a file another move vacates: {chained}")
    return renames


def _module_body(tree: Tree, path: str) -> cst.Module:
    return cst.parse_module(tree.files[path])


def _copy_import(
    module: cst.Module, def_idx: int, name: str, package: Sequence[str]
) -> cst.SimpleStatementLine | None:
    node = small(module.body[def_idx])
    if isinstance(node, cst.Import):
        for alias in node.names:
            text = dotted_text(alias.name)
            if text is None:
                continue
            local = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else text
            )
            if name in (local, text, text.split(".")[0]):
                return cst.SimpleStatementLine(
                    body=[cst.Import(names=[alias.with_changes(comma=cst.MaybeSentinel.DEFAULT)])]
                )
    if isinstance(node, cst.ImportFrom) and not isinstance(node.names, cst.ImportStar):
        base = resolve_from(node, package)
        if base is None:
            return None
        for alias in node.names:
            local = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else getattr(alias.name, "value", "")
            )
            if local == name:
                return cst.SimpleStatementLine(
                    body=[
                        cst.ImportFrom(
                            module=make_dotted(base),
                            names=[alias.with_changes(comma=cst.MaybeSentinel.DEFAULT)],
                        )
                    ]
                )
    return None


def import_bindings(stmt: cst.CSTNode) -> dict[str, str]:
    """Local name to what it imports, for one import statement."""
    node = small(stmt)
    out: dict[str, str] = {}
    if isinstance(node, cst.Import):
        for alias in node.names:
            text = dotted_text(alias.name) or ""
            if alias.asname and isinstance(alias.asname.name, cst.Name):
                out[alias.asname.name.value] = f"import {text}"
            else:
                out[text.split(".")[0]] = f"import {text.split('.')[0]}"
    elif isinstance(node, cst.ImportFrom) and not isinstance(node.names, cst.ImportStar):
        base = ("." * len(node.relative)) + (dotted_text(node.module) or "")
        for alias in node.names:
            name = dotted_text(alias.name) or ""
            local = (
                alias.asname.name.value
                if alias.asname and isinstance(alias.asname.name, cst.Name)
                else name
            )
            out[local] = f"from {base} import {name}"
    return out


def _dest_imports(dest: cst.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for stmt in dest.body:
        if isinstance(stmt, cst.SimpleStatementLine) and is_import_line(stmt):
            out.update(import_bindings(stmt))
    return out


def _import_key(line: cst.SimpleStatementLine) -> str:
    return cst.Module(body=[line]).code.strip()


def _strip_leading_blanks(lines: Sequence[cst.EmptyLine]) -> list[cst.EmptyLine]:
    out = list(lines)
    while out and out[0].comment is None:
        out.pop(0)
    return out


def move_definitions(
    tree: Tree,
    move: DefMove,
    origin: tuple[str, str | None],
    dest_old_path: str,
    problems: list[str],
) -> None:
    source_old, src_path = origin
    if src_path is None:
        problems.append(f"definition source {source_old}: not found")
        return
    source = _module_body(tree, src_path)
    refs = ModuleRefs(source)
    dest_text = tree.files.get(dest_old_path)
    dest = cst.parse_module(dest_text) if dest_text is not None else None
    dest_refs = ModuleRefs(dest) if dest is not None else None
    dest_bound = top_level_names(dest) if dest is not None else set()
    pending: list[tuple[str, int]] = []
    for name in move.names:
        found = refs.defining(name)
        if len(found) > 1:
            problems.append(f"{source_old}.{name}: defined {len(found)} times")
        elif found:
            if name in dest_bound:
                problems.append(f"{move.dst}.{name}: the name is already bound in the destination")
            pending.append((name, found[0]))
        elif not (dest_refs is not None and dest_refs.defining(name)):
            problems.append(f"{source_old}.{name}: not found in the source or the destination")
    if not pending:
        return
    moved_idx = {i for _, i in pending}
    moved_names = {n for n, _ in pending}
    package = package_parts(src_path)
    dest_dotted = move.dst
    needed: list[cst.SimpleStatementLine] = []
    seen_keys: set[str] = set()
    for idx in sorted(moved_idx):
        for name, def_idx in sorted(refs.uses[idx]):
            if def_idx in moved_idx:
                continue
            line = _copy_import(source, def_idx, name, package)
            if line is None:
                if name not in stmt_names(source.body[def_idx]):
                    continue
                line = import_line(source_old, name)
            key = _import_key(line)
            if key in seen_keys or f"from {dest_dotted} import" in key:
                continue
            seen_keys.add(key)
            needed.append(line)
    future = any(is_future(s) for s in source.body)
    back = sorted(
        {
            name
            for idx, uses in refs.uses.items()
            if idx not in moved_idx
            for name, def_idx in uses
            if def_idx in moved_idx and name in moved_names
        }
    )
    kept = [s for i, s in enumerate(source.body) if i not in moved_idx]
    new_source = add_imports(
        source.with_changes(body=kept), [import_line(dest_dotted, n) for n in back]
    )
    tree.files[src_path] = new_source.code
    chunk = [source.body[i] for _, i in pending]
    lead = _strip_leading_blanks(getattr(chunk[0], "leading_lines", ()))
    chunk[0] = chunk[0].with_changes(leading_lines=[cst.EmptyLine(), cst.EmptyLine(), *lead])
    if dest is None:
        head = [future_line()] if future else []
        for line in needed:
            clash = top_level_names(cst.Module(body=[line])) & moved_names
            if clash:
                problems.append(f"{move.dst}: {sorted(clash)} is both imported and moved there")
        out = cst.Module(body=[*head, *needed, *chunk])
    else:
        have = _dest_imports(dest)
        fresh = []
        for line in needed:
            wanted = import_bindings(line)
            if all(have.get(local) == what for local, what in wanted.items()):
                continue
            clash = {n for n, what in wanted.items() if have.get(n, what) != what}
            clash |= set(wanted) & ((dest_bound - set(have)) | moved_names)
            if clash:
                problems.append(
                    f"{move.dst}: {sorted(clash)} imported for {sorted(moved_names)} is already "
                    "bound there by something else"
                )
            fresh.append(line)
        out = add_imports(dest, fresh)
        if future and not any(is_future(s) for s in dest.body):
            out = add_future(out)
        out = out.with_changes(body=[*out.body, *chunk])
    tree.files[dest_old_path] = out.code


# --------------------------------------------------------------------------- tests


@dataclasses.dataclass
class TestPlan:
    __test__ = False
    new_files: dict[str, str] = dataclasses.field(default_factory=dict)
    renames: dict[str, str] = dataclasses.field(default_factory=dict)
    origin: dict[str, str] = dataclasses.field(default_factory=dict)
    homes: dict[str, dict[str, str]] = dataclasses.field(default_factory=lambda: defaultdict(dict))
    landed: dict[str, dict[str, set[str]]] = dataclasses.field(default_factory=dict)
    pseudo: set[str] = dataclasses.field(default_factory=set)


def _is_subject(node: cst.BaseSmallStatement) -> cst.Assign | None:
    if not (isinstance(node, cst.Assign) and len(node.targets) == 1):
        return None
    target = node.targets[0].target
    return node if isinstance(target, cst.Name) and target.value == "SUBJECT" else None


def read_subject(module: cst.Module) -> str | None:
    for stmt in module.body:
        node = small(stmt)
        assign = _is_subject(node) if node is not None else None
        if assign is not None and isinstance(assign.value, cst.SimpleString):
            value = assign.value.evaluated_value
            return value if isinstance(value, str) else None
    return None


def set_subject(module: cst.Module, subject: str) -> cst.Module:
    body = list(module.body)
    for i, stmt in enumerate(body):
        node = small(stmt)
        assign = _is_subject(node) if node is not None else None
        if assign is not None and isinstance(stmt, cst.SimpleStatementLine):
            new = assign.with_changes(value=cst.SimpleString(f'"{subject}"'))
            body[i] = stmt.with_changes(body=[new])
    return module.with_changes(body=body)


def mirror_path(subject: str, suffix: str) -> str:
    parts = subject.split(".")[1:]
    return "/".join([UNIT_DIR.rstrip("/"), *parts[:-1], f"test_{parts[-1]}{suffix}.py"])


def split_name(path: str) -> tuple[str, str]:
    stem = Path(path).stem.removeprefix("test_")
    head, _, tail = stem.partition("__")
    return head, f"__{tail}" if tail else ""


class _Refs(cst.CSTVisitor):
    """Symbols of modules that lose definitions a subtree touches, with the parameters it names."""

    def __init__(self, scan: Scan, rn: RenameSet) -> None:
        self.scan = scan
        self.rn = rn
        self.hits: list[tuple[str, str | None]] = []
        self.params: set[str] = set()

    def visit_Name(self, node: cst.Name) -> bool:
        if node.value in self.scan.name_from:
            self.hits.append(self.scan.name_from[node.value])
        elif self.scan.alias_of.get(node.value) in self.rn.defs:
            self.hits.append((self.scan.alias_of[node.value], None))
        return False

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        value = node.value
        if isinstance(value, cst.Name) and self.scan.alias_of.get(value.value) in self.rn.defs:
            self.hits.append((self.scan.alias_of[value.value], node.attr.value))
            return False
        return True

    def visit_Call(self, node: cst.Call) -> bool:
        target = setattr_target(node, self.scan.alias_of, self.rn)
        if target is None:
            return True
        self.hits.append(target)
        for arg in node.args[1:]:
            arg.visit(self)
        return False

    def visit_SimpleString(self, node: cst.SimpleString) -> bool:
        value = node.evaluated_value
        if isinstance(value, str) and DOTTED_STRING.fullmatch(value):
            owner, _, name = value.partition(":")[0].rpartition(".")
            if owner in self.rn.defs:
                self.hits.append((owner, name))
        return False

    def visit_Param(self, node: cst.Param) -> bool:
        self.params.add(node.name.value)
        return True


def _touches(stmt: cst.CSTNode, scan: Scan, rn: RenameSet) -> Counter[str]:
    """Final module of each symbol the statement touches, counted."""
    refs = _Refs(scan, rn)
    stmt.visit(refs)
    out: Counter[str] = Counter()
    for module, name in refs.hits:
        moved = rn.defs[module].get(name) if name is not None else None
        out[moved or rn.modules.get(module, module)] += 1
    return out


def _params(stmt: cst.CSTNode, scan: Scan, rn: RenameSet) -> set[str]:
    refs = _Refs(scan, rn)
    stmt.visit(refs)
    return refs.params


def _is_unit(stmt: cst.CSTNode) -> bool:
    if isinstance(stmt, cst.FunctionDef):
        return stmt.name.value.startswith("test_")
    return isinstance(stmt, cst.ClassDef) and stmt.name.value.startswith("Test")


def _decorator_code(stmt: cst.CSTNode) -> list[str]:
    if not isinstance(stmt, (cst.FunctionDef, cst.ClassDef)):
        return []
    return [cst.Module(body=[]).code_for_node(d.decorator) for d in stmt.decorators]


def _is_helper(stmt: cst.CSTNode) -> bool:
    """A fixture, helper or constant a part keeps only when it uses it."""
    if _is_unit(stmt) or is_import_line(stmt) or is_docstring(stmt):
        return False
    names = stmt_names(stmt)
    return bool(names) and names[0] not in {"SUBJECT", "pytestmark", "__all__"}


def plan_tests(tree: Tree, rn: RenameSet, problems: list[str], notes: list[str]) -> TestPlan:
    plan = TestPlan()
    taken = {tree.final_path(p) for p in tree.files}
    for path in sorted(tree.files):
        if not (
            path.startswith(UNIT_DIR)
            and path.endswith(".py")
            and Path(path).name.startswith("test_")
        ):
            continue
        try:
            module = cst.parse_module(tree.files[path])
        except cst.ParserSyntaxError:
            continue
        subject = read_subject(module)
        if subject is None or not subject.startswith(PACKAGE + "."):
            continue
        _, suffix = split_name(path)
        if path != mirror_path(subject, suffix):
            continue
        if subject not in rn.defs:
            final_subject = rn.map_module(subject) or subject
            if final_subject != subject:
                plan.renames[path] = mirror_path(final_subject, suffix)
                taken.add(plan.renames[path])
            continue
        _plan_split(tree, rn, (path, module, subject, suffix), plan, taken, (problems, notes))
    return plan


def _group_referenced_units(
    units: Sequence[int],
    refs: ModuleRefs,
    counts: dict[int, Counter[str]],
    group: dict[str, list[int]],
    order: Sequence[str],
) -> None:
    """Units that name each other stay in one part: the one most of them touch."""
    parent = {i: i for i in units}

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i in units:
        for _, other in refs.uses.get(i, ()):
            if other in parent:
                parent[find(i)] = find(other)
    members: dict[int, list[int]] = defaultdict(list)
    for i in units:
        members[find(i)].append(i)
    where = {i: d for d, items in group.items() for i in items}
    for items in members.values():
        if len(items) < 2 or len({where[i] for i in items}) < 2:
            continue
        total: Counter[str] = Counter()
        for i in items:
            total.update(counts[i])
        pick = max(order, key=lambda d: (total[d], -order.index(d)))
        for i in items:
            group[where[i]].remove(i)
            group[pick].append(i)


def _plan_split(
    tree: Tree,
    rn: RenameSet,
    source: tuple[str, cst.Module, str, str],
    plan: TestPlan,
    taken: set[str],
    reports: tuple[list[str], list[str]],
) -> None:
    path, module, subject, suffix = source
    final_subject = rn.map_module(subject) or subject
    problems, notes = reports
    scan = scan_module(module, rn, package_parts(path))
    refs = ModuleRefs(module)
    body = list(module.body)
    units = [i for i, s in enumerate(body) if _is_unit(s)]
    counts = {i: _touches(body[i], scan, rn) for i in units}
    order: list[str] = []
    for i in units:
        for dest, _ in counts[i].most_common():
            if dest not in order:
                order.append(dest)
    if not order:
        if final_subject != subject:
            plan.renames[path] = mirror_path(final_subject, suffix)
        return
    primary = final_subject if final_subject in order else order[0]
    group: dict[str, list[int]] = {d: [] for d in order}
    for i in units:
        ranked = sorted(counts[i], key=lambda d: (-counts[i][d], order.index(d)))
        if len(ranked) > 1:
            notes.append(
                f"{path}: {_unit_name(body[i])} touches {sorted(ranked)}; placed with {ranked[0]}"
            )
        group[ranked[0] if ranked else primary].append(i)
    _group_referenced_units(units, refs, counts, group, order)
    if order == [final_subject] and mirror_path(final_subject, suffix) == path:
        return
    names: dict[str, int] = {}
    for i, stmt in enumerate(body):
        for n in stmt_names(stmt):
            names.setdefault(n, i)
    helpers = {i for i, s in enumerate(body) if _is_helper(s)}
    keep_always = [i for i in range(len(body)) if i not in units and i not in helpers]

    def closure(roots: Sequence[int]) -> set[int]:
        out: set[int] = set()
        stack = [
            *roots,
            *(i for i in helpers if any("autouse=True" in c for c in _decorator_code(body[i]))),
        ]
        while stack:
            i = stack.pop()
            if i in out:
                continue
            out.add(i)
            stack.extend(d for _, d in refs.uses.get(i, ()) if d in helpers)
            wanted = _params(body[i], scan, rn)
            for code in _decorator_code(body[i]):
                if "usefixtures" in code:
                    wanted.update(IDENT.findall(code.split("usefixtures", 1)[1]))
            stack.extend(names[n] for n in wanted if names.get(n) in helpers)
        return out

    needs = {d: closure([*group[d], *keep_always]) for d in order}
    for i in sorted(helpers - set().union(*needs.values())):
        needs[primary].add(i)
    targets = {d: mirror_path(d, suffix) for d in order}
    if len(set(targets.values())) != len(targets):
        problems.append(f"{path}: two destinations share one test file")
        return
    claimed: set[str] = set()
    for rank, dest in enumerate(sorted(order, key=lambda d: (d != final_subject, order.index(d)))):
        target = targets[dest]
        keep = needs[dest] | set(group[dest]) | set(keep_always)
        part = set_subject(
            module.with_changes(body=[s for i, s in enumerate(body) if i in keep]), dest
        )
        if rank == 0 and target != path:
            plan.renames[path] = target
            taken.add(target)
            tree.files[path] = part.code
        elif target == path:
            tree.files[path] = part.code
        else:
            key = target
            if target in taken:
                key = f"{target}.part{len(plan.pseudo) + 1}.py"
                plan.pseudo.add(key)
                plan.renames[key] = target
            taken.add(target)
            plan.new_files[key] = part.code
            plan.origin[key] = path
        plan.landed.setdefault(path, {})[target] = {_unit_name(body[i]) for i in group[dest]}
        for i in sorted(keep - set(units)):
            for name in stmt_names(body[i]):
                if name not in claimed:
                    claimed.add(name)
                    if target != path:
                        plan.homes[module_of_path(path)][name] = module_of_path(target)


def _unit_name(stmt: cst.CSTNode) -> str:
    return stmt.name.value if isinstance(stmt, (cst.FunctionDef, cst.ClassDef)) else "?"


# --------------------------------------------------------------------------- ruff


def ruff_command(root: Path) -> list[str]:
    beside = Path(sys.executable).parent / "ruff"
    if beside.exists():
        return [str(beside)]
    found = shutil.which("ruff")
    return [found] if found else [sys.executable, "-m", "ruff"]


def run_ruff(text: str, path: str, root: Path) -> str:
    base = ruff_command(root)
    fixed = subprocess.run(
        [*base, "check", "--fix", "--quiet", "--exit-zero", "--stdin-filename", path, "-"],
        input=text,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    current = fixed.stdout if fixed.returncode == 0 and fixed.stdout else text
    done = subprocess.run(
        [*base, "format", "--stdin-filename", path, "-"],
        input=current,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    return done.stdout if done.returncode == 0 and done.stdout else current


# --------------------------------------------------------------------------- test ids


def test_ids(files: dict[str, str]) -> dict[str, set[str]]:
    """Static test ids per file: ``name`` and ``Class::name``."""
    out: dict[str, set[str]] = {}
    for path, text in files.items():
        if not (
            path.startswith("tests/")
            and Path(path).name.startswith("test_")
            and path.endswith(".py")
        ):
            continue
        try:
            module = cst.parse_module(text)
        except cst.ParserSyntaxError:
            continue
        ids: set[str] = set()
        for stmt in module.body:
            if isinstance(stmt, cst.FunctionDef) and stmt.name.value.startswith("test"):
                ids.add(stmt.name.value)
            elif isinstance(stmt, cst.ClassDef) and stmt.name.value.startswith("Test"):
                for inner in stmt.body.body:
                    if isinstance(inner, cst.FunctionDef) and inner.name.value.startswith("test"):
                        ids.add(f"{stmt.name.value}::{inner.name.value}")
        out[path] = ids
    return out


test_ids.__test__ = False  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- plan


@dataclasses.dataclass
class Plan:
    root: Path
    before: dict[str, str]
    after: dict[str, str]
    renames: dict[str, str]
    problems: list[str]
    notes: list[str]
    id_moves: dict[str, str]
    retired: list[str]

    def changes(self) -> list[tuple[str, str, str | None]]:
        """``(kind, path, old path)`` for rename, edit, create and delete."""
        out: list[tuple[str, str, str | None]] = []
        reverse = {new: old for old, new in self.renames.items()}
        for path in sorted(self.after):
            old = reverse.get(path)
            if old is not None:
                out.append(("rename", path, old))
            elif path not in self.before:
                out.append(("create", path, None))
            elif self.after[path] != self.before[path]:
                out.append(("edit", path, None))
        for path in sorted(self.before):
            if path not in self.after and path not in self.renames:
                out.append(("delete", path, None))
        return out


def _before_module_moves(name: str, mapping: Mapping) -> str:
    """The name a module has before the module moves, whichever spelling the mapping uses."""
    for move in sorted(mapping.modules, key=lambda m: -len(m.dst)):
        if name == move.dst or name.startswith(move.dst + "."):
            return move.src + name[len(move.dst) :]
    return name


def _module_file(names: Sequence[str], tree: Tree) -> str | None:
    """The first file that holds one of the module's names, as a module or as a package."""
    for name in names:
        for package in (False, True):
            path = path_of_module(name, package=package)
            if path in tree.files:
                return path
    return None


def _resolve_defs(tree: Tree, mapping: Mapping) -> list[tuple[DefMove, str, str | None, str]]:
    """Each definition move: its source's old name and file, and its destination's file."""
    out: list[tuple[DefMove, str, str | None, str]] = []
    for move in mapping.definitions:
        source_old = _before_module_moves(move.src, mapping)
        dest_old = _before_module_moves(move.dst, mapping)
        dest_path = _module_file([dest_old, move.dst], tree) or path_of_module(move.dst)
        out.append((move, source_old, _module_file([source_old, move.src], tree), dest_path))
    return out


def build_plan(root: Path, mapping: Mapping) -> Plan:
    tree = Tree(root)
    problems: list[str] = []
    notes: list[str] = []
    before_ids = test_ids(tree.files)
    known = {module_of_path(p) for p in tree.files if p.startswith(SRC_PREFIX)}
    module_renames = plan_modules(tree, mapping, problems)
    resolved = _resolve_defs(tree, mapping)
    defs: dict[str, dict[str, str]] = defaultdict(dict)
    for move, source_old, _, _ in resolved:
        for name in move.names:
            defs[source_old][name] = move.dst
    rn = RenameSet({m.src: m.dst for m in mapping.modules}, dict(defs), known)

    tests = plan_tests(tree, rn, problems, notes)
    for move, source_old, source_path, dest_path in resolved:
        move_definitions(tree, move, (source_old, source_path), dest_path, problems)
    tree.renames.update(module_renames)
    tree.renames.update(tests.renames)
    for path, text in tests.new_files.items():
        tree.files[path] = text
        tree.origin_of[path] = tests.origin[path]

    rn.modules.update(
        {
            module_of_path(old): module_of_path(new)
            for old, new in tests.renames.items()
            if old not in tests.pseudo
        }
    )
    rn.defs.update(tests.homes)
    py_before = tree.py_paths()
    for path in py_before:
        context = tree.context_path(path)
        final = tree.final_path(path)
        moving = module_of_path(context) != module_of_path(final)
        tree.files[path] = rewrite_python(tree.files[path], rn, context, moving, problems)

    merge_collisions(tree, tests, problems)
    for path in sorted(tree.files):
        if path.endswith(".py") and tree.disk.get(path) != tree.files[path]:
            check_globals(tree.final_path(path), tree.files[path], problems)
    file_moves = {k: v for k, v in tree.renames.items() if k not in tests.pseudo}
    for old, new in module_renames.items():
        file_moves[old] = new
    for path in sorted(tree.files):
        if not path.endswith(".py") and path != RETIRED_FILE:
            tree.files[path] = rewrite_text(tree.files[path], rn, file_moves)

    after = _finalize(tree)
    for cycle in import_cycles(after):
        notes.append(f"top-level import cycle of {len(cycle)} modules: {', '.join(cycle[:6])}")
    _ruff_changed(root, tree, after)
    id_map, retired = id_moves(before_ids, tree.renames, after, tests.landed)
    if retired:
        existing = tree.disk.get(RETIRED_FILE, "")
        lines = [line for line in existing.splitlines() if line]
        for entry in retired:
            if entry not in lines:
                lines.append(entry)
        after[RETIRED_FILE] = "\n".join(lines) + "\n"
    return Plan(root, dict(tree.disk), after, dict(tree.renames), problems, notes, id_map, retired)


def _canonical(stmt: cst.CSTNode) -> str:
    bare = stmt.with_changes(leading_lines=[]) if hasattr(stmt, "leading_lines") else stmt
    return cst.Module(body=[bare]).code  # type: ignore[list-item]


def merge_modules(parts: Sequence[tuple[str, str]], problems: list[str]) -> str:
    """One module from several, in order: imports unioned, equal names kept once."""
    first_path, first_text = parts[0]
    merged = cst.parse_module(first_text)
    seen: dict[str, tuple[str, str]] = {}
    imports = {
        _import_key(s)
        for s in merged.body
        if isinstance(s, cst.SimpleStatementLine) and is_import_line(s)
    }
    for stmt in merged.body:
        for name in stmt_names(stmt):
            seen.setdefault(name, (_canonical(stmt), first_path))
    fresh: list[cst.SimpleStatementLine] = []
    extra: list[cst.CSTNode] = []
    for path, text in parts[1:]:
        for stmt in cst.parse_module(text).body:
            if isinstance(stmt, cst.SimpleStatementLine) and is_import_line(stmt):
                key = _import_key(stmt)
                if key not in imports:
                    imports.add(key)
                    fresh.append(stmt.with_changes(leading_lines=[]))
                continue
            names = stmt_names(stmt)
            if is_docstring(stmt) or names[:1] == ["SUBJECT"]:
                continue
            if names:
                code = _canonical(stmt)
                if names[0] in seen:
                    other_code, other = seen[names[0]]
                    if other_code != code:
                        problems.append(f"{names[0]} differs in {other} and {path}")
                    continue
                seen[names[0]] = (code, path)
            extra.append(stmt)
    merged = add_imports(merged, fresh)
    return merged.with_changes(body=[*merged.body, *extra]).code


def merge_collisions(tree: Tree, tests: TestPlan, problems: list[str]) -> None:
    """Fold files that end at one path into the first of them; whole modules before halves."""
    groups: dict[str, list[str]] = defaultdict(list)
    for key in tree.files:
        if key.endswith(".py"):
            groups[tree.final_path(key)].append(key)
    halves = set(tests.origin) | set(tests.landed)
    for final, keys in groups.items():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: (k in halves, k))
        named = [(tree.origin_of.get(k, k), tree.files[k]) for k in keys]
        tree.files[keys[0]] = merge_modules(named, problems)
        for key in keys[1:]:
            del tree.files[key]
            tree.renames.pop(key, None)
            tree.origin_of.pop(key, None)
        if keys[0] != final:
            tree.renames[keys[0]] = final


def import_cycles(files: dict[str, str]) -> list[list[str]]:
    """Strongly connected sets of ``docket`` modules by top-level imports, largest first."""
    modules = {module_of_path(p): p for p in files if p.startswith(SRC_PREFIX)}
    edges: dict[str, set[str]] = {}
    for name, path in modules.items():
        try:
            tree = ast.parse(files[path])
        except SyntaxError:
            continue
        found: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
                found.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
        edges[name] = {m for m in found if m in modules and m != name}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(edges.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            part = []
            while True:
                w = stack.pop()
                on.discard(w)
                part.append(w)
                if w == v:
                    break
            if len(part) > 1:
                out.append(sorted(part))

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    for v in sorted(edges):
        if v not in index:
            visit(v)
    return sorted(out, key=len, reverse=True)


def _finalize(tree: Tree) -> dict[str, str]:
    after: dict[str, str] = {}
    for path, text in tree.files.items():
        final = tree.final_path(path)
        if final in after:
            raise PlanError(f"two files end at {final}")
        after[final] = text
    existing = set(after) | {tree.final_path(p) for p in tree.disk}
    for path in list(after):
        if not path.startswith(SRC_PREFIX):
            continue
        folder = Path(path).parent.as_posix()
        while folder.startswith(SRC_PREFIX.rstrip("/")) and folder != SRC_PREFIX.rstrip("/"):
            init = f"{folder}/__init__.py"
            if init not in existing and not (tree.root / init).exists():
                after[init] = ""
                existing.add(init)
            folder = Path(folder).parent.as_posix()
    return after


def _ruff_changed(root: Path, tree: Tree, after: dict[str, str]) -> None:
    reverse = {new: old for old, new in tree.renames.items()}
    for path in sorted(after):
        if not path.endswith(".py"):
            continue
        old = reverse.get(path, path)
        if tree.disk.get(old) == after[path] or not after[path]:
            continue
        after[path] = run_ruff(after[path], path, root)


def id_moves(
    before: dict[str, set[str]],
    renames: dict[str, str],
    after: dict[str, str],
    landed: dict[str, dict[str, set[str]]],
) -> tuple[dict[str, str], list[str]]:
    """Where each test id went, and the ids that have no counterpart after the move."""
    now = test_ids(after)
    moves: dict[str, str] = {}
    retired: list[str] = []
    for path, ids in before.items():
        final = renames.get(path, path)
        homes = [final] + [t for t in landed.get(path, {}) if t != final]
        for test in sorted(ids):
            found = next((h for h in homes if test in now.get(h, set())), None)
            if found is None:
                retired.append(f"retired: {path}::{test} -> ?")
            elif found != path:
                moves[f"{path}::{test}"] = f"{found}::{test}"
    return moves, retired


# --------------------------------------------------------------------------- apply


def apply_plan(plan: Plan) -> None:
    root = plan.root
    git = (root / ".git").exists()
    for old, new in sorted(plan.renames.items()):
        target = root / new
        target.parent.mkdir(parents=True, exist_ok=True)
        if (
            git
            and subprocess.run(
                ["git", "-C", str(root), "mv", old, new], capture_output=True, check=False
            ).returncode
            == 0
        ):
            continue
        shutil.move(str(root / old), str(target))
    for kind, path, _ in plan.changes():
        if kind in {"edit", "create", "rename"}:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_text(encoding="utf-8") != plan.after[path]:
                target.write_text(plan.after[path], encoding="utf-8")
        elif kind == "delete":
            (root / path).unlink()


def describe(plan: Plan) -> Iterator[str]:
    for kind, path, old in plan.changes():
        yield f"{kind:7} {old} -> {path}" if old else f"{kind:7} {path}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--map", type=Path, default=None, help=f"default: <root>/{MAP_FILE}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    map_path = args.map or root / MAP_FILE
    try:
        mapping = parse_mapping(map_path.read_text(encoding="utf-8"))
        plan = build_plan(root, mapping)
    except (PlanError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"move: {exc}", file=sys.stderr)
        return 2
    for note in plan.notes:
        print(f"note: {note}", file=sys.stderr)
    for problem in plan.problems:
        print(f"problem: {problem}", file=sys.stderr)
    if args.report is not None:
        args.report.write_text(
            json.dumps({"renames": plan.renames, "ids": plan.id_moves}, indent=2, sort_keys=True)
            + "\n"
        )
    if plan.problems:
        return 2
    changes = plan.changes()
    if args.dry_run:
        print("\n".join(describe(plan)))
        print(f"{len(changes)} change(s); nothing written")
        return 0
    if args.check:
        if changes:
            print("\n".join(describe(plan)), file=sys.stderr)
            print(f"move: {len(changes)} change(s) still to make", file=sys.stderr)
            return 1
        return 0
    apply_plan(plan)
    print(f"move: {len(changes)} change(s) applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
