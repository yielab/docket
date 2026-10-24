#!/usr/bin/env python3
"""One-shot (P47-1): give a context a public surface and point its importers at it.

For one context ``C`` this reads ``tests/architecture/import_contracts_baseline.txt``, takes the
edges into ``C``'s internal modules that a facade closes, writes ``C/__init__.py`` (an explicit
``__all__``, exactly the names other contexts import) and rewrites each importer so that
``from docket.C.m import n`` and ``from docket.C import m`` + ``m.n`` become
``from docket.C import n``. Deleted in the card's last commit.

    python scripts/maint/facade_oneshot.py plan <ctx>     # what would change; flags to judge
    python scripts/maint/facade_oneshot.py apply <ctx>    # write it
"""

from __future__ import annotations

import ast
import builtins
import keyword
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
BASELINE = REPO / "tests/architecture/import_contracts_baseline.txt"


def module_path(name: str) -> Path:
    base = SRC / name.replace(".", "/")
    return base / "__init__.py" if base.is_dir() else base.with_suffix(".py")


def all_modules() -> set[str]:
    out = set()
    for p in SRC.rglob("*.py"):
        parts = list(p.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out.add(".".join(parts))
    return out


MODULES = all_modules()


def my_edges() -> list[tuple[str, str]]:
    edges = []
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        contract, _, edge = raw.partition(" | ")
        if not contract.startswith(("application", "interfaces")):
            continue
        importer, _, imported = edge.partition(" -> ")
        if ctx_of(importer) == ctx_of(imported):
            continue
        edges.append((importer, imported))
    return edges


def ctx_of(module: str) -> str:
    return module.split(".")[1]


@dataclass
class Resolved:
    defmod: str  # module that defines the name (in the same context, or kernel)
    name: str  # its name there
    flags: list[str]


_defs_cache: dict[str, tuple[set[str], dict[str, tuple[str, str]], set[str]]] = {}


def module_facts(mod: str) -> tuple[set[str], dict[str, tuple[str, str]], set[str]]:
    """(top-level defined names, imported name -> (module, original), names rebound via global)."""
    if mod in _defs_cache:
        return _defs_cache[mod]
    tree = ast.parse(module_path(mod).read_text(encoding="utf-8"))
    defined: set[str] = set()
    imported: dict[str, tuple[str, str]] = {}
    rebound: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            defined.add(n.id)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    pkg = (
                        mod.split(".")
                        if module_path(mod).name == "__init__.py"
                        else mod.split(".")[:-1]
                    )
                    pkg = pkg[: len(pkg) - (node.level - 1)]
                    base = ".".join([*pkg, base] if base else pkg)
                for a in node.names:
                    imported[a.asname or a.name] = (base, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    imported[(a.asname or a.name).split(".")[0]] = (a.name, "")
            elif isinstance(node, ast.If | ast.Try | ast.With | ast.For | ast.While):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, []))
                for h in getattr(node, "handlers", []):
                    visit(h.body)

    visit(tree.body)
    for n in ast.walk(tree):
        if isinstance(n, ast.Global):
            rebound.update(n.names)
    _defs_cache[mod] = (defined, imported, rebound)
    return defined, imported, rebound


def resolve(mod: str, name: str) -> Resolved:
    flags: list[str] = []
    seen = 0
    while True:
        seen += 1
        defined, imported, rebound = module_facts(mod)
        if name in rebound:
            flags.append(f"{mod}.{name} is rebound with `global` at runtime")
        if name in defined:
            return Resolved(mod, name, flags)
        if name in imported:
            src, orig = imported[name]
            if src in MODULES and orig and src + "." + orig in MODULES:
                flags.append(f"{mod}.{name} is a submodule {src}.{orig}")
                return Resolved(mod, name, flags)
            if src in MODULES and orig:
                mod, name = src, orig
                if seen > 6:
                    flags.append("re-export chain too long")
                    return Resolved(mod, name, flags)
                continue
            flags.append(f"{mod}.{name} comes from outside the package ({src})")
            return Resolved(mod, name, flags)
        if mod + "." + name in MODULES:
            flags.append(f"{mod}.{name} is a submodule")
            return Resolved(mod, name, flags)
        flags.append(f"{mod}.{name} not found at module level")
        return Resolved(mod, name, flags)


@dataclass
class Use:
    importer: str
    target: str  # docket.C.m
    attr: str  # name in target (module-style) or imported name (name-style)
    style: str  # "attr" | "name"
    local: str  # the importer's own alias (module alias, or `as` name / name)


def scope_of(tree: ast.Module, node: ast.AST) -> ast.AST:
    """Innermost function containing node, else the module."""
    best: ast.AST = tree
    for n in ast.walk(tree):
        inside = (
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and n.lineno <= node.lineno <= (n.end_lineno or n.lineno)
            and n is not node
        )
        if inside and (best is tree or n.lineno >= best.lineno):  # type: ignore[attr-defined]
            best = n
    return best


def collect_bound(tree: ast.Module) -> set[str]:
    bound: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store | ast.Del):
            bound.add(n.id)
        elif isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.alias):
            bound.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.Global | ast.Nonlocal):
            bound.update(n.names)
    return bound


def collect_names_loaded(tree: ast.Module) -> set[str]:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


@dataclass
class ImportEdit:
    node: ast.ImportFrom | ast.Import
    keep: list[ast.alias]  # aliases left in the original statement
    new_names: list[tuple[str, str]]  # (facade name, local name)
    uses: list[ast.Attribute]  # attribute nodes to rewrite to a bare name
    renames: dict[ast.Attribute, str]


def plan_importer(importer: str, targets: set[str], flags: list[str]):
    """Parse one importer and list its imports of ``targets`` with the attributes it uses."""
    path = module_path(importer)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    items: list[tuple[ast.stmt, ast.alias, str, str]] = []  # (stmt, alias, target, style)
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            for a in n.names:
                full = n.module + "." + a.name
                if n.module in targets:
                    items.append((n, a, n.module, "name"))
                elif full in targets:
                    items.append((n, a, full, "attr"))
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in targets:
                    if a.asname:
                        items.append((n, a, a.name, "attr"))
                    else:
                        flags.append(f"{importer}: plain `import {a.name}` needs a hand edit")
    return src, tree, items


def run(ctx: str, write: bool) -> int:
    edges = [(a, b) for a, b in my_edges() if ctx_of(b) == ctx]
    by_importer: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        by_importer[a].add(b)
    flags: list[str] = []
    plans = {}
    # facade entries: (module, attr) -> resolved
    wanted: dict[tuple[str, str], Resolved] = {}

    for importer, targets in sorted(by_importer.items()):
        src, tree, items = plan_importer(importer, targets, flags)
        plans[importer] = (src, tree, items)
        for stmt, alias, target, style in items:
            if style == "name":
                key = (target, alias.name)
                wanted.setdefault(key, resolve(*key))
            else:
                scope = scope_of(tree, stmt)
                local = alias.asname or alias.name
                for n in ast.walk(scope):
                    if (
                        isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name)
                        and n.value.id == local
                    ):
                        key = (target, n.attr)
                        wanted.setdefault(key, resolve(*key))
                        if not isinstance(n.ctx, ast.Load):
                            flags.append(f"{importer}:{n.lineno}: {local}.{n.attr} is assigned")
    # facade names: unique per context, never a submodule name of the context
    submodules = {m.split(".")[2] for m in MODULES if m.startswith(f"docket.{ctx}.")}
    final: dict[tuple[str, str], tuple[str, str, str]] = {}  # key -> (defmod, defname, facade)
    for (target, attr), r in wanted.items():
        flags.extend(r.flags)
        final[(target, attr)] = (r.defmod, r.name, r.name.lstrip("_") or r.name)
    by_name: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for _, (dm, dn, fn) in final.items():
        by_name[fn].add((dm, dn))
    for key, (dm, dn, fn) in list(final.items()):
        clash = len(by_name[fn]) > 1 or fn in submodules or keyword.iskeyword(fn)
        if clash and not dm.startswith("docket.kernel"):
            base = dm.split(".")[-1]
            final[key] = (dm, dn, f"{base}_{dn.lstrip('_')}")
    facade_names: dict[str, tuple[str, str]] = {}
    for _, (dm, dn, fn) in final.items():
        if dm.startswith("docket.kernel"):
            continue
        if fn in facade_names and facade_names[fn] != (dm, dn):
            flags.append(f"facade name clash {fn}: {facade_names[fn]} vs {(dm, dn)}")
        facade_names[fn] = (dm, dn)
        if dn.startswith("_"):
            flags.append(f"private name exported as {fn}: {dm}.{dn}")
        if dm.split(".")[1] != ctx:
            flags.append(f"{dm}.{dn} is defined outside {ctx}")

    print(f"[{ctx}] importers={len(by_importer)} edges={len(edges)} exports={len(facade_names)}")
    for f in sorted(set(flags)):
        print("  FLAG", f)
    if not write:
        return 0
    if any(f for f in flags if "needs a hand edit" in f or "assigned" in f):
        print("refusing to write: hand edits needed")
        return 1

    # rewrite importers
    for importer, (src, tree, items) in plans.items():
        rewrite_importer(importer, src, tree, items, final, ctx)
    write_facade(ctx, facade_names)
    return 0


BUILTINS = set(dir(builtins))


def rewrite_importer(importer, src, tree, items, final, ctx) -> None:
    raw = src.encode("utf-8")
    line_starts = [0]
    for line in raw.split(b"\n")[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)

    def off(lineno: int, col: int) -> int:
        return line_starts[lineno - 1] + col

    bound = collect_bound(tree) | BUILTINS | set(keyword.kwlist)
    taken: dict[str, tuple[str, str]] = {}  # local name -> source it stands for
    edits: list[tuple[int, int, bytes]] = []
    by_stmt: dict[int, list[tuple[ast.alias, str, str]]] = defaultdict(list)
    stmts: dict[int, ast.stmt] = {}
    for stmt, alias, target, style in items:
        by_stmt[id(stmt)].append((alias, target, style))
        stmts[id(stmt)] = stmt

    imported_names_by_stmt: dict[int, list[tuple[str, str]]] = {}
    for sid, group in by_stmt.items():
        stmt = stmts[sid]
        new_names: list[tuple[str, str]] = []
        for alias, target, style in group:
            if style == "name":
                dm, dn, fn = final[(target, alias.name)]
                local = alias.asname or alias.name
                if dm.startswith("docket.kernel"):
                    new_names.append((f"@{dm}", f"{dn} as {local}" if local != dn else dn))
                else:
                    new_names.append((fn, local))
                continue
            modlocal = alias.asname or alias.name
            scope = scope_of(tree, stmt)
            attrs = [
                n
                for n in ast.walk(scope)
                if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id == modlocal
            ]
            chosen: dict[str, str] = {}
            for n in attrs:
                if n.attr in chosen:
                    continue
                dm, dn, fn = final[(target, n.attr)]
                cand = fn
                key = (dm, dn)
                if cand in bound or (cand in taken and taken[cand] != key):
                    cand = f"{modlocal}_{n.attr.lstrip('_')}"
                    if cand in bound or (cand in taken and taken[cand] != key):
                        raise SystemExit(f"{importer}: cannot name {modlocal}.{n.attr}")
                taken[cand] = key
                chosen[n.attr] = cand
                if dm.startswith("docket.kernel"):
                    new_names.append((f"@{dm}", f"{dn} as {cand}" if cand != dn else dn))
                else:
                    new_names.append((fn, cand))
            for n in attrs:
                edits.append(
                    (
                        off(n.lineno, n.col_offset),
                        off(n.end_lineno, n.end_col_offset),
                        chosen[n.attr].encode(),
                    )
                )
        imported_names_by_stmt[sid] = new_names

    for sid, group in by_stmt.items():
        stmt = stmts[sid]
        moved = {id(a) for a, _, _ in group}
        keep = [a for a in stmt.names if id(a) not in moved]
        indent = " " * stmt.col_offset
        lines = []
        if keep:
            kept = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
            if isinstance(stmt, ast.ImportFrom):
                lines.append(f"from {stmt.module} import {kept}")
            else:
                lines.append(f"import {kept}")
        facade_part = [
            (fn, loc) for fn, loc in imported_names_by_stmt[sid] if not fn.startswith("@")
        ]
        kernel_part: dict[str, list[str]] = defaultdict(list)
        for fn, loc in imported_names_by_stmt[sid]:
            if fn.startswith("@"):
                kernel_part[fn[1:]].append(loc)
        if facade_part:
            parts = sorted({fn if fn == loc else f"{fn} as {loc}" for fn, loc in facade_part})
            lines.append(f"from docket.{ctx} import {', '.join(parts)}")
        for dm, names in kernel_part.items():
            lines.append(f"from {dm} import {', '.join(sorted(set(names)))}")
        text = ("\n" + indent).join(lines)
        start, end = off(stmt.lineno, stmt.col_offset), off(stmt.end_lineno, stmt.end_col_offset)
        edits.append((start, end, text.encode()))

    edits.sort(key=lambda e: e[0], reverse=True)
    last = len(raw) + 1
    for start, end, new in edits:
        assert end <= last, f"overlapping edits in {importer}"
        raw = raw[:start] + new + raw[end:]
        last = start
    module_path(importer).write_bytes(raw)


def write_facade(ctx: str, names: dict[str, tuple[str, str]]) -> None:
    by_mod: dict[str, list[str]] = defaultdict(list)
    for fn, (dm, dn) in sorted(names.items()):
        by_mod[dm].append(fn if fn == dn else f"{dn} as {fn}")
    lines = [
        f'"""Public surface of the ``{ctx}`` context (ADR 0030).',
        "",
        "Exactly the names other contexts import; the modules behind them stay internal.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for dm in sorted(by_mod):
        lines.append(f"from {dm} import {', '.join(sorted(by_mod[dm]))}")
    lines += ["", "__all__ = ["]
    lines += [f'    "{n}",' for n in sorted(names)]
    lines += ["]", ""]
    (SRC / "docket" / ctx / "__init__.py").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"plan", "apply"}:
        sys.exit(__doc__)
    sys.exit(run(sys.argv[2], sys.argv[1] == "apply"))
