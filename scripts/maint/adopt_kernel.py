#!/usr/bin/env python3
"""Rewrite call sites that do by hand what a ``kernel/`` module owns to call the module.

Each rule is a function ``(tree, source, rel) -> Outcome`` registered in ``RULES``. It returns
byte-offset edits, the kernel import they need, and the sites it saw but refused to rewrite.
Only exact source spans are replaced, so untouched code is never reformatted. ``--write``
then lets ruff drop the imports the rewrite left unused and sort the new one.
``scripts/maint/measure_kernel_adoption.py`` counts what remains; lower its baseline after.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import dataclasses
import difflib
import functools
import importlib.util
import io
import itertools
import json
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "docket"
TESTS_ROOT = REPO_ROOT / "tests"
KERNEL_ROOT = SRC_ROOT / "kernel"


def _load_measure() -> object:
    path = REPO_ROOT / "scripts" / "maint" / "measure_kernel_adoption.py"
    spec = importlib.util.spec_from_file_location("_measure_kernel_adoption_codemod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Import resolution is the guard's, so the codemod and the guard agree on what a site is.
MEASURE = _load_measure()
_aliases = MEASURE._aliases  # type: ignore[attr-defined]
_dotted = MEASURE._dotted  # type: ignore[attr-defined]
_module_name = MEASURE._module_name  # type: ignore[attr-defined]
ID_MINTS: frozenset[str] = MEASURE.ID_MINTS  # type: ignore[attr-defined]


class Edit(NamedTuple):
    """Replace bytes ``start:end`` of the UTF-8 source with ``text``."""

    start: int
    end: int
    text: str
    note: str = ""  # what a ``--check`` line says instead of the replacement text


@dataclass
class Outcome:
    edits: list[Edit] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # statements the edits depend on
    unmappable: list[tuple[int, str]] = field(default_factory=list)  # (line, why refused)
    notes: list[str] = field(default_factory=list)  # facts to report that are not sites


Rule = Callable[[ast.Module, str, str], Outcome]


@functools.lru_cache(maxsize=8)
def line_starts(source: str) -> tuple[int, ...]:
    """Byte offset of each line start, split the way the tokenizer splits lines."""
    data = source.encode("utf-8")
    return (0, *(m.end() for m in re.finditer(rb"\r\n|\r|\n", data)))


def span(node: ast.expr, source: str) -> tuple[int, int]:
    """Byte span of *node*; ``col_offset`` counts UTF-8 bytes, not characters."""
    starts = line_starts(source)
    assert node.end_lineno is not None and node.end_col_offset is not None
    return (
        starts[node.lineno - 1] + node.col_offset,
        starts[node.end_lineno - 1] + node.end_col_offset,
    )


def _inside_fstring(tree: ast.Module) -> set[int]:
    """Nodes within an f-string; before Python 3.12 their positions are not trustworthy."""
    return {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for child in node.values
        for inner in ast.walk(child)
    }


# ids -------------------------------------------------------------------------------------------

IDS_IMPORT = "from docket.kernel import ids as _ids"


def _is_uuid4(node: ast.expr, aliases: dict[str, str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and _dotted(node.func, aliases) == "uuid.uuid4"
    )


def _is_hex12(node: ast.expr, aliases: dict[str, str]) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and node.slice.lower is None
        and node.slice.step is None
        and isinstance(node.slice.upper, ast.Constant)
        and type(node.slice.upper.value) is int
        and node.slice.upper.value == 12
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "hex"
        and _is_uuid4(node.value.value, aliases)
    )


def _prefixed(node: ast.JoinedStr, aliases: dict[str, str]) -> tuple[str, ast.expr] | None:
    """``f"<prefix>-{<uuid expr>}"`` as (kernel call, the uuid4 call inside), else ``None``."""
    if len(node.values) != 2:
        return None
    head, tail = node.values
    if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
        return None
    if not (isinstance(tail, ast.FormattedValue) and tail.conversion == -1):
        return None
    if tail.format_spec is not None or len(head.value) < 2 or not head.value.endswith("-"):
        return None
    prefix = json.dumps(head.value[:-1], ensure_ascii=False)
    if _is_uuid4(tail.value, aliases):
        return f"_ids.new_id({prefix})", tail.value
    if _is_hex12(tail.value, aliases):
        assert isinstance(tail.value, ast.Subscript) and isinstance(tail.value.value, ast.Attribute)
        return f"_ids.new_short_id({prefix})", tail.value.value.value
    return None


def _bare(node: ast.Call, aliases: dict[str, str]) -> tuple[str, ast.expr] | None:
    """``str(uuid4())`` as (kernel call, the uuid4 call inside), else ``None``."""
    is_str = isinstance(node.func, ast.Name) and node.func.id == "str"
    if is_str and len(node.args) == 1 and not node.keywords and _is_uuid4(node.args[0], aliases):
        return "_ids.new_uuid()", node.args[0]
    return None


def ids(tree: ast.Module, source: str, rel: str) -> Outcome:
    """Prefixed and bare uuid4 ids become ``kernel.ids`` calls; any other mint is listed."""
    aliases = _aliases(tree, rel)
    out = Outcome()
    inside = _inside_fstring(tree)
    handled: set[int] = set()
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        match = None
        if isinstance(node, ast.JoinedStr):
            match = _prefixed(node, aliases)
        elif isinstance(node, ast.Call):
            match = _bare(node, aliases)
        if match is not None:
            call, inner = match
            out.edits.append(Edit(*span(node, source), call))  # type: ignore[arg-type]
            handled.add(id(inner))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) not in handled:
            name = _dotted(node.func, aliases)
            if name in ID_MINTS:
                out.unmappable.append((node.lineno, f"{name}() in a shape no kernel.ids call has"))
    if out.edits:
        out.imports.append(IDS_IMPORT)
    return out


# text ------------------------------------------------------------------------------------------

TEXT_IMPORT = "from docket.kernel import text as _text"
ELLIPSIS = "…"


def _pure(node: ast.expr) -> bool:
    """A constant or a name/attribute chain: evaluating it once or twice gives the same value."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, (ast.Name, ast.Constant))


def _int_const(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    return None


def _module_ints(tree: ast.Module) -> dict[str, int]:
    """Module-level ``NAME = <int literal>`` bindings, to bound a named limit."""
    found: dict[str, int] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], _int_const(stmt.value)
            if isinstance(target, ast.Name) and value is not None:
                found[target.id] = value
    return found


def _len_of(node: ast.expr) -> ast.expr | None:
    """``X`` of ``len(X)``, else ``None``."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and not node.keywords
    ):
        return node.args[0]
    return None


def _same(a: ast.expr, b: ast.expr) -> bool:
    """Equal expressions, whether one is read and the other assigned."""
    return re.sub(r", ctx=\w+\(\)", "", ast.dump(a)) == re.sub(r", ctx=\w+\(\)", "", ast.dump(b))


class _Cut(NamedTuple):
    text: ast.expr
    limit: ast.expr
    marker: ast.Constant


def _ellipsized(node: ast.expr, limit: ast.expr, ints: dict[str, int]) -> _Cut | None:
    """``X[:limit - len(m)] + m`` as its parts, when the slice leaves room for exactly ``m``."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
        return None
    head, marker = node.left, node.right
    if not (isinstance(marker, ast.Constant) and isinstance(marker.value, str) and marker.value):
        return None
    if not (
        isinstance(head, ast.Subscript)
        and isinstance(head.slice, ast.Slice)
        and head.slice.lower is None
        and head.slice.step is None
        and head.slice.upper is not None
    ):
        return None
    bound, room = head.slice.upper, len(marker.value)
    literal, bound_int = _int_const(limit), _int_const(bound)
    if literal is not None and bound_int is not None:
        fits = literal - bound_int == room and bound_int >= 0
    elif (
        isinstance(bound, ast.BinOp)
        and isinstance(bound.op, ast.Sub)
        and _int_const(bound.right) == room
        and _same(bound.left, limit)
    ):
        named = ints.get(limit.id) if isinstance(limit, ast.Name) else None
        fits = named is None or named >= room
    else:
        fits = False
    return _Cut(head.value, limit, marker) if fits else None


def _compare(node: ast.expr, op: type[ast.cmpop]) -> tuple[ast.expr, ast.expr] | None:
    """``len(X) <op> L`` as (X, L), else ``None``."""
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], op)
        and (measured := _len_of(node.left)) is not None
    ):
        return None
    return measured, node.comparators[0]


def _ellipsize_call(cut: _Cut, source: str) -> str:
    data = source.encode("utf-8")

    def part(node: ast.expr) -> str:
        start, end = span(node, source)
        return data[start:end].decode("utf-8")

    extra = "" if cut.marker.value == ELLIPSIS else f", {part(cut.marker)}"
    return f"_text.ellipsize({part(cut.text)}, {part(cut.limit)}{extra})"


def _statement_span(first: ast.stmt, last: ast.stmt, source: str) -> tuple[int, int] | None:
    """Byte span from *first* to *last*, or ``None`` when a comment sits between them."""
    starts = line_starts(source)
    assert last.end_lineno is not None and last.end_col_offset is not None
    start = starts[first.lineno - 1] + first.col_offset
    end = starts[last.end_lineno - 1] + last.end_col_offset
    return None if "#" in source.encode("utf-8")[start:end].decode("utf-8") else (start, end)


def _text_if_expr(node: ast.IfExp, ints: dict[str, int]) -> _Cut | None:
    """``X if len(X) <= L else X[:L - k] + m``."""
    pair = _compare(node.test, ast.LtE)
    if pair is None or not (_same(node.body, pair[0]) and _pure(pair[0]) and _pure(pair[1])):
        return None
    cut = _ellipsized(node.orelse, pair[1], ints)
    return cut if cut is not None and _same(cut.text, pair[0]) else None


def _text_if_assign(node: ast.If, ints: dict[str, int]) -> _Cut | None:
    """``if len(X) > L: X = X[:L - k] + m`` with nothing else in the statement."""
    pair = _compare(node.test, ast.Gt)
    if pair is None or node.orelse or len(node.body) != 1:
        return None
    (body,) = node.body
    if not (
        isinstance(body, ast.Assign)
        and len(body.targets) == 1
        and _same(body.targets[0], pair[0])
        and _pure(pair[0])
        and _pure(pair[1])
    ):
        return None
    cut = _ellipsized(body.value, pair[1], ints)
    return cut if cut is not None and _same(cut.text, pair[0]) else None


def _text_return_pair(first: ast.stmt, second: ast.stmt, ints: dict[str, int]) -> _Cut | None:
    """``if len(X) <= L: return X`` followed by ``return X[:L - k] + m``."""
    if not (isinstance(first, ast.If) and not first.orelse and len(first.body) == 1):
        return None
    pair = _compare(first.test, ast.LtE)
    (body,) = first.body
    if not (
        pair is not None
        and isinstance(body, ast.Return)
        and body.value is not None
        and _same(body.value, pair[0])
        and isinstance(second, ast.Return)
        and second.value is not None
        and _pure(pair[0])
        and _pure(pair[1])
    ):
        return None
    cut = _ellipsized(second.value, pair[1], ints)
    return cut if cut is not None and _same(cut.text, pair[0]) else None


def text(tree: ast.Module, source: str, rel: str) -> Outcome:
    """One-line collapses and ``limit - len(marker)`` cuts become ``kernel.text`` calls."""
    out = Outcome()
    inside = _inside_fstring(tree)
    ints = _module_ints(tree)
    covered: list[tuple[int, int]] = []  # line ranges of rewritten code

    def rewrite(start: int, end: int, replacement: str, first: int, last: int) -> None:
        out.edits.append(Edit(start, end, replacement))
        covered.append((first, last))

    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.Call) and MEASURE._is_one_line(node):  # type: ignore[attr-defined]
            inner = node.args[0].func.value  # type: ignore[attr-defined]
            if not any(isinstance(n, ast.JoinedStr) for n in ast.walk(inner)):
                data = source.encode("utf-8")
                s, e = span(inner, source)
                call = f"_text.one_line({data[s:e].decode('utf-8')})"
                rewrite(*span(node, source), call, node.lineno, node.end_lineno or node.lineno)
        elif isinstance(node, ast.IfExp):
            if (cut := _text_if_expr(node, ints)) is not None:
                rewrite(
                    *span(node, source),
                    _ellipsize_call(cut, source),
                    node.lineno,
                    node.end_lineno or node.lineno,
                )
        elif isinstance(node, ast.If) and (cut := _text_if_assign(node, ints)) is not None:
            if (where := _statement_span(node, node, source)) is not None:
                target = _ellipsize_call(cut, source)
                original = source.encode("utf-8")
                s, e = span(cut.text, source)
                name = original[s:e].decode("utf-8")
                rewrite(*where, f"{name} = {target}", node.lineno, node.end_lineno or node.lineno)
        for field_name in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field_name, None)
            if not isinstance(stmts, list):
                continue
            for first, second in itertools.pairwise(stmts):
                cut = _text_return_pair(first, second, ints)
                where = _statement_span(first, second, source) if cut is not None else None
                if cut is not None and where is not None:
                    rewrite(
                        *where,
                        f"return {_ellipsize_call(cut, source)}",
                        first.lineno,
                        second.end_lineno or second.lineno,
                    )
    for line, shape in MEASURE.text(tree, rel):  # type: ignore[attr-defined]
        if not any(a <= line <= b for a, b in covered):
            out.unmappable.append((line, f"{shape} in a shape no kernel.text call has"))
    if out.edits:
        out.imports.append(TEXT_IMPORT)
    return out


# clock -----------------------------------------------------------------------------------------

CLOCK_IMPORT = "from docket.kernel import clock as _clock"
UTC_NAMES = frozenset({"datetime.UTC", "datetime.timezone.utc"})
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DAY_FORMAT = "%Y-%m-%d"
# Calls whose result is local, naive or in nanoseconds, so no kernel.clock read equals them.
CLOCK_REFUSED = {
    "datetime.datetime.utcnow": "naive UTC datetime; kernel.clock.now() is aware",
    "datetime.datetime.today": "local naive datetime",
    "datetime.date.today": "local date; kernel.clock.today() is the UTC date",
    "time.time_ns": "nanosecond clock; kernel.clock has no integer read",
    "time.monotonic_ns": "nanosecond clock; kernel.clock has no integer read",
    "time.perf_counter_ns": "nanosecond clock; kernel.clock has no integer read",
}
STAMP_MS_RETURN = '{n}.strftime("%Y-%m-%dT%H:%M:%S") + f".{{{n}.microsecond // 1000:03d}}Z"'


def _utc_now_call(node: ast.Call, aliases: dict[str, str]) -> bool | None:
    """True for ``datetime.now(UTC)``, False for ``datetime.now`` in any other shape, else None."""
    if _dotted(node.func, aliases) != "datetime.datetime.now":
        return None
    zones = [*node.args, *(k.value for k in node.keywords if k.arg == "tz")]
    only_zone = len(node.args) + len(node.keywords) == 1 and len(zones) == 1
    return only_zone and _dotted(zones[0], aliases) in UTC_NAMES


def _method(node: ast.expr, parents: dict[int, ast.AST]) -> tuple[str, ast.Call] | None:
    """``(name, call)`` when *node* is the receiver of ``node.name(...)``, else ``None``."""
    attr = parents.get(id(node))
    call = parents.get(id(attr)) if attr is not None else None
    if (
        isinstance(attr, ast.Attribute)
        and attr.value is node
        and isinstance(call, ast.Call)
        and call.func is attr
        and not call.keywords
    ):
        return attr.attr, call
    return None


def _read_shape(call: ast.Call, parents: dict[int, ast.AST]) -> tuple[ast.expr, str]:
    """The outermost expression a UTC ``now()`` feeds and the ``kernel.clock`` call for it."""
    step = _method(call, parents)
    if step is None:
        return call, "now"
    name, outer = step
    args = outer.args
    if name == "isoformat" and not args:
        return outer, "iso"
    if name == "timestamp" and not args:
        return outer, "epoch"
    if name == "strftime" and len(args) == 1 and isinstance(args[0], ast.Constant):
        if args[0].value == STAMP_FORMAT:
            return outer, "stamp"
        if args[0].value == DAY_FORMAT:
            return outer, "today_iso"
    if name == "date" and not args:
        again = _method(outer, parents)
        if again is not None and again[0] == "isoformat" and not again[1].args:
            return again[1], "today_iso"
        return outer, "today"
    return call, "now"


def _stamp_ms_pairs(
    tree: ast.Module, aliases: dict[str, str]
) -> list[tuple[ast.Assign, ast.Return, ast.Call]]:
    """``n = datetime.now(UTC)`` then ``return`` of exactly ``kernel.clock.stamp_ms``'s text."""
    found = []
    for node in ast.walk(tree):
        for stmts in (getattr(node, f, None) for f in ("body", "orelse", "finalbody")):
            if not isinstance(stmts, list):
                continue
            for first, second in itertools.pairwise(stmts):
                if not (
                    isinstance(first, ast.Assign)
                    and len(first.targets) == 1
                    and isinstance(first.targets[0], ast.Name)
                    and isinstance(first.value, ast.Call)
                    and _utc_now_call(first.value, aliases)
                    and isinstance(second, ast.Return)
                    and second.value is not None
                ):
                    continue
                name = first.targets[0].id
                want = ast.parse(STAMP_MS_RETURN.format(n=name), mode="eval").body
                if ast.dump(want) == ast.dump(second.value):
                    found.append((first, second, first.value))
    return found


def clock(tree: ast.Module, source: str, rel: str) -> Outcome:
    """UTC ``now()``, ``time.time`` and the monotonic clocks become ``kernel.clock`` reads."""
    aliases = _aliases(tree, rel)
    out = Outcome()
    inside = _inside_fstring(tree)
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    handled: set[int] = set()
    for first, second, read in _stamp_ms_pairs(tree, aliases):
        if (where := _statement_span(first, second, source)) is None:
            continue
        out.edits.append(Edit(*where, "return _clock.stamp_ms()"))
        handled.add(id(read))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in handled:
            continue
        name = _dotted(node.func, aliases)
        utc = _utc_now_call(node, aliases)
        if name in CLOCK_REFUSED:
            out.unmappable.append((node.lineno, f"{name}(): {CLOCK_REFUSED[name]}"))
            continue
        if utc is False:
            out.unmappable.append((node.lineno, "datetime.now() without UTC is local time"))
            continue
        if utc:
            target, kind = _read_shape(node, parents)
            replacement = f"_clock.{kind}()"
        elif name == "time.time":
            target, replacement = node, "_clock.epoch()"
        elif name in ("time.monotonic", "time.perf_counter"):
            target, replacement = node, "_clock.monotonic()"
        else:
            continue
        s, e = span(target, source)
        if id(node) in inside or id(target) in inside:
            out.unmappable.append((node.lineno, f"{name}() inside an f-string"))
        elif "#" in source.encode("utf-8")[s:e].decode("utf-8"):
            out.unmappable.append((node.lineno, f"{name}() with a comment inside its span"))
        else:
            out.edits.append(Edit(s, e, replacement))
    if out.edits:
        out.imports.append(CLOCK_IMPORT)
    return out


# errors ----------------------------------------------------------------------------------------

ERRORS_MODULE = "docket.kernel.errors"
BUILTIN_ERRORS: frozenset[str] = MEASURE.BUILTIN_ERRORS  # type: ignore[attr-defined]
# A raised builtin and the one kind that replaces it without changing what catchers see.
RAISE_KINDS = {"ValueError": "InvalidInput"}
# Public class name -> the kind it derives from; a class absent here is left for a decision.
CLASS_KINDS: dict[str, str] = {}
OWN_RENDERING = frozenset({"__init__", "__str__"})


def _raised_builtin(node: ast.Raise) -> str | None:
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return exc.id if isinstance(exc, ast.Name) and exc.id in BUILTIN_ERRORS else None


def _raise_refusal(node: ast.Raise, name: str) -> str | None:
    """Why ``raise name(...)`` cannot just swap the name, else ``None``."""
    call = node.exc
    if name not in RAISE_KINDS:
        return f"raise {name}: no kind replaces it one for one"
    if not isinstance(call, ast.Call):
        return f"bare raise {name}: there is no message to carry"
    if not call.args and not call.keywords:
        return f"raise {name}() without a message; a kind needs one (TypeError)"
    if len(call.args) != 1 or call.keywords or isinstance(call.args[0], ast.Starred):
        return f"raise {name} with other than one positional; a kind's second is the hint"
    return None


def _class_refusal(node: ast.ClassDef) -> str | None:
    """Why ``node`` cannot just swap its builtin base for a kind, else ``None``."""
    if node.name not in CLASS_KINDS:
        return f"class {node.name}: not in CLASS_KINDS"
    if len(node.bases) != 1 or node.keywords:
        return f"class {node.name}: more than one base or a class keyword"
    defined = {s.name for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if defined & OWN_RENDERING:
        return f"class {node.name}: defines {', '.join(sorted(defined & OWN_RENDERING))}; by hand"
    return None


def errors(tree: ast.Module, source: str, rel: str) -> Outcome:
    """Single-message builtin raises and listed builtin-based classes take a ``kernel.errors`` kind."""
    out = Outcome()
    raised = {line for line, _ in MEASURE.error_raises(tree, rel)}  # type: ignore[attr-defined]
    classed = {line for line, _ in MEASURE.error_classes(tree, rel)}  # type: ignore[attr-defined]
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.lineno in raised:
            name = _raised_builtin(node)
            if name is None:
                continue
            if (why := _raise_refusal(node, name)) is not None:
                out.unmappable.append((node.lineno, why))
                continue
            call = node.exc
            assert isinstance(call, ast.Call)
            kind = RAISE_KINDS[name]
            out.edits.append(Edit(*span(call.func, source), kind, f"{name} -> {kind}"))
            kinds.add(kind)
        elif isinstance(node, ast.ClassDef) and node.lineno in classed:
            if (why := _class_refusal(node)) is not None:
                out.unmappable.append((node.lineno, why))
                continue
            base, kind = node.bases[0], CLASS_KINDS[node.name]
            assert isinstance(base, ast.Name)
            out.edits.append(Edit(*span(base, source), kind, f"{base.id} -> {kind}"))
            kinds.add(kind)
    out.imports += [f"from {ERRORS_MODULE} import {k}" for k in sorted(kinds)]
    return out


# config-reads ----------------------------------------------------------------------------------

CONFIG_MODULE = "docket.config"
CURRENT_HOME_IMPORT = "from docket.kernel.home import current_home"
HOME_MODULE_PATH = KERNEL_ROOT / "home.py"


@functools.cache
def _home_class() -> type:
    spec = importlib.util.spec_from_file_location("_adopt_kernel_home", HOME_MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Home  # type: ignore[no-any-return]


@functools.cache
def _home_members() -> tuple[frozenset[str], frozenset[str]]:
    """Every public name ``Home`` offers, and the subset that are properties."""
    home = _home_class()
    names = {f.name for f in dataclasses.fields(home)}
    names |= {n for n in dir(home) if not n.startswith("_") and n != "from_environ"}
    props = {n for n in names if isinstance(getattr(home, n, None), property)}
    return frozenset(names), frozenset(props)


def _home_member(name: str) -> str | None:
    """The ``Home`` member that answers ``config.<name>``, else ``None``."""
    attr = "root" if name == "DOCKET_HOME" else name.lower()
    return attr if attr in _home_members()[0] else None


def _import_time(tree: ast.Module) -> dict[int, str]:
    """Each node evaluated when the module is imported, mapped to the context that does it."""
    found: dict[int, str] = {}

    def visit(node: ast.AST, why: str | None) -> None:
        if why is not None:
            found[id(node)] = why
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            outer = [(d, "default argument value") for d in args.defaults]
            outer += [(d, "default argument value") for d in args.kw_defaults if d is not None]
            if not isinstance(node, ast.Lambda):
                outer += [(d, "decorator argument") for d in node.decorator_list]
                outer += [(a.annotation, "annotation") for a in ast.walk(args) if _annotated(a)]
                outer += [(node.returns, "annotation")] if node.returns is not None else []
            for part, label in outer:
                visit(part, label if why is not None else None)
            for child in [node.body] if isinstance(node, ast.Lambda) else node.body:
                visit(child, None)
        elif isinstance(node, ast.ClassDef) and why is not None:
            for child in ast.iter_child_nodes(node):
                visit(child, "class body" if why == "module level" else why)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child, why)

    visit(tree, "module level")
    return found


def _annotated(node: ast.AST) -> bool:
    return isinstance(node, ast.arg) and node.annotation is not None


def _config_names(tree: ast.Module, aliases: dict[str, str]) -> set[str]:
    """Local names the module binds to ``docket.config``."""
    return {local for local, target in aliases.items() if target == CONFIG_MODULE}


def _rebound(tree: ast.Module, names: set[str]) -> set[str]:
    """Which of *names* the module also assigns, declares as a parameter or defines."""
    taken: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            taken.add(node.id)
        elif isinstance(node, ast.arg):
            taken.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            taken.add(node.name)
    return names & taken


def _handed_on(call: ast.AST | None, module: ast.Name) -> str:
    """Why the config module passed as a value is left alone; a patch of one constant says which."""
    if isinstance(call, ast.Call) and len(call.args) >= 2 and call.args[0] is module:
        key = call.args[1]
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            member = _home_member(key.value)
            if member is None:
                return f"patches config.{key.value}, which has no Home field"
            return f"patches config.{key.value}; set Home.{member} on the test's home"
    return "the config module handed on as a value"


def config_reads(tree: ast.Module, source: str, rel: str) -> Outcome:
    """``config.NAME`` reads become ``current_home().<field>``; everything else is listed."""
    aliases = _aliases(tree, rel)
    names = _config_names(tree, aliases)
    out = Outcome()
    inside = _inside_fstring(tree) if sys.version_info < (3, 12) else set()
    at_import = _import_time(tree)
    shadowed = _rebound(tree, names)
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    as_base = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
    }
    properties = _home_members()[1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id not in names:
                continue
            what = f"config.{node.attr}"
            member = _home_member(node.attr)
            call = parents.get(id(node))
            as_call = isinstance(call, ast.Call) and call.func is node
            as_call = as_call and not call.args and not call.keywords
            if node.value.id in shadowed:
                why = f"{node.value.id} is also a variable, parameter or definition here"
            elif not isinstance(node.ctx, ast.Load):
                why = "a write to the module's constant belongs to the repointers rule"
            elif member is None:
                why = "no Home field"
            elif id(node) in at_import:
                why = f"read at import time ({at_import[id(node)]}); it would freeze the home"
            elif id(node) in inside:
                why = "inside an f-string"
            elif member in properties and node.attr.islower() and not as_call:
                why = f"{member} is a Home property; the function is not called here"
            else:
                why = ""
            if why:
                out.unmappable.append((node.lineno, f"{what}: {why}"))
            elif member in properties and node.attr.islower():
                assert isinstance(call, ast.Call)
                out.edits.append(Edit(*span(call, source), f"current_home().{member}"))
            else:
                out.edits.append(Edit(*span(node, source), f"current_home().{member}"))
        elif isinstance(node, ast.Name) and node.id in names and node.id not in shadowed:
            if isinstance(node.ctx, ast.Load) and id(node) not in as_base:
                out.unmappable.append((node.lineno, _handed_on(parents.get(id(node)), node)))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if aliases.get(alias.asname or alias.name, "").startswith(f"{CONFIG_MODULE}."):
                    out.unmappable.append(
                        (node.lineno, f"imported by name: {alias.name}; rewrite its uses by hand")
                    )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(f"{CONFIG_MODULE}."):
                out.unmappable.append((node.lineno, f"named by a string: {node.value}"))
    if out.edits:
        out.imports.append(CURRENT_HOME_IMPORT)
    return out


# repointers ------------------------------------------------------------------------------------

HOME_IMPORTS = ["from docket.kernel.home import Home", "from docket.kernel.home import use_home"]
ITERATOR_IMPORT = "from collections.abc import Iterator"
THREADS = re.compile(r"\b(Thread|threading|ThreadPoolExecutor|Executor|Timer|serve_forever)\b")
MONKEYPATCH_CONTEXT = frozenset({"pytest.MonkeyPatch.context", "MonkeyPatch.context"})
BODY_FIELDS = ("body", "orelse", "finalbody")


def _repoint_stmt(stmt: ast.stmt) -> ast.Call | None:
    """The call of a statement that is exactly ``repoint_docket_home(<name>, <path>)``."""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return None
    call = stmt.value
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return call if name == "repoint_docket_home" else None


def _own_nodes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node of *fn*'s body that runs in *fn* itself, not in a nested scope."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        found.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))
    return found


def _multiline_strings(source: str) -> list[tuple[int, int]]:
    """Line ranges of string literals that span lines; re-indenting them changes their value."""
    ranges: list[tuple[int, int]] = []
    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)
    opened: list[int] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
            ranges.append((tok.start[0], tok.end[0]))
        elif fstring_start is not None and tok.type == fstring_start:
            opened.append(tok.start[0])
        elif fstring_end is not None and tok.type == fstring_end:
            first = opened.pop()
            if first != tok.end[0]:
                ranges.append((first, tok.end[0]))
    return ranges


def _is_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("fixture" in ast.unparse(d) for d in fn.decorator_list)


class _Scope(NamedTuple):
    stmts: list[ast.stmt]  # the body the repointing statement sits in
    owner: ast.AST  # the function or the MonkeyPatch.context() block that owns it
    kind: str  # "test", "fixture" or "block"


def _scope_of(stmt: ast.stmt, parents: dict[int, ast.AST], what: str = "repoint") -> _Scope | str:
    """Where a *what* statement's effect ends, or why it cannot be reproduced."""
    holder = parents[id(stmt)]
    if isinstance(holder, ast.AsyncFunctionDef):
        return "an async function"
    if isinstance(holder, ast.FunctionDef):
        if stmt not in holder.body:
            return "not directly in the function body"
        if _is_fixture(holder):
            return _Scope(holder.body, holder, "fixture")
        if holder.name.startswith("test"):
            return _Scope(holder.body, holder, "test")
        return (
            f"in helper {holder.name}(): the {what} outlives the function that makes it; "
            "turn the helper into a context manager or a fixture by hand"
        )
    if isinstance(holder, ast.With) and stmt in holder.body:
        context = holder.items[0].context_expr if len(holder.items) == 1 else None
        if isinstance(context, ast.Call) and ast.unparse(context.func) in MONKEYPATCH_CONTEXT:
            return _Scope(holder.body, holder, "block")
    return f"inside a {type(holder).__name__}, where the {what}'s end is not the block's end"


def _monkeypatch_refusal(receiver: ast.expr, scope: _Scope) -> str | None:
    """Why *receiver* is not the monkeypatch of the scope that owns the statement, else ``None``."""
    name = receiver.id if isinstance(receiver, ast.Name) else ast.unparse(receiver)
    owner = scope.owner
    if isinstance(owner, ast.With):
        target = owner.items[0].optional_vars
        mine = isinstance(receiver, ast.Name) and isinstance(target, ast.Name)
        mine = mine and target.id == name
    else:
        assert isinstance(owner, ast.FunctionDef)
        params = [
            a.arg for a in (*owner.args.posonlyargs, *owner.args.args, *owner.args.kwonlyargs)
        ]
        mine = isinstance(receiver, ast.Name) and name == "monkeypatch" and name in params
    return None if mine else f"{name} is not the monkeypatch of its own scope"


def _arg_refusal(call: ast.Call, scope: _Scope) -> str | None:
    """Why the call's arguments are not ``(<the monkeypatch>, <path>)``, else ``None``."""
    ok = len(call.args) == 2 and not call.keywords
    ok = ok and not any(isinstance(a, ast.Starred) for a in call.args)
    first = call.args[0] if call.args else None
    if not (ok and isinstance(first, ast.Name)):
        return "arguments other than (monkeypatch, path)"
    return _monkeypatch_refusal(first, scope)


def _indent(text: str, by: str) -> str:
    return "".join(f"{by}{line}" if line.strip() else line for line in text.splitlines(True))


# what opens a block at the first of these statements: (statements it covers, its ``with`` line)
Opener = Callable[[list[ast.stmt]], tuple[int, str] | None]


def _render(lines: list[str], stmts: list[ast.stmt], lo: int, hi: int, opener: Opener) -> str:
    """Lines ``lo:hi`` with each statement *opener* recognises wrapping everything after it."""
    for first in range(len(stmts)):
        if (group := opener(stmts[first:])) is not None:
            break
    else:
        return "".join(lines[lo:hi])
    taken, header = group
    stmt = stmts[first]
    covered = stmts[first : first + taken]
    assert stmt.end_lineno is not None and covered[-1].end_lineno is not None
    pad = " " * stmt.col_offset
    before = "".join(lines[lo : stmt.lineno - 1])
    # comments between the statements of one group stay above the block they now share
    between = "".join(
        line
        for a, b in itertools.pairwise(covered)
        for line in lines[(a.end_lineno or a.lineno) : b.lineno - 1]
        if line.strip()
    )
    inner = _render(lines, stmts[first + taken :], covered[-1].end_lineno, hi, opener)
    return f"{before}{between}{pad}{header}\n{_indent(inner, '    ')}"


def _wrap_scope(
    scope: _Scope,
    direct: list[ast.stmt],
    refusals: list[str],
    opener: Opener,
    what: str,
    source: str,
    strings: list[tuple[int, int]],
) -> tuple[list[Edit], str]:
    """The edits that put everything from ``direct[0]`` to the scope's end under the blocks
    *opener* opens, or the reasons it cannot be reproduced."""
    lines = source.splitlines(True)
    starts = line_starts(source)
    stmts = scope.stmts[scope.stmts.index(direct[0]) :]
    lo, hi = stmts[0].lineno - 1, stmts[-1].end_lineno or stmts[-1].lineno
    for c in direct:
        end = c.end_lineno or c.lineno
        if "#" in "".join(lines[c.lineno - 1 : end]):
            refusals.append(f"a comment inside the {what} statement")
        elif "\t" in lines[c.lineno - 1][: c.col_offset]:
            refusals.append("tab indentation")
    if any(a <= hi and lo + 1 <= b for a, b in strings):
        refusals.append("a multi-line string literal that re-indenting would change")
    owner = scope.owner
    fixture_edits: list[Edit] = []
    extra_yield = False
    if THREADS.search("".join(lines[owner.lineno - 1 : owner.end_lineno])):
        refusals.append("the function starts threads, which a ContextVar does not reach")
    if scope.kind == "fixture":
        assert isinstance(owner, ast.FunctionDef)
        plan = _fixture_plan(owner, source)
        if isinstance(plan, str):
            refusals.append(plan)
        else:
            fixture_edits, extra_yield = plan
    elif direct[-1] is scope.stmts[-1]:
        refusals.append(f"nothing follows the {what} in the {scope.kind}")
    if refusals:
        return [], "; ".join(dict.fromkeys(refusals))
    work = list(lines)
    if scope.kind == "fixture":
        _fixture_returns(owner, work)  # type: ignore[arg-type]
    if extra_yield:
        work.insert(hi, f"{' ' * direct[0].col_offset}yield\n")
    text = _render(work, stmts, lo, hi + (1 if extra_yield else 0), opener)
    end = starts[hi] if hi < len(starts) else len(source.encode("utf-8"))
    return [Edit(starts[lo], end, text, f"use_home x{len(direct)}"), *fixture_edits], ""


def _scope_imports(out: Outcome) -> None:
    """The imports a rewrite that wraps a scope in ``use_home`` and may yield depends on."""
    if any(e.text.startswith("Iterator[") for e in out.edits):
        out.imports.append(ITERATOR_IMPORT)


def repointers(tree: ast.Module, source: str, rel: str) -> Outcome:
    """A repointed home becomes ``use_home(Home(path))`` around the rest of its scope."""
    out = Outcome()
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    strings = _multiline_strings(source)
    data = source.encode("utf-8")
    sites = {line for line, _ in MEASURE.repointers(tree, rel)}  # type: ignore[attr-defined]
    done: set[int] = set()  # statements a wrapping already covers

    def opener(stmts: list[ast.stmt]) -> tuple[int, str] | None:
        call = _repoint_stmt(stmts[0])
        if call is None:
            return None
        s, e = span(call.args[1], source)
        return 1, f"with use_home(Home({data[s:e].decode('utf-8')})):"

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno in sites]
    for call in sorted(calls, key=lambda n: n.lineno):
        stmt = parents[id(call)]
        if not isinstance(stmt, ast.stmt) or _repoint_stmt(stmt) is not call:
            out.unmappable.append((call.lineno, "repoint_docket_home() used as a value"))
            continue
        if id(stmt) in done:
            continue
        scope = _scope_of(stmt, parents)
        if isinstance(scope, str):
            out.unmappable.append((call.lineno, scope))
            continue
        direct = [s for s in scope.stmts if _repoint_stmt(s) is not None]
        refusals = [r for c in direct if (r := _arg_refusal(_repoint_stmt(c), scope))]  # type: ignore[arg-type]
        edits, why = _wrap_scope(scope, direct, refusals, opener, "repoint", source, strings)
        if why:
            out.unmappable += [(c.lineno, why) for c in direct]
        out.edits += edits
        done.update(id(c) for c in direct)
    if out.edits:
        out.imports += HOME_IMPORTS
        _scope_imports(out)
    return out


def _fixture_plan(fn: ast.FunctionDef, source: str) -> tuple[list[Edit], bool] | str:
    """A fixture that holds ``use_home`` open must yield: the edits that make it a generator
    and whether a closing ``yield`` is needed, or why it cannot be made one."""
    own = _own_nodes(fn)
    if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in own):
        return [], False
    returns = [n for n in own if isinstance(n, ast.Return)]
    if any(r is not fn.body[-1] for r in returns):
        return "a fixture with a return that is not its last statement"
    edits: list[Edit] = []
    if fn.returns is not None:
        data = source.encode("utf-8")
        s, e = span(fn.returns, source)
        edits.append(Edit(s, e, f"Iterator[{data[s:e].decode('utf-8')}]"))
    return edits, not returns


def _fixture_returns(fn: ast.FunctionDef, work: list[str]) -> None:
    """Turn the fixture's closing ``return`` into ``yield``, in place on the line list."""
    last = fn.body[-1]
    if isinstance(last, ast.Return):
        line = work[last.lineno - 1].encode("utf-8")
        cut = last.col_offset
        work[last.lineno - 1] = (line[:cut] + b"yield" + line[cut + len("return") :]).decode(
            "utf-8"
        )


# config-patches --------------------------------------------------------------------------------
#
# ``monkeypatch.setattr(config, "NAME", value)`` changes a constant nothing reads once reads go
# through ``current_home()``. It becomes a ``Home`` override around the rest of its scope. The
# scope machinery is the repointers rule's, so a patch is reproduced where a repoint is and
# refused where a repoint is.

DATACLASSES_IMPORT = "import dataclasses"
USE_HOME_IMPORT = "from docket.kernel.home import use_home"
CONFIG_STRING = f"{CONFIG_MODULE}."


class _Patch(NamedTuple):
    stmt: ast.Expr
    receiver: ast.expr  # what ``setattr`` is called on: the monkeypatch
    field: str  # the Home field that holds the patched value
    value: ast.expr


@functools.cache
def _home_fields() -> frozenset[str]:
    return frozenset(f.name for f in dataclasses.fields(_home_class()))  # type: ignore[arg-type]


def _patch_field(name: str) -> tuple[str, str]:
    """The ``Home`` field a patch of ``config.<name>`` sets, else (``""``, why there is none)."""
    member = _home_member(name)
    if member is None:
        return "", f"config.{name} has no Home field"
    for candidate in (member, f"{member}_override"):
        if candidate in _home_fields():
            return candidate, ""
    if member in _home_members()[1]:
        return "", (
            f"Home.{member} is derived, not a field; set the root or the field it is derived from"
        )
    return "", f"Home.{member} is a Home method, not a field"


def _patch_call(call: ast.Call) -> tuple[ast.expr, str, ast.expr] | str:
    """(receiver, patched name, value) of ``setattr(<config>, "NAME", value)``, else why not."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return "the builtin setattr on the config module cannot be undone when the scope ends"
    if func.attr == "delattr":
        return "monkeypatch.delattr removes the constant; a Home field cannot be removed"
    args = call.args
    if any(isinstance(a, ast.Starred) for a in args) or not args:
        return "arguments other than (config, NAME, value)"
    first = args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        name = first.value.removeprefix(CONFIG_STRING)
        if len(args) != 2 or "." in name:
            return 'arguments other than ("docket.config.NAME", value)'
        value = args[1]
    else:
        if len(args) != 3:
            return "arguments other than (config, NAME, value)"
        key = args[1]
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return "the patched name is not a string literal"
        name, value = key.value, args[2]
    for keyword in call.keywords:
        flag = keyword.value
        if keyword.arg != "raising" or not (
            isinstance(flag, ast.Constant) and flag.value in (True, False)
        ):
            return "a keyword other than raising=True"
        if flag.value is False:
            return "raising=False: the constant may not exist, which a Home field cannot express"
    return func.value, name, value


def config_patches(tree: ast.Module, source: str, rel: str) -> Outcome:
    """Patches of ``docket.config`` constants become ``use_home(replace(current_home(), ...))``."""
    out = Outcome()
    aliases = _aliases(tree, rel)
    reads = _config_names(tree, aliases) | {"current_home", "use_home"}
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    strings = _multiline_strings(source)
    data = source.encode("utf-8")
    by_scope: dict[int, tuple[_Scope, list[_Patch]]] = {}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    for call in sorted((c for c in calls if MEASURE.patches_config(c, aliases)), key=_line):  # type: ignore[attr-defined]
        stmt = parents[id(call)]
        if not (isinstance(stmt, ast.Expr) and stmt.value is call):
            out.unmappable.append((call.lineno, "a config patch used as a value"))
            continue
        parts = _patch_call(call)
        if isinstance(parts, str):
            out.unmappable.append((call.lineno, parts))
            continue
        field, why = _patch_field(parts[1])
        scope = _scope_of(stmt, parents, "patch")
        if why or isinstance(scope, str):
            out.unmappable.append((call.lineno, why or str(scope)))
            continue
        if why := _monkeypatch_refusal(parts[0], scope):
            out.unmappable.append((call.lineno, why))
            continue
        patch = _Patch(stmt, parts[0], field, parts[2])
        by_scope.setdefault(id(scope.owner), (scope, []))[1].append(patch)
    for scope, patches in by_scope.values():
        taken = {id(p.stmt): p for p in patches}

        def opener(
            stmts: list[ast.stmt], taken: dict[int, _Patch] = taken
        ) -> tuple[int, str] | None:
            group: list[_Patch] = []
            for stmt in stmts:
                patch = taken.get(id(stmt))
                # a patch is applied before the next value is evaluated, so one that reads the
                # home it follows, or sets a field twice, cannot share a replace()
                if patch is None or any(p.field == patch.field for p in group):
                    break
                if (
                    group
                    and {n.id for n in ast.walk(patch.value) if isinstance(n, ast.Name)} & reads
                ):
                    break
                group.append(patch)
            if not group:
                return None
            fields = ", ".join(f"{p.field}={_text(p.value, source, data)}" for p in group)
            return len(group), f"with use_home(dataclasses.replace(current_home(), {fields})):"

        direct = [p.stmt for p in patches]
        edits, why = _wrap_scope(scope, direct, [], opener, "patch", source, strings)
        if why:
            out.unmappable += [(stmt.lineno, why) for stmt in direct]
        out.edits += edits
    if out.edits:
        out.imports += [DATACLASSES_IMPORT, CURRENT_HOME_IMPORT, USE_HOME_IMPORT]
        _scope_imports(out)
    return out


def _line(node: ast.AST) -> int:
    return getattr(node, "lineno", 0)


def _text(node: ast.expr, source: str, data: bytes) -> str:
    start, end = span(node, source)
    return data[start:end].decode("utf-8")


# wrappers --------------------------------------------------------------------------------------
#
# A wrapper is a parameterless module-level ``def`` whose whole body is one kernel call. Deleting
# one means rewriting its callers in other modules and in tests, so unlike the rules above this
# one reads the whole tree before it decides anything about a single file.

WRAPPER_KERNELS = frozenset({"clock", "ids", "text"})
SCAN_ROOTS = ("src", "tests", "scripts", "packages")
REWRITE_ROOTS = ("src/", "tests/")  # a call anywhere else is one this rule cannot rewrite


class Module(NamedTuple):
    rel: str
    path: Path
    source: str
    tree: ast.Module
    aliases: dict[str, str]
    parents: dict[int, ast.AST]
    inside: set[int]
    docstrings: set[int]


class Wrapper(NamedTuple):
    home: Module
    node: ast.FunctionDef
    kernel: str  # "clock", "ids" or "text"
    fn: str  # the kernel function whose call is the whole body

    @property
    def module(self) -> str:
        return _module_name(self.home.rel)

    @property
    def dotted(self) -> str:
        return f"{self.module}.{self.node.name}"


def _docstring_ids(tree: ast.Module) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _load_modules() -> list[Module]:
    found = []
    for root in SCAN_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if path.is_relative_to(KERNEL_ROOT) or "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(REPO_ROOT))
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=rel)
            except SyntaxError:
                continue  # a fixture that is not Python 3.11 cannot import a docket module
            parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
            found.append(
                Module(
                    rel,
                    path,
                    source,
                    tree,
                    _aliases(tree, rel),
                    parents,
                    _inside_fstring(tree),
                    _docstring_ids(tree),
                )
            )
    return found


def _wrapper_of(stmt: ast.stmt, home: Module) -> Wrapper | None:
    if not isinstance(stmt, ast.FunctionDef) or stmt.decorator_list:
        return None
    a = stmt.args
    if a.posonlyargs or a.args or a.vararg or a.kwonlyargs or a.kwarg:
        return None
    body = stmt.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    call = body[0].value
    if not (
        isinstance(call, ast.Call)
        and not call.args
        and not call.keywords
        and isinstance(call.func, ast.Attribute)
    ):
        return None
    target = _dotted(call.func.value, home.aliases) or ""
    kernel = target.removeprefix("docket.kernel.") if target.startswith("docket.kernel.") else ""
    return Wrapper(home, stmt, kernel, call.func.attr) if kernel in WRAPPER_KERNELS else None


def _kernel_alias(aliases: dict[str, str], kernel: str) -> str | None:
    """The name a module already binds ``docket.kernel.<kernel>`` to, if any."""
    names = sorted(k for k, v in aliases.items() if v == f"docket.kernel.{kernel}")
    return names[0] if names else None


class _Use(NamedTuple):
    mod: Module
    line: int
    call: ast.Call | None  # the call to replace; ``None`` for a reference that is not a call
    why: str


def _uses(w: Wrapper, mod: Module) -> list[_Use]:
    """Every reference to *w* in *mod*; a bare call is rewritable, everything else is not."""
    name = w.node.name
    if name not in mod.source:
        return []
    own = mod.rel == w.home.rel
    names_module = own or w.module in mod.source or w.module in mod.aliases.values()
    local = {k for k, v in mod.aliases.items() if v == w.dotted} | ({name} if own else set())
    out: list[_Use] = []

    def use(node: ast.Attribute | ast.Name) -> None:
        parent = mod.parents.get(id(node))
        loaded = isinstance(node.ctx, ast.Load)
        if (
            isinstance(parent, ast.Call)
            and parent.func is node
            and loaded
            and not parent.args
            and not parent.keywords
        ):
            out.append(_Use(mod, node.lineno, parent, ""))
        else:
            how = "passed as a value" if loaded else "assigned"
            out.append(_Use(mod, node.lineno, None, f"{how} in {mod.rel}:{node.lineno}"))

    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Attribute):
            if node.attr == name and _dotted(node.value, mod.aliases) == w.module:
                use(node)
        elif isinstance(node, ast.Name):
            if node.id in local:
                use(node)
        elif isinstance(node, ast.arg):
            if node.arg in local:
                out.append(_Use(mod, node.lineno, None, f"shadowed by a parameter in {mod.rel}"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in local and node is not w.node:
                out.append(_Use(mod, node.lineno, None, f"name rebound in {mod.rel}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            bare = names_module and (text == name or text.endswith(f".{name}"))
            if (bare or w.dotted in text) and id(node) not in mod.docstrings:
                out.append(_Use(mod, node.lineno, None, f"named by a string in {mod.rel}"))
    return out


def _gap(w: Wrapper) -> tuple[int, int] | None:
    """Byte span of the whole ``def`` and the blank lines after it, or ``None`` to refuse."""
    source, node = w.home.source, w.node
    lines = source.splitlines(keepends=True)
    if node.lineno >= 2 and lines[node.lineno - 2].lstrip().startswith("#"):
        return None  # a comment directly above belongs to the def; keeping it is a judgment
    starts = line_starts(source)
    end_line = node.end_lineno or node.lineno
    while end_line < len(lines) and not lines[end_line].strip():
        end_line += 1
    end = starts[end_line] if end_line < len(starts) else len(source.encode("utf-8"))
    return starts[node.lineno - 1], end


def _rewrite_call(w: Wrapper, use: _Use) -> tuple[Edit, str | None] | str:
    """The edit that replaces one call (and the import it needs), or why it cannot be."""
    mod, call = use.mod, use.call
    assert call is not None
    s, e = span(call, mod.source)
    if not mod.rel.startswith(REWRITE_ROOTS):
        return f"called from {mod.rel}, which this rule does not rewrite"
    if id(call) in mod.inside:
        return f"called inside an f-string in {mod.rel}:{use.line}"
    if "#" in mod.source.encode("utf-8")[s:e].decode("utf-8"):
        return f"call with a comment inside its span in {mod.rel}:{use.line}"
    statement = None
    local = _kernel_alias(mod.aliases, w.kernel)
    if local is None:
        local = f"_{w.kernel}"
        statement = f"from docket.kernel import {w.kernel} as {local}"
        if _conflicts(statement, mod.tree, mod.aliases):
            return f"{local} is taken by another name in {mod.rel}"
    text = f"{local}.{w.fn}()"
    return Edit(s, e, text, text), statement


def wrappers() -> dict[str, Outcome]:
    """Delete each kernel wrapper and call the kernel where it was called; refuse the rest."""
    modules = _load_modules()
    outcomes: dict[str, Outcome] = {}

    def outcome(rel: str) -> Outcome:
        return outcomes.setdefault(rel, Outcome())

    for home in (m for m in modules if m.rel.startswith("src/")):
        for stmt in home.tree.body:
            w = _wrapper_of(stmt, home)
            if w is None:
                continue
            uses = [u for mod in modules for u in _uses(w, mod)]
            refusals = [u.why for u in uses if u.call is None]
            edits: list[tuple[str, Edit, str | None]] = []
            for use in (u for u in uses if u.call is not None):
                result = _rewrite_call(w, use)
                if isinstance(result, str):
                    refusals.append(result)
                else:
                    edits.append((use.mod.rel, result[0], result[1]))
            gap = _gap(w)
            if gap is None:
                refusals.append("a comment sits directly above the def")
            if refusals or gap is None:
                reason = "; ".join(dict.fromkeys(refusals))
                outcome(home.rel).unmappable.append((w.node.lineno, f"{w.dotted}: {reason}"))
                continue
            for rel, edit, statement in edits:
                outcome(rel).edits.append(edit)
                if statement and statement not in outcome(rel).imports:
                    outcome(rel).imports.append(statement)
            note = f"delete def {w.node.name} ({len(edits)} call(s) rewritten)"
            outcome(home.rel).edits.append(Edit(*gap, "", note))
            if not w.node.name.startswith("_"):
                public = f"public name removed: {w.dotted} ({len(edits)} caller(s) rewritten)"
                outcome(home.rel).notes.append(public)
    return outcomes


# rule -> (function, text a module must contain to be parsed at all)
RULES: dict[str, tuple[Rule, str]] = {
    "ids": (ids, "uuid"),
    "text": (text, ""),
    "clock": (clock, "time"),
    "errors": (errors, "Error"),
    "config-reads": (config_reads, "config"),
    "config-patches": (config_patches, "config"),
    "repointers": (repointers, "repoint_docket_home"),
}
# the trees a rule rewrites; a rule absent here rewrites src/docket only
RULE_ROOTS: dict[str, tuple[Path, ...]] = {
    "config-reads": (SRC_ROOT, TESTS_ROOT),
    "config-patches": (TESTS_ROOT,),
    "repointers": (TESTS_ROOT,),
}
# Rules that move a scope's lines are applied one after another, each over the files the one
# before left, in this order: a patch's value may read the config (config-reads first), and a
# repoint that follows a patch must find it already rewritten, or the repoint's Home would
# replace the patched one (config-patches before repointers). Every other rule shares one pass.
HOME_ORDER = ("config-reads", "config-patches", "repointers")
# rules that read the whole tree first: rule -> the rewrite it wants per file
PROJECT_RULES: dict[str, Callable[[], dict[str, Outcome]]] = {"wrappers": wrappers}


# frame -----------------------------------------------------------------------------------------


@dataclass
class FilePlan:
    rel: str
    path: Path
    before: str
    after: str
    sites: list[tuple[int, str]] = field(default_factory=list)  # (line, rewrite)
    unmappable: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the module already uses for something, imports included."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _binding(statement: str) -> tuple[str, str]:
    """The local name an import statement binds and the dotted name it stands for."""
    stmt = ast.parse(statement).body[0]
    assert isinstance(stmt, (ast.Import, ast.ImportFrom))
    alias = stmt.names[0]
    if isinstance(stmt, ast.ImportFrom):
        return alias.asname or alias.name, f"{stmt.module}.{alias.name}"
    head = alias.name.split(".")[0]
    return (alias.asname, alias.name) if alias.asname else (head, head)


def _conflicts(statement: str, tree: ast.Module, aliases: dict[str, str]) -> bool:
    """True when the import's local name is already taken by something it does not stand for."""
    local, target = _binding(statement)
    if aliases.get(local) == target:
        return False
    return local in aliases or local in _bound_names(tree)


def _import_insertion(tree: ast.Module, source: str) -> int | None:
    """Byte offset of the line after the module's leading imports, else ``None``."""
    last: ast.stmt | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            last = stmt
        elif last is not None or not (
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        ):
            break
    if last is None or last.end_lineno is None:
        return None
    starts = line_starts(source)
    return starts[last.end_lineno] if last.end_lineno < len(starts) else len(source.encode())


def _apply(source: str, edits: list[Edit]) -> str:
    data = source.encode("utf-8")
    for edit in sorted(edits, key=lambda e: (e.start, e.end), reverse=True):
        data = data[: edit.start] + edit.text.encode("utf-8") + data[edit.end :]
    return data.decode("utf-8")


def _overlap(edits: list[Edit]) -> bool:
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    return any(a.end > b.start for a, b in itertools.pairwise(ordered))


def plan_file(path: Path, rules: list[str]) -> FilePlan | None:
    """The rewrite of one module under *rules*, or ``None`` when no rule has anything to say."""
    source = path.read_text(encoding="utf-8")
    wanted = [r for r in rules if RULES[r][1] in source]
    if not wanted:
        return None
    rel = str(path.relative_to(REPO_ROOT))
    tree = ast.parse(source, filename=rel)
    return plan_outcomes(path, source, tree, [(r, RULES[r][0](tree, source, rel)) for r in wanted])


def plan_outcomes(
    path: Path, source: str, tree: ast.Module, outcomes: list[tuple[str, Outcome]]
) -> FilePlan | None:
    """Merge what the rules decided about one module into a single rewrite of it."""
    rel = str(path.relative_to(REPO_ROOT))
    aliases = _aliases(tree, rel)
    plan = FilePlan(rel, path, source, source)
    edits: list[Edit] = []
    imports: list[str] = []
    for name, outcome in outcomes:
        plan.unmappable += outcome.unmappable
        plan.notes += outcome.notes
        if not outcome.edits:
            continue
        taken = [i for i in outcome.imports if _conflicts(i, tree, aliases)]
        if taken:
            plan.skipped.append(f"{name}: {', '.join(taken)} clashes with a name in the module")
            continue
        edits += outcome.edits
        imports += [i for i in outcome.imports if i not in imports and not _present(i, aliases)]
        starts = line_starts(source)
        plan.sites += [
            (bisect.bisect_right(starts, e.start), e.note or e.text) for e in outcome.edits
        ]
    if imports:
        at = _import_insertion(tree, source)
        if at is None:
            plan.skipped.append("no leading import block to add to")
            edits = []
        else:
            edits.append(Edit(at, at, "".join(f"{i}\n" for i in imports)))
    if _overlap(edits):
        plan.skipped.append("two rewrites overlap")
        edits = []
    if edits:
        plan.after = _apply(source, edits)
        plan.sites.sort()
    else:
        plan.sites = []
    return plan if (plan.sites or plan.unmappable or plan.skipped or plan.notes) else None


def _present(statement: str, aliases: dict[str, str]) -> bool:
    local, target = _binding(statement)
    return aliases.get(local) == target


def plan_project(rule: str) -> list[FilePlan]:
    plans = []
    for rel, outcome in sorted(PROJECT_RULES[rule]().items()):
        path = REPO_ROOT / rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        if (plan := plan_outcomes(path, source, tree, [(rule, outcome)])) is not None:
            plans.append(plan)
    return plans


def plan_tree(rules: list[str]) -> list[FilePlan]:
    if rules and rules[0] in PROJECT_RULES:
        return plan_project(rules[0])
    plans = []
    roots = dict.fromkeys(r for rule in rules for r in RULE_ROOTS.get(rule, (SRC_ROOT,)))
    for root in roots:
        wanted = [r for r in rules if root in RULE_ROOTS.get(r, (SRC_ROOT,))]
        files = (p for p in sorted(root.rglob("*.py")) if not p.is_relative_to(KERNEL_ROOT))
        plans += [plan for p in files if (plan := plan_file(p, wanted)) is not None]
    return plans


def run_ruff(paths: list[Path]) -> int:
    """Drop the imports the rewrite orphaned, sort the new one, and keep the format."""
    names = [str(p) for p in paths]
    steps = (
        ["uv", "run", "ruff", "check", "--fix", "--select", "F401,I", *names],
        ["uv", "run", "ruff", "format", *names],
    )
    return max(subprocess.run(step, cwd=REPO_ROOT).returncode for step in steps)


def stages(rules: list[str]) -> list[list[str]]:
    """*rules* as passes over the tree: the plain rules together, then each home rule alone."""
    plain = [r for r in rules if r not in HOME_ORDER]
    return ([plain] if plain else []) + [[r] for r in HOME_ORDER if r in rules]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "rules",
        nargs="*",
        help=f"default: every per-file rule ({', '.join(RULES)}); "
        f"{', '.join(PROJECT_RULES)} reads the whole tree and runs alone. "
        f"{', '.join(HOME_ORDER)} each run as their own pass, in that order; a dry run or "
        "--check shows each against the tree as it is on disk, only --write feeds one the next",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the diff (the default)")
    parser.add_argument("--write", action="store_true", help="apply the rewrites, then run ruff")
    parser.add_argument("--check", action="store_true", help="exit 1 if a rewritable site remains")
    parser.add_argument("--unmappable", action="store_true", help="print sites left alone")
    args = parser.parse_args()
    if unknown := set(args.rules) - set(RULES) - set(PROJECT_RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")
    if set(args.rules) & set(PROJECT_RULES) and len(args.rules) > 1:
        parser.error(f"{', '.join(PROJECT_RULES)} rewrites across files and runs alone")
    if args.write and args.check:
        parser.error("--write and --check are exclusive")

    passes = stages(args.rules or list(RULES))
    total, status = 0, 0
    for rules in passes:
        plans = plan_tree(rules)
        rewritable = [p for p in plans if p.sites]
        sites = sum(len(p.sites) for p in rewritable)
        total += sites
        if len(passes) > 1:
            print(f"\n== {', '.join(rules)}")
        if args.check:
            for p in rewritable:
                for line, text in p.sites:
                    print(f"{p.rel}:{line}  -> {text}")
        elif not args.write:
            for p in rewritable:
                sys.stdout.writelines(
                    difflib.unified_diff(
                        p.before.splitlines(keepends=True),
                        p.after.splitlines(keepends=True),
                        f"a/{p.rel}",
                        f"b/{p.rel}",
                    )
                )
        if args.unmappable:
            for p in plans:
                for line, why in p.unmappable:
                    print(f"unmappable {p.rel}:{line}  {why}")
        for p in plans:
            for why in p.skipped:
                print(f"skipped {p.rel}: {why}")
            for note in p.notes:
                print(f"note {p.rel}: {note}")

        print(f"\n{sites} site(s) in {len(rewritable)} file(s)")
        if args.write and rewritable:
            for p in rewritable:
                p.path.write_text(p.after, encoding="utf-8")
            status = max(status, run_ruff([p.path for p in rewritable]))
    if args.write:
        return status
    return 1 if args.check and total else 0


if __name__ == "__main__":
    sys.exit(main())
