#!/usr/bin/env python3
"""Move every ``cmd_*`` body out of ``cli/__init__.py`` into its group module.

The registry keeps the app, the callback and one registration per command.
Modes: ``--dry-run`` (plan only), ``--write`` (idempotent move), ``--check``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "src" / "docket" / "cli"
INIT = CLI / "__init__.py"
SEARCH = ("src", "tests", "scripts")
MAX_REGISTRY_FUNCTION = 10

TARGETS: dict[str, list[str]] = {
    "_task": ["cmd_approve", "cmd_deny", "cmd_chat", "cmd_runs", "cmd_trace"],
    "_pod": ["cmd_add", "cmd_pod", "cmd_info", "cmd_delete", "cmd_maintain", "cmd_profile"],
    "_pod_config": [
        "cmd_config",
        "cmd_validate",
        "cmd_pipeline",
        "cmd_roles",
        "cmd_policies",
        "cmd_plugins",
        "cmd_recipes",
    ],
    "_status": ["cmd_status", "cmd_cost", "cmd_metrics", "cmd_snapshot"],
    "_inbox": ["cmd_inbox"],
    "_agents": ["cmd_init"],
    "_log": ["cmd_audit"],
    "_setup": ["cmd_doctor", "cmd_completions"],
    "_setup_model": ["cmd_models", "cmd_keys"],
    "_setup_notify": [
        "cmd_channels",
        "cmd_wire",
        "cmd_unwire",
        "cmd_notify",
        "cmd_conversations",
    ],
    "_setup_export": ["cmd_exporters"],
    "_setup_sandbox": ["cmd_gates"],
    "_setup_mcp": ["cmd_mcp"],
    "_service": ["cmd_serve"],
    "_exec": ["cmd_harness"],
    "_remove": [
        "cmd_list",
        "cmd_context",
        "cmd_logs",
        "cmd_edit",
        "cmd_scope",
        "cmd_persona",
        "cmd_help",
    ],
}
DOCSTRINGS = {
    "_task": "The task commands.\nHolds approve, deny, chat, runs and trace.",
    "_pod_config": "The pod configuration commands.\nHolds config, validate, pipeline, roles, policies, plugins and recipes.",
    "_log": "The log commands.\nHolds audit.",
    "_setup": "The setup commands.\nHolds doctor and completions.",
    "_setup_model": "The model setup commands.\nHolds models and keys.",
    "_setup_notify": "The notification setup commands.\nHolds channels, wire, unwire, notify and conversations.",
    "_setup_export": "The export setup commands.\nHolds exporters.",
    "_setup_sandbox": "The sandbox setup commands.\nHolds gates.",
    "_setup_mcp": "The MCP setup commands.\nHolds mcp.",
    "_service": "The service commands.\nHolds serve.",
    "_exec": "The exec commands.\nHolds harness.",
    "_remove": "The commands being removed.\nHolds list, context, logs, edit, scope, persona and help.",
}
KEEP = {"app", "_default"}
SHARED: dict[str, str] = {
    "_pick_agent": "_agents",
    "_test_cmd_for_stack": "_agents",
    "_delete_pod": "_pod",
    "_resolve_version": "_setup",
    "_version_callback": "_setup",
}
REGISTRY_EXEMPT = {"_default"}
TARGET_OF = {c: m for m, cs in TARGETS.items() for c in cs}

Import = tuple[str, str, str]  # (module or "", name, asname)


def _lines(src: str) -> list[str]:
    return src.split("\n")


def _span(node: ast.stmt, lines: list[str]) -> str:
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def _first_line(node: ast.FunctionDef) -> int:
    return min([node.lineno] + [d.lineno for d in node.decorator_list])


def _bound(imp: Import) -> str:
    return imp[2] or imp[1].split(".")[0]


def _imports(tree: ast.Module) -> list[Import]:
    out: list[Import] = []
    for n in tree.body:
        if isinstance(n, ast.Import):
            out += [("", a.name, a.asname or "") for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module != "__future__":
            out += [(n.module or "", a.name, a.asname or "") for a in n.names]
    return out


def _render(imps: list[Import]) -> list[str]:
    plain = sorted(f"import {n}" + (f" as {a}" if a else "") for m, n, a in imps if not m)
    grouped: dict[str, list[str]] = defaultdict(list)
    for m, n, a in imps:
        if m:
            grouped[m].append(n + (f" as {a}" if a else ""))
    froms = [f"from {m} import {', '.join(sorted(v))}" for m, v in sorted(grouped.items())]
    return plain + froms


def _loaded(node: ast.AST) -> set[str]:
    """Names read in ``node`` that are not bound locally inside it."""
    loads: set[str] = set()
    local: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            (loads if isinstance(n.ctx, ast.Load) else local).add(n.id)
        elif isinstance(n, ast.arg):
            local.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            local |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.ExceptHandler)):
            local.add(n.name or "")
    return loads - local


class Plan:
    def __init__(self) -> None:
        self.src = INIT.read_text(encoding="utf-8")
        self.lines = _lines(self.src)
        self.tree = ast.parse(self.src)
        self.funcs = {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        self.cmds = [
            n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name in TARGET_OF
        ]
        self.imports = _imports(self.tree)
        self.by_bound = {_bound(i): i for i in self.imports}
        helpers = {
            n for n in self.funcs if n not in TARGET_OF and n not in KEEP and n not in SHARED
        }
        self.refs = {n: _loaded(f) & (helpers | set(TARGET_OF)) for n, f in self.funcs.items()}
        self.shared_refs = {n: _loaded(f) & set(SHARED) for n, f in self.funcs.items()}
        self.consumers: dict[str, set[str]] = defaultdict(set)
        for c in self.cmds:
            seen: set[str] = set()
            stack = [c.name]
            while stack:
                for r in self.refs[stack.pop()]:
                    if r in helpers and r not in seen:
                        seen.add(r)
                        stack.append(r)
            for h in seen:
                self.consumers[h].add(c.name)
        self.external = {h: self._external(h) for h in helpers}
        self.shared: dict[str, str] = {}
        self.carried: dict[str, str] = {}
        for h in sorted(helpers):
            mods = {TARGET_OF[c] for c in self.consumers[h]}
            if self.external[h]:
                self.shared[h] = "referenced outside: " + ", ".join(self.external[h])
            elif len(mods) > 1:
                self.shared[h] = "used by " + ", ".join(sorted(self.consumers[h]))
            elif mods:
                self.carried[h] = mods.pop()
            else:
                self.shared[h] = "no cmd_* consumer"
        # A helper that calls a left-behind helper must not move without it.
        for h in list(self.carried):
            if self.refs[h] & set(self.shared):
                self.shared[h] = "calls shared " + ", ".join(
                    sorted(self.refs[h] & set(self.shared))
                )
                del self.carried[h]

    def _external(self, name: str) -> list[str]:
        pat = re.compile(rf"\bcli\.{name}\b|from docket\.cli import [^\n]*\b{name}\b")
        hits = []
        for d in SEARCH:
            for p in sorted((ROOT / d).rglob("*.py")):
                if p == INIT or p == Path(__file__):
                    continue
                if pat.search(p.read_text(encoding="utf-8")):
                    hits.append(str(p.relative_to(ROOT)))
        return hits

    def moved(self, module: str) -> list[ast.FunctionDef]:
        names = (
            set(TARGETS[module])
            | {h for h, m in self.carried.items() if m == module}
            | {h for h, m in SHARED.items() if m == module}
        )
        return [n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name in names]

    def hoist(self, module: str) -> list[Import]:
        used: set[str] = set()
        for f in self.moved(module):
            used |= _loaded(f)
        found = {self.by_bound[n] for n in used if n in self.by_bound}
        for f in self.moved(module):
            for name in self.shared_refs[f.name]:
                if SHARED[name] != module:
                    found.add((f"docket.cli.{SHARED[name]}", name, ""))
        return sorted(found)

    def registration(self, node: ast.FunctionDef) -> str:
        call = next(d for d in node.decorator_list if isinstance(d, ast.Call))
        text = ast.get_source_segment(self.src, call) or ""
        args = text[text.index("(") + 1 : text.rindex(")")]
        mod = TARGET_OF[node.name]
        sep = "\n" if "\n" in args else ""
        return f"app.command({sep}{args}{sep})({mod}.{node.name})"

    def problems(self) -> list[str]:
        out = [f"stray non-blank line {n} between definitions" for n in self.strays()]
        for module in TARGETS:
            have = _target_imports(CLI / f"{module}.py")
            for i in self.hoist(module):
                if _bound(i) in have and have[_bound(i)] != i:
                    out.append(f"{module}: import conflict on {_bound(i)}")
            clash = {f.name for f in self.moved(module)} & {
                n.name for n in _defs(CLI / f"{module}.py")
            }
            out += [f"{module}: name clash {n}" for n in sorted(clash)]
        for c in self.cmds:
            out += [
                f"{c.name} calls command {r}" for r in sorted(self.refs[c.name] & set(TARGET_OF))
            ]
        return out

    def strays(self) -> list[int]:
        covered: set[int] = set()
        for n in self.tree.body:
            first = _first_line(n) if isinstance(n, ast.FunctionDef) else n.lineno
            covered |= set(range(first, (n.end_lineno or n.lineno) + 1))
        return [i + 1 for i, t in enumerate(self.lines) if t.strip() and i + 1 not in covered]


def _target_imports(path: Path) -> dict[str, Import]:
    if not path.exists():
        return {}
    return {_bound(i): i for i in _imports(ast.parse(path.read_text(encoding="utf-8")))}


def cmd_dry_run() -> int:
    p = Plan()
    print(f"registry source: {len(p.lines)} lines, {len(p.cmds)} commands to move")
    for module in TARGETS:
        moved = p.moved(module)
        new = "" if (CLI / f"{module}.py").exists() else " (new)"
        total = sum((f.end_lineno or 0) - f.lineno + 1 for f in moved)
        print(f"\n{module}{new}: {total} lines moved")
        for f in moved:
            kind = "cmd" if f.name in TARGET_OF else "helper"
            print(f"  {kind:6} {f.name}  lines {f.lineno}-{f.end_lineno}")
        print("  hoist: " + ("; ".join(_render(p.hoist(module))) or "none"))
    print("\nshared helpers (left in the registry):")
    for h, why in p.shared.items():
        f = p.funcs[h]
        print(f"  {h}  {(f.end_lineno or 0) - f.lineno + 1} lines  {why}")
    remaining = [n for n in p.funcs if n in p.shared]
    print("\nregistry functions over the limit after the move:")
    for n in remaining:
        f = p.funcs[n]
        size = (f.end_lineno or 0) - f.lineno + 1
        if size > MAX_REGISTRY_FUNCTION and n not in REGISTRY_EXEMPT:
            print(f"  {n}  {size} lines")
    found = p.problems()
    for line in found:
        print(f"UNRESOLVED {line}")
    return 1 if found else 0


def _defs(path: Path) -> list[ast.FunctionDef]:
    if not path.exists():
        return []
    return [
        n
        for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef)
    ]


def cmd_write() -> int:
    p = Plan()
    if not p.cmds:
        print("nothing to move")
        return 0
    found = p.problems()
    if found:
        print("refusing:\n  " + "\n  ".join(found), file=sys.stderr)
        return 1
    for module in TARGETS:
        moved = p.moved(module)
        if not moved:
            continue
        path = CLI / f"{module}.py"
        blocks = "\n\n\n".join(_span(f, p.lines) for f in moved)
        have = _target_imports(path)
        new = [i for i in p.hoist(module) if _bound(i) not in have]
        if path.exists():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            tops = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            lines = _lines(text)
            at = tops[-1].end_lineno if tops else 0
            lines[at:at] = _render(new)
            path.write_text(
                "\n".join(lines).rstrip("\n") + "\n\n\n" + blocks + "\n", encoding="utf-8"
            )
        else:
            doc = DOCSTRINGS[module]
            head = f'"""{doc}"""\n\nfrom __future__ import annotations\n\n'
            imp = "\n".join(_render(new))
            path.write_text(
                head + (imp + "\n\n\n" if imp else "\n") + blocks + "\n", encoding="utf-8"
            )
    drop = {f.name for m in TARGETS for f in p.moved(m)}
    kept: list[str] = []
    for n in p.tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Expr)):
            continue
        if isinstance(n, ast.FunctionDef):
            if n.name in drop:
                continue
            kept.append(_span_with_decorators(n, p.lines))
        else:
            kept.append(_span(n, p.lines))
    regs = "\n".join(p.registration(c) for c in p.cmds)
    rest_src = "\n\n\n".join(kept) + "\n\n\n" + regs + "\n"
    used = _loaded(ast.parse(rest_src)) | {"app"}
    keep_imps = [i for i in p.imports if _bound(i) in used]
    mods = sorted(m for m in TARGETS if p.moved(m))
    doc = _span(p.tree.body[0], p.lines)
    head = doc + "\n\nfrom __future__ import annotations\n\n"
    head += "\n".join(_render(keep_imps)) + "\nfrom docket.cli import " + ", ".join(mods)
    head += "\nfrom docket.cli._setup import _version_callback\n\n\n"
    INIT.write_text(head + rest_src, encoding="utf-8")
    print(
        f"moved {len(drop)} definitions into {len(mods)} modules; run ruff format and ruff check --fix"
    )
    return 0


def _span_with_decorators(node: ast.FunctionDef, lines: list[str]) -> str:
    return "\n".join(lines[_first_line(node) - 1 : node.end_lineno])


def cmd_check() -> int:
    tree = ast.parse(INIT.read_text(encoding="utf-8"))
    problems: list[str] = []
    defined: dict[str, list[str]] = defaultdict(list)
    for path in sorted(CLI.glob("_*.py")):
        for f in _defs(path):
            if f.name in TARGET_OF:
                defined[f.name].append(path.name)
    registered: dict[str, int] = defaultdict(int)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Call) and n.args:
            arg = n.args[0]
            outer = n.func.func
            if (
                isinstance(arg, ast.Attribute)
                and isinstance(outer, ast.Attribute)
                and outer.attr == "command"
            ):
                registered[arg.attr] += 1
    for cmd, module in TARGET_OF.items():
        if defined.get(cmd) != [f"{module}.py"]:
            problems.append(f"{cmd}: defined in {defined.get(cmd, [])}, want [{module}.py]")
        if registered.get(cmd, 0) != 1:
            problems.append(f"{cmd}: registered {registered.get(cmd, 0)} times in cli/__init__.py")
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            size = (n.end_lineno or 0) - n.lineno + 1
            if size > MAX_REGISTRY_FUNCTION and n.name not in REGISTRY_EXEMPT:
                problems.append(
                    f"cli/__init__.py::{n.name} is {size} lines (max {MAX_REGISTRY_FUNCTION})"
                )
    for line in problems:
        print(line)
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args()
    return cmd_dry_run() if a.dry_run else cmd_write() if a.write else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
