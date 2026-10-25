#!/usr/bin/env python3
"""Count the dead and duplicated code under src/docket; each count may only fall.

* ``dead``: a top-level function, class or constant, or a method of one, whose name no file
  names: not as a Name, Attribute, import alias or word in a src string, docstrings aside, and
  not as a word anywhere in tests, scripts, packages or pyproject.toml (comments count).
* ``test-only``: the same, but every naming file is under ``tests/``.
* ``duplicate``: groups of functions with identical bodies of 4+ statements once locals are
  renamed by position.
Matching is by name, so a site sharing a name with live code is never reported: the numbers
undercount. Exempt: dunders, ``__all__``, registrations, validators, ``do_VERB`` handlers,
property setters, Protocol methods and overrides of a base-class method.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = REPO_ROOT / "tests" / "guards" / "dead_code_baseline.txt"
SKIP_DIRS = frozenset({".venv", ".git", "node_modules", "__pycache__", "build", "dist"})
EXEMPT_DECORATORS = frozenset(
    {
        "command",
        "callback",
        "fixture",
        "validator",
        "field_validator",
        "model_validator",
        "root_validator",
        "field_serializer",
        "model_serializer",
        "computed_field",
        "abstractmethod",
        "overload",
        "register",
        "setter",
        "deleter",
        "getter",
    }
)
MIN_DUPLICATE_STATEMENTS = 4
HANDLER_VERB = re.compile(r"do_[A-Z]+$")  # BaseHTTPRequestHandler looks these up by name
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KINDS = ("dead", "test-only", "duplicate")

Site = tuple[str, int, str]  # (path relative to the repo, line, name)


@dataclass
class Result:
    dead: list[Site] = field(default_factory=list)
    test_only: list[Site] = field(default_factory=list)
    duplicates: list[list[Site]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "dead": len(self.dead),
            "test-only": len(self.test_only),
            "duplicate": len(self.duplicates),
        }


def _rel(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def _py_files(root: Path) -> Iterator[Path]:
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name.endswith(".py"):
                yield Path(base, name)


def _names_in(tree: ast.Module) -> Iterator[tuple[str, int]]:
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
        elif isinstance(node, ast.Name):
            yield node.id, node.lineno
        elif isinstance(node, ast.Attribute):
            yield node.attr, node.lineno
        elif isinstance(node, ast.alias):
            for part in [*node.name.split("."), node.asname or ""]:
                if part:
                    yield part, getattr(node, "lineno", 0)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                for token in TOKEN.findall(node.value):
                    yield token, node.lineno


def _toml_files(repo: Path) -> Iterator[Path]:
    yield repo / "pyproject.toml"
    yield from sorted((repo / "packages").glob("*/pyproject.toml"))


@dataclass
class Refs:
    """Where each name is mentioned: src by line, every other tree by file only."""

    in_src: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))
    elsewhere: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    exported: set[str] = field(default_factory=set)

    def outside(self, name: str, rel: str, start: int, end: int) -> list[str]:
        """Files naming *name* other than through the span [start, end] of *rel*."""
        found = [
            r for r, line in self.in_src.get(name, []) if not (r == rel and start <= line <= end)
        ]
        return found + sorted(self.elsewhere.get(name, ()))


def _exports(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            out |= {
                c.value
                for c in ast.walk(node.value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            }
    return out


def collect_refs(repo: Path, modules: list[tuple[str, ast.Module]]) -> Refs:
    """Every name each tree mentions. Tests, scripts and packages are read as text, so a
    comment there also counts as a mention; src is read as a syntax tree, docstrings excluded."""
    refs = Refs()
    for rel, tree in modules:
        for name, line in _names_in(tree):
            refs.in_src[name].append((rel, line))
        refs.exported |= _exports(tree)
    others = [p for d in ("tests", "scripts", "packages") for p in _py_files(repo / d)]
    for path in [*others, *(t for t in _toml_files(repo) if t.exists())]:
        rel = _rel(path, repo)
        for name in set(TOKEN.findall(path.read_text(encoding="utf-8"))):
            refs.elsewhere[name].add(rel)
    return refs


def _aliases(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out[(a.asname or a.name).split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            for a in node.names:
                out[a.asname or a.name] = f"{base}.{a.name}"
    return out


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _external_has(dotted: str, method: str) -> bool:
    """True when the importable class named by *dotted* has *method* in its MRO."""
    parts = dotted.split(".")
    if len(parts) == 1:
        obj = getattr(builtins, parts[0], None)
        return obj is not None and hasattr(obj, method)
    for cut in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except Exception:
            continue
        try:
            for attr in parts[cut:]:
                obj = getattr(obj, attr)
        except AttributeError:
            return False
        return hasattr(obj, method)
    return False


class _Classes:
    """The classes under src by name, so a method can be matched against its in-repo bases."""

    def __init__(self, modules: list[tuple[str, ast.Module]]) -> None:
        self.by_name: dict[str, list[tuple[ast.ClassDef, dict[str, str]]]] = defaultdict(list)
        for _, tree in modules:
            aliases = _aliases(tree)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    self.by_name[node.name].append((node, aliases))

    def inherits(self, cls: ast.ClassDef, aliases: dict[str, str], method: str) -> bool:
        return self._inherits(cls, aliases, method, set())

    def _inherits(
        self, cls: ast.ClassDef, aliases: dict[str, str], method: str, seen: set[int]
    ) -> bool:
        for base in cls.bases:
            dotted = _dotted(base)
            if dotted is None:
                continue
            head = dotted.split(".")[0]
            full = ".".join([aliases.get(head, head), *dotted.split(".")[1:]])
            if full.startswith((".", "docket.")) or (head not in aliases and head in self.by_name):
                for node, node_aliases in self.by_name.get(dotted.split(".")[-1], []):
                    if id(node) in seen:
                        continue
                    seen.add(id(node))
                    defined = {
                        n.name
                        for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    if method in defined or self._inherits(node, node_aliases, method, seen):
                        return True
            elif _external_has(full, method):
                return True
        return False


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def _is_protocol(cls: ast.ClassDef) -> bool:
    return any((_dotted(b) or "").split(".")[-1] == "Protocol" for b in cls.bases)


def _span(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[int, int]:
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return start, node.end_lineno or node.lineno


def _definitions(tree: ast.Module, classes: _Classes) -> Iterator[tuple[int, int, int, str, str]]:
    """(line, span start, span end, name to report, name to look up) per candidate."""
    aliases = _aliases(tree)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not (_decorator_names(node) & EXEMPT_DECORATORS):
                start, end = _span(node)
                yield node.lineno, start, end, node.name, node.name
        elif isinstance(node, ast.ClassDef):
            start, end = _span(node)
            yield node.lineno, start, end, node.name, node.name
            if _is_protocol(node):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _decorator_names(item) & EXEMPT_DECORATORS:
                    continue
                if HANDLER_VERB.match(item.name) or classes.inherits(node, aliases, item.name):
                    continue
                s, e = _span(item)
                yield item.lineno, s, e, f"{node.name}.{item.name}", item.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    end = node.end_lineno or node.lineno
                    yield node.lineno, node.lineno, end, target.id, target.id


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def parse_src(repo: Path) -> list[tuple[str, ast.Module]]:
    return [
        (_rel(p, repo), ast.parse(p.read_text(encoding="utf-8")))
        for p in _py_files(repo / "src" / "docket")
    ]


def find_unreferenced(
    repo: Path, modules: list[tuple[str, ast.Module]]
) -> tuple[list[Site], list[Site]]:
    refs = collect_refs(repo, modules)
    classes = _Classes(modules)
    dead: list[Site] = []
    test_only: list[Site] = []
    for rel, tree in modules:
        for line, start, end, shown, name in _definitions(tree, classes):
            if _is_dunder(name) or name in refs.exported:
                continue
            outside = refs.outside(name, rel, start, end)
            if not outside:
                dead.append((rel, line, shown))
            elif all(path.startswith("tests/") for path in outside):
                test_only.append((rel, line, shown))
    return sorted(dead), sorted(test_only)


def _stores(body: list[ast.stmt]) -> list[str]:
    """Names a body binds, in source order: assignment targets and ``except ... as`` names."""
    found: list[str] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                found.append(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                found.append(node.name)
    return found


def _dump(node: object, names: dict[str, str], count: list[int]) -> str:
    """``ast.dump`` of *node* with every local spelled by position, counting statements."""
    if isinstance(node, list):
        return "[" + ",".join(_dump(n, names, count) for n in node) + "]"
    if not isinstance(node, ast.AST):
        return repr(node)
    if isinstance(node, ast.stmt):
        count[0] += 1
    if isinstance(node, ast.Name):
        return f"N({names.get(node.id, node.id)})"
    parts = [type(node).__name__]
    for name, value in ast.iter_fields(node):
        if name == "ctx":
            continue
        if (isinstance(node, ast.arg) and name == "arg") or (
            isinstance(node, ast.ExceptHandler) and name == "name" and value
        ):
            value = names.get(value, value)
        parts.append(f"{name}={_dump(value, names, count)}")
    return "(" + " ".join(parts) + ")"


def _normalised(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = list(func.body)
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        body = body[1:]
    args = func.args
    params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    params += [a.arg for a in (args.vararg, args.kwarg) if a is not None]
    names: dict[str, str] = {}
    for name in [*params, *_stores(body)]:
        names.setdefault(name, f"_v{len(names)}")
    count = [0]
    dumped = _dump(body, names, count)
    return f"{len(params)}|{dumped}" if count[0] >= MIN_DUPLICATE_STATEMENTS else None


def find_duplicates(modules: list[tuple[str, ast.Module]]) -> list[list[Site]]:
    groups: dict[str, list[Site]] = defaultdict(list)
    for rel, tree in modules:
        for node in tree.body:
            funcs: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                funcs += [
                    (f"{node.name}.{n.name}", n)
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
            for shown, func in funcs:
                shape = _normalised(func)
                if shape is not None:
                    groups[shape].append((rel, func.lineno, shown))
    return sorted(sorted(g) for g in groups.values() if len(g) > 1)


def scan(repo: Path = REPO_ROOT) -> Result:
    modules = parse_src(repo)
    dead, test_only = find_unreferenced(repo, modules)
    return Result(dead=dead, test_only=test_only, duplicates=find_duplicates(modules))


def read_baseline(path: Path = BASELINE_FILE) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            kind, count = line.split()
            out[kind] = int(count)
    return out


def format_baseline(counts: dict[str, int]) -> str:
    lines = ["# dead and duplicated code under src/docket; shrink-only, regenerate with --write"]
    lines += [f"{kind} {counts[kind]}" for kind in KINDS]
    return "\n".join(lines) + "\n"


def regressions(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    bad: list[str] = []
    for kind in KINDS:
        if counts[kind] > baseline.get(kind, 0):
            bad.append(f"{kind} grew to {counts[kind]}, above baseline {baseline.get(kind, 0)}")
    return bad


def per_module(result: Result) -> dict[str, dict[str, int]]:
    table: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(KINDS, 0))
    for rel, _, _ in result.dead:
        table[rel]["dead"] += 1
    for rel, _, _ in result.test_only:
        table[rel]["test-only"] += 1
    for group in result.duplicates:
        for rel in {rel for rel, _, _ in group}:
            table[rel]["duplicate"] += 1
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print every site and group")
    parser.add_argument("--by-module", action="store_true", help="print counts per module")
    parser.add_argument("--check", action="store_true", help="exit 1 off the baseline")
    parser.add_argument("--write", action="store_true", help="overwrite the committed baseline")
    args = parser.parse_args(argv)
    result = scan()
    counts = result.counts()
    if args.by_module:
        rows = per_module(result)
        for rel, row in sorted(rows.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"{row['dead']:4} {row['test-only']:4} {row['duplicate']:4}  {rel}")
        print("dead test-only duplicate  module")
    if args.list:
        for title, sites in (("dead", result.dead), ("test-only", result.test_only)):
            print(f"== {title} ({len(sites)})")
            for rel, line, name in sites:
                print(f"{rel}:{line} {name}")
        print(f"== duplicate groups ({len(result.duplicates)})")
        for n, group in enumerate(result.duplicates, 1):
            print(f"-- group {n}")
            for rel, line, name in group:
                print(f"{rel}:{line} {name}")
    print(" ".join(f"{kind}={counts[kind]}" for kind in KINDS))
    if args.write:
        BASELINE_FILE.write_text(format_baseline(counts), encoding="utf-8")
        print(f"wrote {BASELINE_FILE.relative_to(REPO_ROOT)}")
        return 0
    if args.check:
        bad = regressions(counts, read_baseline())
        for message in bad:
            print(f"FAIL: {message}")
        print("FAIL" if bad else "OK: every count equals its baseline")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
