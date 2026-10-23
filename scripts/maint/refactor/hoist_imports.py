#!/usr/bin/env python3
"""Hoist function-local ``docket.*`` imports to module level; keep only the real cycles.

Every candidate under ``src/docket`` (``templates/`` and ``if TYPE_CHECKING:`` skipped) is hoisted,
merged and deduplicated against the top-level imports, then PROVEN by importing every module in
its own forked ``python -I`` child. Adaptive group testing isolates what must stay local:
``optional`` (guarded by ``except ImportError``), ``collision`` (name clash, builtin shadow, or the
function rebinds the name), ``cycle`` (hoisting breaks some import), ``unverified`` (module does
not import even unchanged). Trials run on a temp copy of ``src`` through the root's own ruff
config; a second run is a no-op. ``--dry-run`` writes nothing; ``--ledger FILE`` writes JSON.
Flags: ``--root``, ``--jobs``, ``--python`` (interpreter with the dependencies). Exit 0 done, 2 error.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import dataclasses
import json
import os
import shutil
import subprocess
import symtable
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

PACKAGE = "docket"
SKIPPED_DIRS = {"templates", "__pycache__"}
NO_VERIFY = {"__main__"}
OPTIONAL_EXCEPTIONS = {"ImportError", "ModuleNotFoundError"}

Key = tuple[str, str, str, str]  # (kind, module-or-dotted, imported-or-"", name it binds)


class AnalysisError(Exception):
    """A tree the tool cannot analyse."""


# --------------------------------------------------------------------------- verification

_VERIFY_SRC = r"""
import importlib, json, os, sys, traceback
job = json.load(sys.stdin)
sys.path.insert(0, job["src"])
for top in job["third_party"]:
    try:
        importlib.import_module(top)
    except BaseException:
        pass
result = {}
pending = list(job["modules"])
running = {}

def start(name):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        code = 0
        message = ""
        try:
            importlib.import_module(name)
        except BaseException as exc:
            code = 1
            frames = [
                "%s:%s" % (f.filename.rsplit("src/", 1)[-1], f.lineno)
                for f in traceback.extract_tb(exc.__traceback__)
            ]
            message = "%s: %s @ %s" % (type(exc).__name__, exc, " > ".join(frames[-6:]))
        try:
            os.write(w, message[:4000].encode("utf-8", "replace"))
        finally:
            os._exit(code)
    os.close(w)
    running[pid] = (name, r)

def reap():
    pid, status = os.wait()
    name, r = running.pop(pid)
    chunks = []
    while True:
        data = os.read(r, 65536)
        if not data:
            break
        chunks.append(data)
    os.close(r)
    text = b"".join(chunks).decode("utf-8", "replace")
    result[name] = None if os.waitstatus_to_exitcode(status) == 0 else (text or "exit %s" % status)

while pending or running:
    while pending and len(running) < job["jobs"]:
        start(pending.pop(0))
    if running:
        reap()
sys.stdout.write(json.dumps(result))
"""


def verify(
    python: str, src: Path, modules: Sequence[str], third_party: Sequence[str], jobs: int
) -> dict[str, str | None]:
    """Import each module in its own forked child; map name -> None (ok) or the error."""
    with tempfile.TemporaryDirectory(prefix="hoist-home-") as home:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(HOME=home, DOCKET_HOME=str(Path(home) / ".docket"), XDG_CONFIG_HOME=home)
        job = {
            "src": str(src),
            "modules": list(modules),
            "third_party": list(third_party),
            "jobs": max(1, jobs),
        }
        proc = subprocess.run(
            [python, "-I", "-c", _VERIFY_SRC],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            env=env,
            cwd=home,
            check=False,
        )
    if proc.returncode != 0:
        raise AnalysisError(f"verification process failed: {proc.stderr.strip()[-800:]}")
    result: dict[str, str | None] = json.loads(proc.stdout)
    return result


# --------------------------------------------------------------------------- collection


@dataclasses.dataclass(frozen=True)
class Binding:
    """One name an import statement binds, and what it binds it to."""

    name: str
    key: Key


@dataclasses.dataclass
class Candidate:
    module: str
    line: int
    path: tuple[str, ...]  # enclosing def/class names, outermost first
    text: str
    kind: str  # "from" | "import"
    target: str  # the imported module (from) or "" (import)
    names: list[tuple[str, str | None]]  # (imported/dotted name, asname)
    comment: str | None
    bindings: list[Binding]
    line_node: cst.SimpleStatementLine
    reason: str | None = None  # None while still a trial candidate
    detail: str = ""
    cid: int = -1

    @property
    def function(self) -> str:
        return ".".join(self.path)


def _dotted(node: cst.BaseExpression | None) -> str:
    if node is None:
        return ""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted(node.value)}.{node.attr.value}"
    raise AnalysisError(f"unsupported dotted expression {type(node).__name__}")


def _asname(alias: cst.ImportAlias) -> str | None:
    if alias.asname is None:
        return None
    name = alias.asname.name
    return name.value if isinstance(name, cst.Name) else None


def _is_docket(name: str) -> bool:
    return name == PACKAGE or name.startswith(PACKAGE + ".")


def _is_type_checking(test: cst.BaseExpression) -> bool:
    if isinstance(test, cst.Name):
        return test.value == "TYPE_CHECKING"
    if isinstance(test, cst.Attribute):
        return test.attr.value == "TYPE_CHECKING"
    return False


def _catches_import_error(handler: cst.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    if isinstance(handler.type, cst.Tuple):
        exprs = [e.value for e in handler.type.elements]
    else:
        exprs = [handler.type]
    return any(_dotted(e).split(".")[-1] in OPTIONAL_EXCEPTIONS for e in exprs)


def _bindings(small: cst.Import | cst.ImportFrom) -> list[Binding] | None:
    """The names a (docket) import statement binds; None when it is not a plain docket import."""
    out = _raw_bindings(small)
    if not out or not all(_is_docket(b.key[1]) for b in out):
        return None  # relative, star, foreign or mixed statements are left alone
    return out


class _Collector(cst.CSTVisitor):
    def __init__(self, module: str, wrapper: MetadataWrapper) -> None:
        self.module = module
        self.positions = wrapper.resolve(PositionProvider)
        self.found: list[Candidate] = []
        self.path: list[str] = []
        self.fn_depth = 0
        self.skip_depth = 0  # inside `if TYPE_CHECKING:`
        self.optional_depth = 0  # inside a try body whose handler swallows ImportError

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self.path.append(node.name.value)
        return True

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self.path.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self.path.append(node.name.value)
        self.fn_depth += 1
        return True

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self.path.pop()
        self.fn_depth -= 1

    def visit_If(self, node: cst.If) -> bool:
        if not _is_type_checking(node.test):
            return True
        self.skip_depth += 1
        node.body.visit(self)
        self.skip_depth -= 1
        if node.orelse is not None:
            node.orelse.visit(self)
        return False

    def visit_Try(self, node: cst.Try) -> bool:
        if not any(_catches_import_error(h) for h in node.handlers):
            return True
        self.optional_depth += 1
        node.body.visit(self)
        self.optional_depth -= 1
        for handler in node.handlers:
            handler.visit(self)
        if node.orelse is not None:
            node.orelse.visit(self)
        if node.finalbody is not None:
            node.finalbody.visit(self)
        return False

    def visit_SimpleStatementLine(self, node: cst.SimpleStatementLine) -> bool:
        if self.fn_depth and not self.skip_depth:
            for small in node.body:
                if isinstance(small, cst.Import | cst.ImportFrom):
                    self._add(node, small)
        return False

    def _add(self, line: cst.SimpleStatementLine, small: cst.Import | cst.ImportFrom) -> None:
        bindings = _bindings(small)
        if bindings is None:
            return
        names: list[tuple[str, str | None]] = []
        target = ""
        if isinstance(small, cst.ImportFrom):
            target = _dotted(small.module)
            assert not isinstance(small.names, cst.ImportStar)
            aliases = small.names
        else:
            aliases = small.names
        for alias in aliases:
            names.append((_dotted(alias.name), _asname(alias)))
        comment = line.trailing_whitespace.comment
        self.found.append(
            Candidate(
                module=self.module,
                line=int(self.positions[small].start.line),
                path=tuple(self.path),
                text=cst.Module([]).code_for_node(small),
                kind="from" if isinstance(small, cst.ImportFrom) else "import",
                target=target,
                names=names,
                comment=comment.value if comment else None,
                bindings=bindings,
                line_node=line,
                reason="optional" if self.optional_depth else None,
            )
        )


# --------------------------------------------------------------------------- transformation


def _suites(stmt: cst.If | cst.Try | cst.With | cst.For | cst.While) -> list[cst.BaseSuite]:
    out: list[cst.BaseSuite] = [stmt.body]
    if isinstance(stmt, cst.If):
        orelse = stmt.orelse
        while orelse is not None:
            out.append(orelse.body)
            orelse = orelse.orelse if isinstance(orelse, cst.If) else None
    elif isinstance(stmt, cst.Try):
        out.extend(h.body for h in stmt.handlers)
        if stmt.orelse is not None:
            out.append(stmt.orelse.body)
        if stmt.finalbody is not None:
            out.append(stmt.finalbody.body)
    elif isinstance(stmt, cst.For | cst.While) and stmt.orelse is not None:
        out.append(stmt.orelse.body)
    return out


def _is_import_line(stmt: cst.CSTNode) -> bool:
    return isinstance(stmt, cst.SimpleStatementLine) and all(
        isinstance(s, cst.Import | cst.ImportFrom) for s in stmt.body
    )


def _import_only(stmt: cst.CSTNode) -> bool:
    """An import line, or an if/try whose every statement is one (a guarded import block)."""
    if _is_import_line(stmt):
        return True
    if not isinstance(stmt, cst.If | cst.Try):
        return False
    inner = [
        s for suite in _suites(stmt) if isinstance(suite, cst.IndentedBlock) for s in suite.body
    ]
    return bool(inner) and all(
        _import_only(s)
        or (isinstance(s, cst.SimpleStatementLine) and all(isinstance(p, cst.Pass) for p in s.body))
        for s in inner
    )


def _is_docstring(stmt: cst.CSTNode) -> bool:
    return (
        isinstance(stmt, cst.SimpleStatementLine)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], cst.Expr)
        and isinstance(stmt.body[0].value, cst.SimpleString | cst.ConcatenatedString)
    )


def _insertion_index(body: Sequence[cst.CSTNode]) -> int:
    """Index just after the last statement of the module's leading import block."""
    i = 1 if body and _is_docstring(body[0]) else 0
    after = i
    while i < len(body) and _import_only(body[i]):
        i += 1
        after = i
    return after


class _Rewriter(cst.CSTTransformer):
    def __init__(self, removed: set[int], inserted: list[cst.SimpleStatementLine]) -> None:
        self.removed = removed  # id() of the original SimpleStatementLine nodes
        self.inserted = inserted

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        if id(original_node) in self.removed:
            return cst.RemoveFromParent()
        return updated_node

    def leave_IndentedBlock(
        self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock
    ) -> cst.BaseSuite:
        if not updated_node.body:
            return updated_node.with_changes(body=[cst.SimpleStatementLine([cst.Pass()])])
        first = original_node.body[0] if original_node.body else None
        if first is not None and id(first) in self.removed:
            # the removed first statement carried the block's opening blank line
            head = updated_node.body[0]
            if isinstance(head, cst.SimpleStatementLine | cst.BaseCompoundStatement):
                kept = [ln for ln in head.leading_lines if ln.comment is not None]
                return updated_node.with_changes(
                    body=[head.with_changes(leading_lines=kept), *updated_node.body[1:]]
                )
        return updated_node

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        if not self.inserted:
            return updated_node
        body = list(updated_node.body)
        at = _insertion_index(body)
        body[at:at] = self.inserted
        return updated_node.with_changes(body=body)


def _render(
    kind: str, target: str, names: list[tuple[str, str | None]], comment: str | None
) -> str:
    listed = ", ".join(f"{n} as {a}" if a else n for n, a in names)
    text = f"import {listed}" if kind == "import" else f"from {target} import {listed}"
    return f"{text}  {comment}" if comment else text


def _plan_insertions(chosen: list[Candidate], present: set[Key]) -> list[str]:
    """New top-level statements for the chosen candidates, merged per module."""
    merged: dict[str, list[tuple[str, str | None]]] = {}
    slots: list[str] = []  # "\0<module>" placeholders keep first-seen order
    for cand in chosen:
        pairs = [
            (pair, b)
            for pair, b in zip(cand.names, cand.bindings, strict=True)
            if b.key not in present
        ]
        if not pairs:
            continue
        if cand.kind == "from" and not cand.comment:
            if cand.target not in merged:
                merged[cand.target] = []
                slots.append(f"\0{cand.target}")
            for pair, _ in pairs:
                if pair not in merged[cand.target]:
                    merged[cand.target].append(pair)
        else:
            text = _render(cand.kind, cand.target, [p for p, _ in pairs], cand.comment)
            if text not in slots:
                slots.append(text)
    return [_render("from", s[1:], merged[s[1:]], None) if s.startswith("\0") else s for s in slots]


def render_module(module: cst.Module, chosen: list[Candidate], present: set[Key]) -> str:
    inserted: list[cst.SimpleStatementLine] = []
    for text in _plan_insertions(chosen, present):
        stmt = cst.parse_statement(text + "\n")
        assert isinstance(stmt, cst.SimpleStatementLine)
        inserted.append(stmt)
    rewriter = _Rewriter({id(c.line_node) for c in chosen}, inserted)
    return module.visit(rewriter).code


# --------------------------------------------------------------------------- module facts


def _module_import_keys(module: cst.Module) -> tuple[set[Key], set[Key]]:
    """(unconditional top-level import keys, keys of every module-level import at any depth)."""
    direct: set[Key] = set()
    anywhere: set[Key] = set()

    def scan(stmts: Sequence[cst.CSTNode], top: bool) -> None:
        for stmt in stmts:
            if isinstance(stmt, cst.SimpleStatementLine):
                for small in stmt.body:
                    if isinstance(small, cst.Import | cst.ImportFrom):
                        for b in _raw_bindings(small):
                            anywhere.add(b.key)
                            if top:
                                direct.add(b.key)
            elif isinstance(stmt, cst.If | cst.Try | cst.With | cst.For | cst.While):
                for suite in _suites(stmt):
                    if isinstance(suite, cst.IndentedBlock):
                        scan(suite.body, False)

    scan(module.body, True)
    return direct, anywhere


def _raw_bindings(small: cst.Import | cst.ImportFrom) -> list[Binding]:
    """Bindings of any import statement (not only docket ones)."""
    out: list[Binding] = []
    if isinstance(small, cst.ImportFrom):
        if small.relative or small.module is None or isinstance(small.names, cst.ImportStar):
            return out
        target = _dotted(small.module)
        for alias in small.names:
            imported = _dotted(alias.name)
            bound = _asname(alias) or imported
            out.append(Binding(bound, ("from", target, imported, bound)))
        return out
    for alias in small.names:
        dotted = _dotted(alias.name)
        asname = _asname(alias)
        top = dotted.split(".")[0]
        bound = asname or top
        out.append(Binding(bound, ("import", dotted if asname else top, "", bound)))
    return out


def _find_tables(table: symtable.SymbolTable, path: tuple[str, ...]) -> list[symtable.SymbolTable]:
    if not path:
        return [table]
    out: list[symtable.SymbolTable] = []
    for child in table.get_children():
        if child.get_name() == path[0]:
            out.extend(_find_tables(child, path[1:]))
    return out


def _bound_locally(table: symtable.SymbolTable, name: str) -> bool:
    try:
        sym = table.lookup(name)
    except KeyError:
        return False
    return bool(sym.is_local() or sym.is_declared_global() or sym.is_parameter())


@dataclasses.dataclass
class ModuleInfo:
    name: str
    rel: Path  # path under src/
    source: str
    tree: cst.Module
    candidates: list[Candidate]
    direct: set[Key]
    anywhere: set[Key]


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _iter_sources(src: Path) -> list[Path]:
    pkg = src / PACKAGE
    if not pkg.is_dir():
        raise AnalysisError(f"no package at {pkg}")
    return [
        p.relative_to(src)
        for p in sorted(pkg.rglob("*.py"))
        if not SKIPPED_DIRS & set(p.relative_to(src).parts)
    ]


def _analyse(name: str, rel: Path, source: str) -> ModuleInfo | None:
    wrapper = MetadataWrapper(cst.parse_module(source))
    collector = _Collector(name, wrapper)
    wrapper.module.visit(collector)
    if not collector.found:
        return None
    direct, anywhere = _module_import_keys(wrapper.module)
    return ModuleInfo(name, rel, source, wrapper.module, collector.found, direct, anywhere)


def classify_static(info: ModuleInfo) -> None:
    """Mark candidates that must stay put for a reason other than a cycle."""
    module_table = symtable.symtable(info.source, info.name, "exec")
    claimed: dict[str, Key] = {}
    for cand in info.candidates:
        if cand.reason is not None:
            continue
        clash = False
        for b in cand.bindings:
            if b.name in dir(builtins):
                clash = True
            if b.key in info.anywhere:
                pass  # the module already imports exactly this binding
            else:
                try:
                    sym = module_table.lookup(b.name)
                except KeyError:
                    sym = None
                if sym is not None and (
                    sym.is_assigned() or sym.is_namespace() or sym.is_imported()
                ):
                    clash = True
            if claimed.get(b.name, b.key) != b.key:
                clash = True
        if clash:
            cand.reason = "collision"
            continue
        claimed.update({b.name: b.key for b in cand.bindings})
    live = [c for c in info.candidates if c.reason is None]
    if not live:
        return
    # once the import is gone the function must not still bind the name some other way
    table = symtable.symtable(render_module(info.tree, live, set()), info.name, "exec")
    for cand in live:
        tables = _find_tables(table, cand.path)
        if any(_bound_locally(t, b.name) for t in tables for b in cand.bindings):
            cand.reason = "collision"


# --------------------------------------------------------------------------- the workspace


def _third_party(src: Path, rels: Sequence[Path]) -> list[str]:
    tops: set[str] = set()
    for rel in rels:
        for node in ast.walk(ast.parse((src / rel).read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            tops.update(n.split(".")[0] for n in names)
    return sorted(t for t in tops if t != PACKAGE and t not in sys.stdlib_module_names)


class Workspace:
    def __init__(self, root: Path, work: Path, python: str, jobs: int) -> None:
        self.root = root
        self.src = work / "src"
        self.python = python
        self.jobs = jobs
        self.config = root / "pyproject.toml"
        shutil.copytree(root / "src", self.src, ignore=shutil.ignore_patterns("__pycache__"))
        rels = _iter_sources(self.src)
        self.modules = [_module_name(r) for r in rels if r.stem not in NO_VERIFY]
        self.third_party = _third_party(self.src, rels)
        self.infos: list[ModuleInfo] = []
        for rel in rels:
            info = _analyse(_module_name(rel), rel, (self.src / rel).read_text(encoding="utf-8"))
            if info is not None:
                classify_static(info)
                self.infos.append(info)
        for number, cand in enumerate(c for i in self.infos for c in i.candidates):
            cand.cid = number
        self.cache: dict[tuple[str, frozenset[int]], str] = {}
        self.on_disk = {i.name: i.source for i in self.infos}
        self.trials = 0

    def run_ruff(self, files: Sequence[Path]) -> None:
        if not files:
            return
        exe = shutil.which("ruff")
        base = [exe] if exe else [self.python, "-m", "ruff"]
        config = ["--config", str(self.config)] if self.config.is_file() else ["--isolated"]
        common = ["--quiet", "--no-cache", *config, *map(str, files)]
        subprocess.run([*base, "check", "--fix", *common], capture_output=True, check=False)
        subprocess.run([*base, "format", *common], capture_output=True, check=False)

    def chosen(self, info: ModuleInfo, selection: set[int]) -> list[Candidate]:
        return [c for c in info.candidates if c.cid in selection]

    def text_for(self, info: ModuleInfo, selection: set[int]) -> str:
        ids = frozenset(c.cid for c in self.chosen(info, selection))
        return self.cache[(info.name, ids)] if ids else info.source

    def trial(self, selection: set[int]) -> dict[str, str | None]:
        """Write the selection into the temporary tree and import every module."""
        self.trials += 1
        fresh: list[ModuleInfo] = []
        for info in self.infos:
            ids = frozenset(c.cid for c in self.chosen(info, selection))
            if ids and (info.name, ids) not in self.cache:
                fresh.append(info)
                text = render_module(info.tree, self.chosen(info, selection), info.direct)
                (self.src / info.rel).write_text(text, encoding="utf-8")
                self.on_disk[info.name] = text
        self.run_ruff([self.src / i.rel for i in fresh])
        for info in fresh:
            ids = frozenset(c.cid for c in self.chosen(info, selection))
            self.cache[(info.name, ids)] = (self.src / info.rel).read_text(encoding="utf-8")
            self.on_disk[info.name] = self.cache[(info.name, ids)]
        for info in self.infos:
            text = self.text_for(info, selection)
            if self.on_disk[info.name] != text:
                (self.src / info.rel).write_text(text, encoding="utf-8")
                self.on_disk[info.name] = text
        return verify(self.python, self.src, self.modules, self.third_party, self.jobs)


def search(ws: Workspace, baseline_bad: set[str]) -> set[int]:
    """Adaptive group testing for the largest hoistable set; marks the rest ``cycle``."""
    live: dict[int, Candidate] = {
        c.cid: c for info in ws.infos for c in info.candidates if c.reason is None
    }
    for cand in list(live.values()):
        if cand.module in baseline_bad:
            cand.reason = "unverified"
            del live[cand.cid]
    accepted: set[int] = set()

    def extend(items: list[int]) -> None:
        if not items:
            return
        result = ws.trial(accepted | set(items))
        bad = sorted(m for m, e in result.items() if e is not None and m not in baseline_bad)
        if not bad:
            accepted.update(items)
            return
        if len(items) == 1:
            live[items[0]].reason = "cycle"
            live[items[0]].detail = f"{bad[0]}: {result[bad[0]]}"
            return
        mid = len(items) // 2
        extend(items[:mid])
        extend(items[mid:])

    extend(sorted(live))
    return accepted


# --------------------------------------------------------------------------- entry point


def build_ledger(
    ws: Workspace, accepted: set[int], baseline_bad: dict[str, str | None]
) -> dict[str, object]:
    modules: dict[str, object] = {}
    totals = {"found": 0, "hoisted": 0, "cycle": 0, "collision": 0, "optional": 0, "unverified": 0}
    for info in ws.infos:
        kept: list[dict[str, object]] = []
        hoisted = 0
        for c in info.candidates:
            totals["found"] += 1
            if c.cid in accepted:
                hoisted += 1
                totals["hoisted"] += 1
                continue
            reason = c.reason or "cycle"
            totals[reason] += 1
            entry: dict[str, object] = {
                "line": c.line,
                "function": c.function,
                "statement": c.text,
                "reason": reason,
            }
            if c.detail:
                entry["detail"] = c.detail
            kept.append(entry)
        modules[info.name] = {"hoisted": hoisted, "kept": kept}
    return {"totals": totals, "baseline_import_failures": baseline_bad, "modules": modules}


def run(root: Path, dry_run: bool, ledger: Path | None, python: str, jobs: int) -> int:
    root = root.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="hoist-work-") as tmp:
            ws = Workspace(root, Path(tmp), python, jobs)
            base = ws.trial(set())
            baseline_bad = {m: e for m, e in base.items() if e is not None}
            if base and len(baseline_bad) == len(base):
                raise AnalysisError("no module of the package imports; check --python")
            accepted = search(ws, set(baseline_bad))
            data = build_ledger(ws, accepted, baseline_bad)
            changed: list[Path] = []
            for info in ws.infos:
                text = ws.text_for(info, accepted)
                if text != info.source:
                    changed.append(root / "src" / info.rel)
                    if not dry_run:
                        changed[-1].write_text(text, encoding="utf-8")
            if changed and not dry_run:
                ws.run_ruff(changed)
    except AnalysisError as exc:
        print(f"hoist_imports: {exc}", file=sys.stderr)
        return 2
    totals = data["totals"]
    assert isinstance(totals, dict)
    print(
        f"found {totals['found']}  hoisted {totals['hoisted']}  kept: cycle {totals['cycle']}, "
        f"collision {totals['collision']}, optional {totals['optional']}, "
        f"unverified {totals['unverified']}  "
        f"({len(changed)} file(s) {'would change' if dry_run else 'changed'}, {ws.trials} trials)"
    )
    if ledger is not None:
        ledger.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hoist function-local docket imports.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--dry-run", action="store_true", help="write nothing, report counts")
    parser.add_argument("--ledger", type=Path, help="write the JSON ledger here")
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter with the dependencies"
    )
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 8))
    args = parser.parse_args(argv)
    return run(args.root, args.dry_run, args.ledger, args.python, args.jobs)


if __name__ == "__main__":
    raise SystemExit(main())
