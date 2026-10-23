#!/usr/bin/env python3
"""Count the code that still does by hand what a ``kernel/`` module owns.

One rule per kernel module: reading the clock, minting an id, cutting text, declaring or raising
an error outside the ``kernel/errors.py`` tree, reading the environment, and reading
``docket.config`` or calling ``repoint_docket_home`` instead of using ``Home``. Each count may
only go down: ``tests/guards/kernel_adoption_baseline.txt`` records it, and the commit that
migrates sites lowers it with ``--write``. ``kernel/`` itself is never scanned.
"""

from __future__ import annotations

import argparse
import ast
import functools
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "docket"
TESTS_ROOT = REPO_ROOT / "tests"
KERNEL_ROOT = SRC_ROOT / "kernel"
BASELINE_FILE = REPO_ROOT / "tests" / "guards" / "kernel_adoption_baseline.txt"

Hit = tuple[str, int, str]  # (path relative to the repo, line, what was found)
Detector = Callable[[ast.Module, str], Iterator[tuple[int, str]]]

CLOCK_READS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
    }
)
ID_MINTS = frozenset({"uuid.uuid1", "uuid.uuid4"})
ENV_READS = frozenset({"os.environ", "os.getenv", "os.putenv", "os.unsetenv"})
CUT_MARKERS = ("…", "...", "truncated")
BUILTIN_ERRORS = frozenset(
    {
        "BaseException",
        "Exception",
        "ValueError",
        "RuntimeError",
        "LookupError",
        "KeyError",
        "OSError",
    }
)
# Raised as part of normal operation and caught by their own callers, so not a DocketError.
SIGNALS = frozenset({"ApprovalNoop", "ConsultParked"})


def _module_name(rel: str) -> str:
    """The dotted module a ``src/`` path defines, for resolving relative imports."""
    parts = Path(rel).with_suffix("").parts
    parts = parts[parts.index("docket") :] if "docket" in parts else parts
    return ".".join(p for p in parts if p != "__init__")


def _aliases(tree: ast.Module, rel: str) -> dict[str, str]:
    """Each local name bound by an import, mapped to the dotted name it stands for."""
    package = _module_name(rel).split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    names[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package[: len(package) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            for alias in node.names:
                names[alias.asname or alias.name] = f"{base}.{alias.name}"
    return names


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """``a.b.c`` with ``a`` resolved through the module's imports, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in aliases:
        return None
    return ".".join([aliases[node.id], *reversed(parts)])


def _calls(tree: ast.Module, rel: str, wanted: frozenset[str]) -> Iterator[tuple[int, str]]:
    """Every call of *wanted*, and every reference passed on uncalled (``clock=time.monotonic``),
    because a function handed on reads the clock as surely as one called in place."""
    aliases = _aliases(tree, rel)
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Name)) or not isinstance(node.ctx, ast.Load):
            continue
        if (name := _dotted(node, aliases)) in wanted:
            yield node.lineno, f"{name}()" if id(node) in called else name


def clock(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A read of the wall or monotonic clock; ``kernel.clock`` owns both."""
    yield from _calls(tree, rel, CLOCK_READS)


def ids(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A uuid minted directly; ``kernel.ids`` owns the shape of every id."""
    yield from _calls(tree, rel, ID_MINTS)


def _is_head_slice(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and node.slice.lower is None
        and node.slice.upper is not None
        and node.slice.step is None
    )


def _has_marker(node: ast.expr) -> bool:
    texts = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)]
    return any(isinstance(t, str) and any(m in t for m in CUT_MARKERS) for t in texts)


def _is_one_line(node: ast.Call) -> bool:
    func, args = node.func, node.args
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "join"
        and isinstance(func.value, ast.Constant)
        and func.value.value == " "
        and len(args) == 1
        and isinstance(args[0], ast.Call)
        and isinstance(args[0].func, ast.Attribute)
        and args[0].func.attr == "split"
        and not args[0].args
    )


def _measured(scope: ast.AST) -> set[str]:
    """Every expression *scope* takes ``len()`` of, as an ``ast.dump``."""
    return {
        ast.dump(node.args[0])
        for node in ast.walk(scope)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
    }


def _cut(parts: list[ast.expr], whole: ast.expr, measured: set[str]) -> bool:
    """A head slice of something whose length the function checks, next to a marker. The
    length check is what tells a cut from an always-short prefix such as ``digest[:12]``."""
    heads = [p for p in parts if _is_head_slice(p)]
    return _has_marker(whole) and any(ast.dump(h.value) in measured for h in heads)  # type: ignore[attr-defined]


def text(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A hand-made cut with a marker, or a hand-made whitespace collapse; ``kernel.text``."""
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    innermost: dict[ast.AST, ast.AST] = {}
    for scope in sorted(scopes, key=lambda s: s.lineno):
        for node in ast.walk(scope):
            innermost[node] = scope
    measured_in = {id(s): _measured(s) for s in [tree, *scopes]}
    for node in ast.walk(tree):
        measured = measured_in[id(innermost.get(node, tree))]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if _cut([node.left, node.right], node, measured):
                yield node.lineno, "text[:n] + marker"
        elif isinstance(node, ast.JoinedStr):
            values = [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
            if _cut(values, node, measured):
                yield node.lineno, 'f"{text[:n]}…marker"'
        elif isinstance(node, ast.Call) and _is_one_line(node):
            yield node.lineno, '" ".join(text.split())'


def error_classes(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A public exception class on a builtin instead of a ``kernel.errors`` kind."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        if node.name in SIGNALS:
            continue
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        if bases & BUILTIN_ERRORS:
            yield node.lineno, f"class {node.name}({', '.join(sorted(bases))})"


def error_raises(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A builtin exception raised for the operator to read; a ``kernel.errors`` kind carries it."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(exc, ast.Name) and exc.id in BUILTIN_ERRORS:
            yield node.lineno, f"raise {exc.id}"


def environ(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A read or write of the process environment; ``Home`` is built from it once."""
    aliases = _aliases(tree, rel)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Attribute, ast.Name))
            and isinstance(node.ctx, ast.Load)
            and (name := _dotted(node, aliases)) in ENV_READS
        ):
            yield node.lineno, name


def config_reads(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A name read from ``docket.config``; ``current_home()`` answers it."""
    aliases = _aliases(tree, rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if aliases.get(node.value.id) == "docket.config":
                yield node.lineno, f"config.{node.attr}"
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if aliases.get(alias.asname or alias.name, "").startswith("docket.config."):
                    yield node.lineno, f"from docket.config import {alias.name}"


def repointers(tree: ast.Module, rel: str) -> Iterator[tuple[int, str]]:
    """A test isolating its home by patching constants; ``use_home(Home(tmp_path))`` replaces it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "repoint_docket_home":
                yield node.lineno, "repoint_docket_home()"


# rule -> (detector, tree it scans, text a module must contain to be parsed at all)
RULES: dict[str, tuple[Detector, Path, str]] = {
    "clock": (clock, SRC_ROOT, ""),
    "ids": (ids, SRC_ROOT, ""),
    "text": (text, SRC_ROOT, ""),
    "error-classes": (error_classes, SRC_ROOT, ""),
    "error-raises": (error_raises, SRC_ROOT, ""),
    "environ": (environ, SRC_ROOT, ""),
    "config-reads": (config_reads, SRC_ROOT, ""),
    "repointers": (repointers, TESTS_ROOT, "repoint_docket_home"),
}


@functools.cache
def _parsed(root: Path, needle: str) -> tuple[tuple[str, ast.Module], ...]:
    """Every module under *root* outside ``kernel/`` whose text contains *needle*, parsed."""
    files = (p for p in sorted(root.rglob("*.py")) if not p.is_relative_to(KERNEL_ROOT))
    sources = ((str(p.relative_to(REPO_ROOT)), p.read_text(encoding="utf-8")) for p in files)
    return tuple((rel, ast.parse(src, filename=rel)) for rel, src in sources if needle in src)


def scan(rule: str) -> list[Hit]:
    """Every site *rule* finds outside ``kernel/``, in path and line order."""
    detector, root, needle = RULES[rule]
    return sorted(
        (rel, line, what)
        for rel, tree in _parsed(root, needle)
        for line, what in detector(tree, rel)
    )


def read_baseline(path: Path = BASELINE_FILE) -> dict[str, int]:
    pairs = (line.split() for line in path.read_text(encoding="utf-8").splitlines() if line)
    return {rule: int(count) for rule, count in pairs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rules", nargs="*", help=f"default: every rule ({', '.join(RULES)})")
    parser.add_argument("--list", action="store_true", help="print every site, not only counts")
    parser.add_argument("--check", action="store_true", help="exit 1 if a count is off baseline")
    parser.add_argument("--write", action="store_true", help="record the current counts")
    args = parser.parse_args()
    if unknown := set(args.rules) - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")

    rules = args.rules or list(RULES)
    counts = {rule: scan(rule) for rule in rules}
    baseline = read_baseline() if BASELINE_FILE.exists() else {}
    for rule, hits in counts.items():
        print(f"{rule:14} {len(hits):4}  (baseline {baseline.get(rule, '-')})")
        if args.list:
            for rel, line, what in hits:
                print(f"    {rel}:{line}  {what}")

    if args.write:
        merged = {**baseline, **{rule: len(hits) for rule, hits in counts.items()}}
        lines = [f"{rule} {merged[rule]}" for rule in RULES if rule in merged]
        BASELINE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwrote {BASELINE_FILE.relative_to(REPO_ROOT)}")
        return 0
    if args.check:
        off = {r: len(h) for r, h in counts.items() if len(h) != baseline.get(r)}
        if off:
            print(f"\nFAIL: off baseline: {off}")
            return 1
        print("\nOK: every count equals its baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
