#!/usr/bin/env python3
"""Measure a package's import graph, call groups, status writers and patch targets.

Reads ``src/<package>`` and ``tests/`` with ``ast`` and ``grimp`` and writes
``refactor/analysis.json`` plus ``refactor/analysis.md``. ``--metrics`` prints the nine gate
numbers as ``name=value`` lines; ``--draft-map`` writes ``refactor/target-map.toml`` from the
rules in ``docket-rules.toml`` and the call groups.

Nothing here edits ``src/`` or ``tests/``. Every claim is a count of syntax, so a number that
looks wrong is checked against the file and line it names.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
RULES_FILE = Path(__file__).with_name("docket-rules.toml")

Pairs = tuple[tuple[str, str], ...]
Scoped = tuple[ast.AST, str, bool, bool]


def _load_rules() -> tuple[Pairs, dict[str, Pairs]]:
    data = tomllib.loads(RULES_FILE.read_text(encoding="utf-8"))
    modules = tuple(sorted(data["modules"].items()))
    rules = {
        name: tuple((rx, dest) for rx, dest in table["rules"])
        for name, table in data["definitions"].items()
    }
    return modules, rules


_MODULES, _RULES = _load_rules()


@dataclass(frozen=True)
class Profile:
    """Everything that names the package under analysis; the tests swap it for a toy."""

    package: str = "docket"
    core_prefix: str = "docket.core"
    edges_prefix: str = "docket.edges"
    call_graph_modules: tuple[str, ...] = (
        "docket.core.dispatch",
        "docket.serve",
        "docket.edges.adapters.system",
    )
    hub_threshold: int = 5
    task_receivers: tuple[str, ...] = ("task", "t", "claimed")
    status_key: str = "status"
    task_marker_keys: tuple[str, ...] = ("id", "status", "hops")
    hop_marker_keys: tuple[str, ...] = ("role", "stepId")
    run_marker_key: str = "taskIds"
    generic_keys: frozenset[str] = frozenset({"id", "error", "created", "state", "status"})
    test_exclude: tuple[str, ...] = ("tests/guards/fixtures/refactor",)
    keep_modules: tuple[str, ...] = ("docket", "docket.__main__", "docket.config")
    keep_prefixes: tuple[str, ...] = ("docket.kernel",)
    module_map: Pairs = _MODULES
    definition_rules: dict[str, Pairs] = field(default_factory=lambda: dict(_RULES))


DOCKET = Profile()


@dataclass
class Mod:
    name: str
    rel: str
    is_package: bool
    tree: ast.Module
    lines: int

    @cached_property
    def scoped(self) -> list[Scoped]:
        return list(walk_scoped(self.tree))

    @cached_property
    def bound(self) -> dict[str, str]:
        return bindings(self)

    @cached_property
    def nodes(self) -> list[ast.AST]:
        return [node for node, _label, _in_func, _tc in self.scoped]


def load_modules(root: Path, profile: Profile) -> dict[str, Mod]:
    src = root / "src"
    mods: dict[str, Mod] = {}
    for path in sorted((src / profile.package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(src).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        text = path.read_text(encoding="utf-8")
        name = ".".join(parts)
        rel = path.relative_to(root).as_posix()
        mods[name] = Mod(name, rel, is_package, ast.parse(text), len(text.splitlines()))
    return mods


def _is_type_checking(test: ast.expr) -> bool:
    name = test.id if isinstance(test, ast.Name) else getattr(test, "attr", "")
    return name == "TYPE_CHECKING"


def walk_scoped(tree: ast.AST) -> Iterator[Scoped]:
    """Yield (node, scope label, in a function, in TYPE_CHECKING) for every node.

    The label is the outermost function (``Cls.meth`` for methods), else the class or the module."""

    def rec(
        node: ast.AST, label: str, in_func: bool, classes: tuple[str, ...], tc: bool
    ) -> Iterator[Scoped]:
        for child in ast.iter_child_nodes(node):
            yield child, label, in_func, tc
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = label if in_func else ".".join([*classes, child.name])
                yield from rec(child, inner, True, classes, tc)
            elif isinstance(child, ast.ClassDef):
                inner = label if in_func else child.name
                yield from rec(child, inner, in_func, (*classes, child.name), tc)
            elif isinstance(child, ast.If) and _is_type_checking(child.test):
                for part in child.body:
                    yield part, label, in_func, True
                    yield from rec(part, label, in_func, classes, True)
                for part in child.orelse:
                    yield part, label, in_func, tc
                    yield from rec(part, label, in_func, classes, tc)
            else:
                yield from rec(child, label, in_func, classes, tc)

    yield from rec(tree, "<module>", False, (), False)


def _resolve_from(mod: Mod, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    base = mod.name.split(".") if mod.is_package else mod.name.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def bindings(mod: Mod) -> dict[str, str]:
    """Local name -> dotted target for every import statement in the file, at any depth."""
    out: dict[str, str] = {}
    for node in mod.nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                root_name = a.name.split(".")[0]
                out[a.asname or root_name] = a.name if a.asname else root_name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(mod, node)
            if base is not None:
                for a in node.names:
                    out[a.asname or a.name] = f"{base}.{a.name}"
    return out


def split_target(dotted: str, modules: set[str]) -> tuple[str | None, str | None]:
    """Split ``pkg.mod.attr.more`` into (longest module prefix, remaining dotted attr or None)."""
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        head = ".".join(parts[:end])
        if head in modules:
            rest = ".".join(parts[end:])
            return head, rest or None
    return None, None


def _import_targets(mod: Mod, node: ast.Import | ast.ImportFrom, modules: set[str]) -> list[str]:
    if isinstance(node, ast.Import):
        return sorted({split_target(a.name, modules)[0] or a.name for a in node.names})
    base = _resolve_from(mod, node)
    if base is None:
        return []
    return sorted({split_target(f"{base}.{a.name}", modules)[0] or base for a in node.names})


def _in_package(name: str, profile: Profile) -> bool:
    return name == profile.package or name.startswith(profile.package + ".")


def local_imports(mod: Mod, profile: Profile, modules: set[str]) -> list[dict[str, Any]]:
    """Import statements of the package nested inside a function body."""
    out = []
    for node, label, in_func, tc in mod.scoped:
        if not (in_func and not tc and isinstance(node, ast.Import | ast.ImportFrom)):
            continue
        targets = [t for t in _import_targets(mod, node, modules) if _in_package(t, profile)]
        if targets:
            out.append(
                {"module": mod.name, "line": node.lineno, "function": label, "targets": targets}
            )
    return out


def sccs(nodes: list[str], adj: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components of size > 1, largest first (iterative Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        work = [(start, iter(sorted(adj.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(adj.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
    return sorted(result, key=lambda c: (-len(c), c))


def build_import_graph(root: Path, profile: Profile) -> Any:
    """The package's grimp graph, built against ``root/src`` even if another copy is imported."""
    import grimp

    prefix = profile.package
    saved = {k: v for k, v in sys.modules.items() if k == prefix or k.startswith(prefix + ".")}
    for key in saved:
        del sys.modules[key]
    sys.path.insert(0, str(root / "src"))
    try:
        return grimp.build_graph(
            prefix,
            include_external_packages=False,
            exclude_type_checking_imports=True,
            cache_dir=None,
        )
    finally:
        sys.path.remove(str(root / "src"))
        sys.modules.update(saved)


def import_adjacency(
    graph: Any, local_lines: dict[str, set[int]]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(top-level edges, all edges) as importer -> imported sets."""
    top: dict[str, set[str]] = defaultdict(set)
    full: dict[str, set[str]] = defaultdict(set)
    for importer in sorted(graph.modules):
        for imported in sorted(graph.find_modules_directly_imported_by(importer)):
            full[importer].add(imported)
            details = graph.get_import_details(importer=importer, imported=imported)
            if any(d["line_number"] not in local_lines.get(importer, ()) for d in details):
                top[importer].add(imported)
    return top, full


@dataclass
class Definition:
    name: str
    kind: str
    start: int
    end: int
    node: ast.AST


def top_level_definitions(tree: ast.Module) -> dict[str, Definition]:
    defs: dict[str, Definition] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            defs[node.name] = Definition(node.name, kind, start, node.end_lineno or start, node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = Definition(t.id, "assign", node.lineno, node.end_lineno or 0, node)
    return defs


def reference_graph(defs: dict[str, Definition]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for name, d in defs.items():
        refs[name] = {
            n.id
            for n in ast.walk(d.node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in defs
        } - {name}
    return refs


Uses = dict[tuple[str, str], set[tuple[str, str]]]


def _chain(expr: ast.expr) -> list[str] | None:
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        return [expr.id, *reversed(parts)]
    return None


def _use_target(node: ast.AST, bound: dict[str, str], names: set[str]) -> tuple[str, str] | None:
    dotted = None
    if isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Store):
        chain = _chain(node)
        if chain and chain[0] in bound:
            dotted = ".".join([bound[chain[0]], *chain[1:]])
    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in bound:
        dotted = bound[node.id]
    if dotted is None:
        return None
    module, attr = split_target(dotted, names)
    return (module, attr.split(".")[0]) if module and attr else None


def build_uses(mods: dict[str, Mod]) -> Uses:
    """(defining module, name) -> {(using module, using scope)} across the package."""
    names = set(mods)
    uses: Uses = defaultdict(set)
    for mod in mods.values():
        defs = top_level_definitions(mod.tree)
        for node, label, _in_func, _tc in mod.scoped:
            target = _use_target(node, mod.bound, names)
            if target is None and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                local = node.id in defs and node.id not in mod.bound
                target = (mod.name, node.id) if local else None
            if target is not None:
                uses[target].add((mod.name, label))
    return uses


def call_graph(mod: Mod, uses: Uses, profile: Profile) -> dict[str, Any]:
    defs = top_level_definitions(mod.tree)
    refs = reference_graph(defs)
    fan_in: dict[str, int] = defaultdict(int)
    for targets in refs.values():
        for t in targets:
            fan_in[t] += 1
    hubs = {n for n in defs if fan_in[n] >= profile.hub_threshold}
    parent = {n: n for n in defs if n not in hubs}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, targets in refs.items():
        for b in targets:
            if a in parent and b in parent:
                parent[find(a)] = find(b)
    members: dict[str, list[str]] = defaultdict(list)
    for n in parent:
        members[find(n)].append(n)
    groups = sorted(
        (sorted(m, key=lambda n: defs[n].start) for m in members.values()),
        key=lambda m: defs[m[0]].start,
    )

    def callers(names: list[str]) -> list[dict[str, Any]]:
        by_site: dict[tuple[str, str], set[str]] = defaultdict(set)
        for n in names:
            for use_mod, scope in uses.get((mod.name, n), ()):
                if use_mod != mod.name:
                    by_site[(use_mod, scope)].add(n)
        return [
            {"module": m, "function": f, "names": sorted(ns)}
            for (m, f), ns in sorted(by_site.items())
        ]

    def entry(d: Definition) -> dict[str, Any]:
        return {"name": d.name, "kind": d.kind, "start": d.start, "end": d.end}

    out_groups = [
        {
            "id": f"g{i}",
            "lines": [defs[g[0]].start, max(defs[n].end for n in g)],
            "definitions": [entry(defs[n]) for n in g],
            "external_callers": callers(g),
        }
        for i, g in enumerate(groups, 1)
    ]
    shared = [
        {**entry(defs[n]), "fan_in": fan_in[n], "external_callers": callers([n])}
        for n in sorted(hubs, key=lambda n: defs[n].start)
    ]
    return {
        "definitions": len(defs),
        "hub_threshold": profile.hub_threshold,
        "groups": out_groups,
        "shared": shared,
    }


def _store_target(node: ast.AST) -> tuple[str, str] | None:
    """(receiver text, constant key) of ``recv["key"]`` when it is a subscript."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        key = node.slice.value
        return (ast.unparse(node.value), key) if isinstance(key, str) else None
    return None


def status_writes(mods: dict[str, Mod], uses: Uses, profile: Profile) -> list[dict[str, Any]]:
    out = []
    for mod in mods.values():
        parents: dict[ast.AST, ast.AST] | None = None
        for node, label, _f, _tc in mod.scoped:
            if not isinstance(node, ast.Assign):
                continue
            hit = next(
                (h for h in map(_store_target, node.targets) if h and h[1] == profile.status_key),
                None,
            )
            if hit is None:
                continue
            if parents is None:
                parents = {c: p for p in mod.nodes for c in ast.iter_child_nodes(p)}
            out.append(_status_entry(mod, node, label, hit[0], parents, uses, profile))
    return sorted(out, key=lambda e: (e["module"], e["line"]))


def _status_entry(
    mod: Mod,
    node: ast.Assign,
    label: str,
    receiver: str,
    parents: dict[ast.AST, ast.AST],
    uses: Uses,
    profile: Profile,
) -> dict[str, Any]:
    siblings: list[ast.stmt] = []
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(parents[node], attr, None)
        if isinstance(block, list) and node in block:
            siblings = block
    fields = set()
    for s in siblings:
        for t in s.targets if isinstance(s, ast.Assign) else []:
            hit = _store_target(t)
            if hit and hit[0] == receiver and hit[1] != profile.status_key:
                fields.add(hit[1])
    callers = sorted(
        {(m, f) for m, f in uses.get((mod.name, label), ()) if (m, f) != (mod.name, label)}
    )
    return {
        "module": mod.name,
        "line": node.lineno,
        "function": label,
        "receiver": receiver,
        "value": ast.unparse(node.value),
        "task_record": receiver in profile.task_receivers,
        "fields": sorted(fields),
        "callers": [{"module": m, "function": f} for m, f in callers],
    }


def _literal_keys(d: ast.Dict) -> list[str]:
    return [k.value for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def _task_key_event(node: ast.AST, receivers: set[str]) -> tuple[str, str] | None:
    if isinstance(node, ast.Subscript):
        hit = _store_target(node)
        if hit and hit[0] in receivers:
            return ("read" if isinstance(node.ctx, ast.Load) else "write", hit[1])
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        func = node.func
        arg = node.args[0] if node.args else None
        if (
            isinstance(func.value, ast.Name)
            and func.value.id in receivers
            and isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and func.attr in ("get", "pop", "setdefault")
        ):
            return ("read" if func.attr == "get" else "write", arg.value)
    elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant):
        right = node.comparators[0]
        if isinstance(node.ops[0], ast.In) and isinstance(right, ast.Name):
            return ("read", str(node.left.value)) if right.id in receivers else None
    return None


def task_keys(mods: dict[str, Mod], profile: Profile) -> dict[str, Any]:
    """Who reads and who writes each key of a task record (receivers named in the profile)."""
    reads: dict[str, set[str]] = defaultdict(set)
    writes: dict[str, set[str]] = defaultdict(set)
    receivers = set(profile.task_receivers)
    for mod in mods.values():
        for node, label, _f, _tc in mod.scoped:
            site = f"{mod.name}:{label}"
            event = _task_key_event(node, receivers)
            if event:
                (reads if event[0] == "read" else writes)[event[1]].add(site)
            elif isinstance(node, ast.Dict):
                keys = _literal_keys(node)
                if all(m in keys for m in profile.task_marker_keys):
                    for k in keys:
                        writes[k].add(site)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(re.fullmatch(r"_?TASK\w*DEFAULTS", n) for n in names):
                    for k in _literal_keys(node.value):
                        writes[k].add(site)
    table = {
        k: {"readers": sorted(reads.get(k, ())), "writers": sorted(writes[k])}
        for k in sorted(writes)
    }
    return {
        "receivers": sorted(receivers),
        "keys": table,
        "unread": [k for k, v in table.items() if not v["readers"]],
    }


def runs_vs_hops(mods: dict[str, Mod], profile: Profile) -> dict[str, Any]:
    run_keys: set[str] = set()
    hop_keys: set[str] = set()
    for mod in mods.values():
        for node in mod.nodes:
            if not isinstance(node, ast.Dict):
                continue
            keys = set(_literal_keys(node))
            if profile.run_marker_key in keys:
                run_keys |= keys
            if all(m in keys for m in profile.hop_marker_keys):
                hop_keys |= keys
    shared = run_keys & hop_keys
    return {
        "run_record_keys": sorted(run_keys),
        "hop_record_keys": sorted(hop_keys),
        "shared_keys": sorted(shared),
        "duplicates_hops": bool(shared - profile.generic_keys) or "hops" in run_keys,
    }


@dataclass
class PatchTables:
    names: set[str]
    defs: dict[str, set[str]]
    imports: dict[str, dict[str, str]]

    def defining(self, module: str, name: str, depth: int = 0) -> tuple[str | None, str]:
        """(module that defines ``module.name``, how it got there)."""
        if depth > 12:
            return None, "unresolved"
        if name in self.defs.get(module, ()):
            return module, "defined"
        dotted = self.imports.get(module, {}).get(name)
        if dotted is None:
            return None, "unresolved"
        target, attr = split_target(dotted, self.names)
        if target is None:
            return None, "external"
        if attr is None:
            return module, "module_alias"
        origin, kind = self.defining(target, attr.split(".")[0], depth + 1)
        return origin, ("imported" if kind in ("defined", "imported") else kind)


def _patch_calls(tree: ast.Module) -> Iterator[tuple[ast.Call, str, ast.expr | str, str | None]]:
    """(call, via, object expression or dotted string, attribute name or None)."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func, args = node.func, node.args
        recv = ast.unparse(func.value)
        if func.attr == "setattr" and (recv.endswith("monkeypatch") or recv in ("mp", "m")):
            if len(args) >= 3 and isinstance(args[1], ast.Constant):
                yield node, "monkeypatch.setattr", args[0], str(args[1].value)
            elif len(args) >= 2 and isinstance(args[0], ast.Constant):
                yield node, "monkeypatch.setattr", str(args[0].value), None
        elif func.attr == "patch" and args and isinstance(args[0], ast.Constant):
            yield node, "mock.patch", str(args[0].value), None
        elif (
            func.attr == "object"
            and recv.endswith("patch")
            and len(args) >= 2
            and isinstance(args[1], ast.Constant)
        ):
            yield node, "mock.patch", args[0], str(args[1].value)


def monkeypatches(root: Path, mods: dict[str, Mod], profile: Profile) -> dict[str, Any]:
    tables = PatchTables(
        set(mods),
        {n: set(top_level_definitions(m.tree)) for n, m in mods.items()},
        {n: m.bound for n, m in mods.items()},
    )
    sites = []
    for path in sorted((root / "tests").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or any(rel.startswith(p) for p in profile.test_exclude):
            continue
        text = path.read_text(encoding="utf-8")
        if "setattr" not in text and "patch" not in text:
            continue
        holder = Mod(path.stem, rel, False, ast.parse(text), 0)
        for call, via, target, attr in _patch_calls(holder.tree):
            site = _patch_site(rel, call, via, target, attr, holder.bound, tables, profile)
            if site:
                sites.append(site)
    sites.sort(key=lambda s: (s["file"], s["line"]))
    cross = {(s["patched_module"], s["name"], s["defined_in"]) for s in sites if s["mismatch"]}
    return {
        "sites": sites,
        "cross_module_targets": [
            {"patched_module": m, "name": n, "defined_in": d} for m, n, d in sorted(cross)
        ],
    }


def _patch_site(
    rel: str,
    call: ast.Call,
    via: str,
    target: ast.expr | str,
    attr: str | None,
    bound: dict[str, str],
    tables: PatchTables,
    profile: Profile,
) -> dict[str, Any] | None:
    if isinstance(target, str):
        dotted = target
    else:
        chain = _chain(target)
        if chain is None or chain[0] not in bound:
            return _site(rel, call, via, None, attr, None, "unresolved")
        dotted = ".".join([bound[chain[0]], *chain[1:]])
    if not _in_package(dotted, profile):
        return None
    module, rest = split_target(dotted, tables.names)
    if attr is None:
        if module is None or rest is None or "." in rest:
            return _site(rel, call, via, module, rest, None, "unresolved")
        attr = rest
    elif rest is not None or module is None:
        return _site(rel, call, via, module, attr, None, "unresolved")
    origin, kind = tables.defining(module, attr)
    return _site(rel, call, via, module, attr, origin, kind)


def _site(
    rel: str,
    call: ast.Call,
    via: str,
    module: str | None,
    name: str | None,
    origin: str | None,
    kind: str,
) -> dict[str, Any]:
    differs = origin is not None and module is not None and origin != module
    return {
        "file": rel,
        "line": call.lineno,
        "via": via,
        "patched_module": module,
        "name": name,
        "defined_in": origin,
        "kind": kind,
        "mismatch": differs and kind != "module_alias",
    }


def _is_dict_any(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)):
        return False
    elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else []
    return node.value.id == "dict" and [ast.unparse(e) for e in elts] == ["str", "Any"]


def _is_dict_guard(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return False
    if node.func.id != "isinstance" or len(node.args) != 2:
        return False
    kinds = node.args[1].elts if isinstance(node.args[1], ast.Tuple) else [node.args[1]]
    return any(isinstance(k, ast.Name) and k.id == "dict" for k in kinds)


def _annotations(node: ast.AST) -> list[ast.expr | None]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        a = node.args
        anns = [x.annotation for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]]
        extra = [a.vararg.annotation if a.vararg else None, a.kwarg.annotation if a.kwarg else None]
        return [*anns, *extra, node.returns]
    return [node.annotation] if isinstance(node, ast.AnnAssign) else []


def annotation_counts(mods: dict[str, Mod]) -> tuple[int, int]:
    """(dict[str, Any] annotations, isinstance(x, dict) guards)."""
    annotated = guards = 0
    for mod in mods.values():
        for node in mod.nodes:
            annotated += sum(_is_dict_any(n) for a in _annotations(node) if a for n in ast.walk(a))
            guards += _is_dict_guard(node)
    return annotated, guards


def unmapped_modules(mods: dict[str, Mod], profile: Profile) -> list[str]:
    mapped = {src for src, _ in profile.module_map}
    out = []
    for name, mod in mods.items():
        if mod.is_package or name in mapped or name in profile.call_graph_modules:
            continue
        if name in profile.keep_modules or name.startswith(profile.keep_prefixes):
            continue
        out.append(name)
    return sorted(out)


def analyze(root: Path, profile: Profile = DOCKET) -> dict[str, Any]:
    mods = load_modules(root, profile)
    names = set(mods)
    locals_ = [i for m in mods.values() for i in local_imports(m, profile, names)]
    local_lines: dict[str, set[int]] = defaultdict(set)
    for item in locals_:
        local_lines[item["module"]].add(item["line"])
    top, full = import_adjacency(build_import_graph(root, profile), local_lines)
    sccs_top, sccs_full = sccs(sorted(names), top), sccs(sorted(names), full)
    uses = build_uses(mods)
    writes = status_writes(mods, uses, profile)
    patches = monkeypatches(root, mods, profile)
    any_count, guard_count = annotation_counts(mods)
    edges = profile.edges_prefix
    core_edges = sorted(
        m
        for m in names
        if m.startswith(profile.core_prefix + ".")
        and any(i == edges or i.startswith(edges + ".") for i in full.get(m, ()))
    )
    biggest = sorted(((m.lines, n) for n, m in mods.items()), key=lambda x: (-x[0], x[1]))
    by_package: dict[str, int] = defaultdict(int)
    for item in locals_:
        by_package[".".join(item["module"].split(".")[:2])] += 1
    metrics = {
        "cycle_largest": max([len(c) for c in sccs_full], default=1),
        "cycle_largest_toplevel": max([len(c) for c in sccs_top], default=1),
        "local_imports": len(locals_),
        "module_largest_lines": biggest[0][0] if biggest else 0,
        "status_writers": sum(1 for w in writes if w["task_record"]),
        "monkeypatch_cross_module_targets": len(patches["cross_module_targets"]),
        "core_modules_importing_edges": len(core_edges),
        "dict_any_annotations": any_count,
        "isinstance_dict_guards": guard_count,
    }
    return {
        "package": profile.package,
        "modules": len(mods),
        "metrics": metrics,
        "imports": {
            "sccs": {"top_level": sccs_top, "with_local": sccs_full},
            "local_imports": sorted(locals_, key=lambda i: (i["module"], i["line"])),
            "local_imports_by_package": dict(sorted(by_package.items())),
            "core_modules_importing_edges": core_edges,
        },
        "call_graphs": {
            n: call_graph(mods[n], uses, profile) for n in profile.call_graph_modules if n in mods
        },
        "status_writes": writes,
        "monkeypatches": patches,
        "task_keys": task_keys(mods, profile),
        "runs_vs_hops": runs_vs_hops(mods, profile),
        "largest_modules": [{"module": n, "lines": c} for c, n in biggest[:5]],
        "unmapped_modules": unmapped_modules(mods, profile),
    }


def assign_definitions(mod: Mod, profile: Profile) -> dict[str, str]:
    """Destination per top-level definition: the first matching rule, else the one most neighbours
    have (ties to the first alphabetically), else ``<package>.unassigned.<module>``."""
    defs = top_level_definitions(mod.tree)
    refs = reference_graph(defs)
    neighbours: dict[str, set[str]] = {n: set(r) for n, r in refs.items()}
    for n, targets in refs.items():
        for t in targets:
            neighbours[t].add(n)
    rules = [(re.compile(p), dest) for p, dest in profile.definition_rules.get(mod.name, ())]
    dest: dict[str, str] = {}
    for name in defs:
        hit = next((d for rx, d in rules if rx.search(name)), None)
        if hit:
            dest[name] = hit
    changed = True
    while changed:
        changed = False
        snapshot = dict(dest)
        for name in sorted(defs):
            if name in snapshot:
                continue
            votes: dict[str, int] = defaultdict(int)
            for other in neighbours[name]:
                if other in snapshot:
                    votes[snapshot[other]] += 1
            if votes:
                dest[name] = min(votes, key=lambda d: (-votes[d], d))
                changed = True
    stem = mod.name.split(".")[-1]
    return {n: dest.get(n, f"{profile.package}.unassigned.{stem}") for n in defs}


def _toml_names(names: list[str]) -> str:
    one = "names = [" + ", ".join(json.dumps(n) for n in names) + "]"
    if len(one) <= 100:
        return one
    return "names = [\n" + "".join(f"    {json.dumps(n)},\n" for n in names) + "]"


def draft_map(root: Path, profile: Profile, analysis: dict[str, Any]) -> str:
    """The first target-map.toml: module moves from the rules, definition moves from the groups."""
    mods = load_modules(root, profile)
    head = "# Draft target map. Generated by scripts/maint/refactor/analyze.py --draft-map; "
    lines = [head + "review before use."]
    if analysis["unmapped_modules"]:
        lines.append(
            "# Modules with no rule (left where they are): "
            + ", ".join(analysis["unmapped_modules"])
        )
    lines += ["", "# whole-module moves, applied first"]
    moves = sorted((s, d) for s, d in profile.module_map if s in mods)
    lines.append(
        "\n".join(f"[[module]]\nfrom = {json.dumps(s)}\nto = {json.dumps(d)}\n" for s, d in moves)
    )
    lines.append(
        "# named definitions moved in list order (functions, classes, module-level assignments)"
    )
    entries: list[str] = []
    for name in profile.call_graph_modules:
        if name not in mods:
            continue
        dest = assign_definitions(mods[name], profile)
        defs = top_level_definitions(mods[name].tree)
        order: dict[str, list[str]] = {}
        for n in sorted(defs, key=lambda n: defs[n].start):
            order.setdefault(dest[n], []).append(n)
        for to, names in order.items():
            review = ""
            if to.startswith(f"{profile.package}.unassigned."):
                review = "# REVIEW: no rule matched and no neighbour was assigned\n"
            entries.append(
                f"{review}[[definition]]\nfrom = {json.dumps(name)}\nto = {json.dumps(to)}\n"
                f"{_toml_names(names)}\n"
            )
    lines.append("\n".join(entries))
    return "\n".join(lines).rstrip("\n") + "\n"


def render_markdown(analysis: dict[str, Any]) -> str:
    out = [f"# Analysis of `{analysis['package']}` ({analysis['modules']} modules)", ""]
    out += ["## Gate metrics", "", "| metric | value |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in analysis["metrics"].items()]
    cycles = analysis["imports"]["sccs"]
    out += ["", "## Import cycles", ""]
    for label in ("top_level", "with_local"):
        sizes = [len(c) for c in cycles[label]]
        out.append(f"- {label}: {len(sizes)} cycle(s), sizes {sizes}")
    if cycles["with_local"]:
        out += ["", "Largest cycle (counting local imports):", ""]
        out += [f"- `{m}`" for m in cycles["with_local"][0]]
    out += ["", "## Function-local imports by package", ""]
    out += [f"- {k}: {v}" for k, v in analysis["imports"]["local_imports_by_package"].items()]
    for name, graph in analysis["call_graphs"].items():
        out += ["", f"## Call groups: `{name}`", ""]
        out.append(
            f"{graph['definitions']} definitions; hubs have fan-in >= {graph['hub_threshold']}."
        )
        out += ["", "| group | definitions | lines | external callers |", "|---|---|---|---|"]
        for g in graph["groups"]:
            span = f"{g['lines'][0]}-{g['lines'][1]}"
            out.append(
                f"| {g['id']} | {len(g['definitions'])} | {span} | {len(g['external_callers'])} |"
            )
        shared = ", ".join(f"`{s['name']}` ({s['fan_in']})" for s in graph["shared"])
        out += ["", f"Shared (name and fan-in): {shared or 'none'}"]
    out += ["", "## Writers of a task's status", ""]
    out += ["| site | function | value | other fields set |", "|---|---|---|---|"]
    for w in analysis["status_writes"]:
        tag = "" if w["task_record"] else " (not a task record)"
        out.append(
            f"| {w['module']}:{w['line']}{tag} | {w['function']} | `{w['value']}` "
            f"| {', '.join(w['fields']) or '-'} |"
        )
    cross = analysis["monkeypatches"]["cross_module_targets"]
    out += ["", f"## Patches whose defining module differs ({len(cross)} targets)", ""]
    out += [
        f"- `{c['patched_module']}.{c['name']}` is defined in `{c['defined_in']}`" for c in cross
    ]
    out += ["", "## Task-record keys nothing reads", ""]
    out.append(", ".join(analysis["task_keys"]["unread"]) or "none")
    runs = analysis["runs_vs_hops"]
    shared_keys = ", ".join(runs["shared_keys"]) or "none"
    out += ["", "## Run records and hop records", ""]
    out.append(f"Shared keys: {shared_keys}; duplicates hops: {runs['duplicates_hops']}")
    out += ["", "## Modules with no rule in the mapping", ""]
    out += [f"- `{m}`" for m in analysis["unmapped_modules"]] or ["none"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None, profile: Profile = DOCKET) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help="repository root (src/ and tests/)")
    ap.add_argument("--out-dir", type=Path, default=None, help="default: <root>/refactor")
    ap.add_argument("--metrics", action="store_true", help="print the nine gate numbers")
    ap.add_argument("--json", action="store_true", help="with --metrics: print JSON")
    ap.add_argument("--draft-map", action="store_true", help="write target-map.toml")
    args = ap.parse_args(argv)
    out_dir = args.out_dir or args.root / "refactor"
    analysis = analyze(args.root, profile)
    if args.metrics:
        if args.json:
            print(json.dumps(analysis["metrics"], indent=2))
        else:
            print("\n".join(f"{k}={v}" for k, v in analysis["metrics"].items()))
    if args.draft_map:
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "target-map.toml"
        target.write_text(draft_map(args.root, profile, analysis), encoding="utf-8")
        print(f"wrote {target}")
    if not args.metrics and not args.draft_map:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", "utf-8")
        (out_dir / "analysis.md").write_text(render_markdown(analysis), encoding="utf-8")
        print(f"wrote {out_dir / 'analysis.json'} and {out_dir / 'analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
