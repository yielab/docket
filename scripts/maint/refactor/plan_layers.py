#!/usr/bin/env python3
"""What-if planner for P47-11: which whole-module reassignments remove upward context imports.

Builds the module import graph of ``src/docket`` (top-level and function-local ``from docket.X
import y``, ``y`` resolved to a submodule when it is one), takes ``LAYERS`` and the dependency rules
from ``tests/architecture/test_import_contracts.py`` (the rules are applied to the reassigned names,
so the count is the one the contracts would give), and greedily applies the single module move that
removes the most violations until none helps. Prints the moves with their gain, what is left with
the names that cross, the cross-context private-name imports, and the exact minimal layer order of
the moved tree (a DP over the 2^11 subsets of contexts). Same tree, same output. Writes nothing.

Run from the repository root: ``uv run python scripts/maint/refactor/plan_layers.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"

_spec = importlib.util.spec_from_file_location(
    "_icontracts", REPO / "tests/architecture/test_import_contracts.py"
)
assert _spec and _spec.loader
IC = importlib.util.module_from_spec(_spec)
sys.modules["_icontracts"] = IC
_spec.loader.exec_module(IC)

LAYERS: tuple[str, ...] = IC.LAYERS
RANK = {c: i for i, c in enumerate(LAYERS)}
# A module may be reassigned to these contexts only: they have the domain/application structure.
DESTINATIONS = [c for c in LAYERS if c not in {"platform", "sandbox", "agent"}]
MOVABLE_LAYERS = {"domain", "application", "flat", "agent"}

mods: dict[str, Path] = {}
for p in sorted((SRC / "docket").rglob("*.py")):
    if "templates" in p.parts:
        continue
    name = ".".join(p.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")
    mods[name] = p


def top(m: str) -> str:
    parts = m.split(".")
    return parts[1] if len(parts) > 1 else ""


# edges: (importer, imported module) -> names imported from it; local: importer-imported pairs only
# reached through a function-local import are tracked apart.
edges: dict[tuple[str, str], set[str]] = defaultdict(set)
local_edges: set[tuple[str, str]] = set()
attr_private: dict[tuple[str, str], set[str]] = defaultdict(set)


class Walker(ast.NodeVisitor):
    def __init__(self, importer: str) -> None:
        self.importer = importer
        self.depth = 0
        self.alias: dict[str, str] = {}

    def _fn(self, node: ast.AST) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _fn

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module or not node.module.startswith("docket"):
            return
        for a in node.names:
            sub = f"{node.module}.{a.name}"
            if sub in mods:
                target, name = sub, ""
                self.alias[a.asname or a.name] = sub
            else:
                target, name = node.module, a.name
            if target not in mods or target == "docket":
                continue
            edges[(self.importer, target)].add(name)
            if self.depth:
                local_edges.add((self.importer, target))

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.name in mods and a.name != "docket":
                edges[(self.importer, a.name)].add("")
                if self.depth:
                    local_edges.add((self.importer, a.name))
                if a.asname:
                    self.alias[a.asname] = a.name

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.alias
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            attr_private[(self.importer, self.alias[node.value.id])].add(node.attr)
        self.generic_visit(node)


for m, p in mods.items():
    w = Walker(m)
    w.visit(ast.parse(p.read_text(encoding="utf-8")))

by_module: dict[str, list[tuple[str, str]]] = defaultdict(list)
for a, b in edges:
    by_module[a].append((a, b))
    by_module[b].append((a, b))

assign: dict[str, str] = {m: top(m) for m in mods}
original = dict(assign)

# Moves already accepted in refactor/target-map.toml are applied first; the greedy search adds to them.
renamed: dict[str, str] = {}
_map = REPO / "refactor/target-map.toml"
if _map.exists():
    for row in tomllib.loads(_map.read_text(encoding="utf-8")).get("module", []):
        for m in mods:
            if m == row["from"] or m.startswith(row["from"] + "."):
                renamed[m] = row["to"] + m[len(row["from"]) :]
                assign[m] = renamed[m].split(".")[1]
print(f"accepted moves read from target-map.toml: {len(renamed)} modules")


def vname(m: str, asg: dict[str, str]) -> str:
    if m in renamed and asg[m] == renamed[m].split(".")[1]:
        return renamed[m]
    parts = m.split(".")
    if len(parts) > 1:
        parts[1] = asg[m]
    return ".".join(parts)


def edge_violations(a: str, b: str, asg: dict[str, str]) -> list[str]:
    va, vb = vname(a, asg), vname(b, asg)
    layer = IC._classify(va)[1]
    return [
        name
        for name, (layers, rule) in IC._CONTRACTS.items()
        if layer in layers and not rule(va, vb)
    ]


def violations(asg: dict[str, str]) -> list[tuple[str, str, str]]:
    return sorted((n, a, b) for (a, b) in edges for n in edge_violations(a, b, asg))


def cost_of(m: str, asg: dict[str, str]) -> int:
    return sum(len(edge_violations(a, b, asg)) for a, b in by_module[m])


def movable(m: str) -> bool:
    return len(m.split(".")) > 2 and IC._classify(m)[1] in MOVABLE_LAYERS and top(m) in RANK


def short(contract: str) -> str:
    return contract.split(" ")[0]


base = violations(assign)
print(f"violations now: {len(base)} ({dict(Counter(short(n) for n, _, _ in base))})")
print(f"function-local docket imports: {len(local_edges)} module pairs")

if renamed:
    mid = violations(assign)
    print(f"\nviolations after the accepted moves alone: {len(mid)}")
    for n, a, b in mid:
        names = ", ".join(sorted(x for x in edges[(a, b)] if x)) or "(module)"
        print(f"  {short(n)} | {vname(a, assign)} -> {vname(b, assign)} : {names}")

accepted = dict(assign)

# Greedy single-module reassignment.
moves: list[tuple[str, str, str, int]] = []
while True:
    best: tuple[int, str, str] | None = None
    for m in sorted(mods):
        if not movable(m):
            continue
        cur = cost_of(m, assign)
        if cur == 0:
            continue
        neigh = {assign[x] for a, b in by_module[m] for x in (a, b) if x != m}
        for c in sorted((neigh & set(DESTINATIONS)) - {assign[m]}):
            old = assign[m]
            assign[m] = c
            gain = cur - cost_of(m, assign)
            assign[m] = old
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, m, c)
    if best is None:
        break
    gain, m, c = best
    moves.append((m, assign[m], c, gain))
    assign[m] = c

print(f"\nproposed moves ({len(moves)}):")
for m, src, dst, gain in moves:
    print(f"  {m:58s} {src:>13s} -> {dst:<13s} -{gain}")
after = violations(assign)
print(f"\nviolations after moves: {len(after)} ({dict(Counter(short(n) for n, _, _ in after))})")

print("\nviolations left (contract | importer -> imported : names crossing):")
for n, a, b in after:
    names = ", ".join(sorted(x for x in edges[(a, b)] if x)) or "(module)"
    print(f"  {short(n)} | {vname(a, assign)} -> {vname(b, assign)} : {names}")

# Cross-context private names, in the tree as it stands. Importers and imported are any docket package.
print("\ncross-context private-name use in the tree as it stands (importer -> imported : names):")
private: dict[tuple[str, str], set[str]] = defaultdict(set)
for (a, b), names in edges.items():
    if accepted[a] != accepted[b] and accepted[b] != "kernel":
        hit = {n for n in names if n.startswith("_") and not n.startswith("__")}
        if hit:
            private[(a, b)] |= hit
for (a, b), names in attr_private.items():
    if accepted[a] != accepted[b] and accepted[b] != "kernel":
        private[(a, b)] |= names
count = sum(len(v) for v in private.values())
for (a, b), names in sorted(private.items()):
    print(f"  {vname(a, accepted)} -> {vname(b, accepted)} : {', '.join(sorted(names))}")
print(f"  total: {count} names over {len(private)} module pairs")

# Exact minimal order of the contexts for the moved tree (application/flat importers, like the rule).
w: dict[tuple[str, str], int] = Counter()
for a, b in edges:
    va, vb = vname(a, accepted), vname(b, accepted)
    ca, cb = IC._classify(va)[0], IC._classify(vb)[0]
    if IC._classify(va)[1] in {"application", "flat"} and ca != cb and ca in RANK and cb in RANK:
        w[(ca, cb)] += 1
n = len(LAYERS)
INF = 10**9
dp = [INF] * (1 << n)
choice = [-1] * (1 << n)
dp[0] = 0
for s in range(1 << n):
    if dp[s] >= INF:
        continue
    for i in range(n):
        if s >> i & 1:
            continue
        above = [j for j in range(n) if j != i and not (s >> j & 1)]
        c = dp[s] + sum(w[(LAYERS[i], LAYERS[j])] for j in above)
        t = s | 1 << i
        if c < dp[t] or (c == dp[t] and i < choice[t]):
            dp[t], choice[t] = c, i
order: list[str] = []
s = (1 << n) - 1
while s:
    i = choice[s]
    order.append(LAYERS[i])
    s &= ~(1 << i)
order.reverse()
layers_cost = sum(v for (a, b), v in w.items() if RANK[b] > RANK[a])
print(f"\nupward under LAYERS (module-pair imports): {layers_cost}")
print(f"exact minimal order: {dp[(1 << n) - 1]} upward -> {' < '.join(order)}")
print(f"LAYERS is {'minimal' if layers_cost == dp[(1 << n) - 1] else 'NOT minimal'}")
