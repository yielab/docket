# ruff: noqa
"""One-shot: fold every AST-identical test helper or fixture into tests/support/<owner>.py.

Run once from the repository root; the card's last commit deletes this file. Groups whose free
names do not resolve identically in every copy are reported and left for a hand edit.
"""

from __future__ import annotations

import ast
import builtins
import collections
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("tests")
SKIP_PARTS = {"fixtures", "golden", "support", "__pycache__"}
SERVICE_ONLY = 'monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")'

RULES: list[tuple[str, str]] = [
    (
        "http",
        r"live_server|urlopen|http\.client|HTTPConnection|^_?(post|get|put|post_raw|request)$|^_?server$",
    ),
    ("trace", r"trace|audit|_project_all|span"),
    ("git", r"^_?git$|^_?repo_dir$|git_|_git|pgrep"),
    (
        "llm",
        r"final|tool_call_turn|summariz|ChatResponse|^_?ctx$|^_?hop$|implementer_messages|backoff|LlmBackend",
    ),
    (
        "home",
        r"hermetic|isolate|fake_home|api_home|approvals_dir|runs_file|point_config|global_providers|^_?home$|use_home",
    ),
    (
        "pods",
        r"seed|pod_home|bind_|write_meta|^_?meta$|members|^_?ids$|lead_ws|setup_agent|put_task|planned_unit|unit_context|^_?unit$|workspace|policy|pod_input",
    ),
    ("cli", r"CliRunner|invoke|^_?run$|^_?call$|^_?add$|reachable|pod_cli"),
]


def is_test_file(p: Path) -> bool:
    return not (set(p.parts) & SKIP_PARTS) and p.suffix == ".py" and p.name != "__init__.py"


def strip_doc(node: ast.AST) -> ast.AST:
    node = ast.parse(ast.unparse(node)).body[0]
    body = node.body  # type: ignore[attr-defined]
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined]
    return node


def dump(node: ast.AST) -> str:
    return ast.dump(strip_doc(node))


def is_fixture(node: ast.FunctionDef) -> bool:
    return any("fixture" in ast.unparse(d) for d in node.decorator_list)


class Mod:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text()
        self.lines = self.text.split("\n")
        self.tree = ast.parse(self.text)
        self.funcs: dict[str, ast.FunctionDef] = {}
        self.imports: dict[str, ast.stmt] = {}
        self.other: dict[str, ast.stmt] = {}
        for n in self.tree.body:
            if isinstance(n, ast.FunctionDef):
                self.funcs[n.name] = n
            elif isinstance(n, ast.Import):
                for a in n.names:
                    self.imports[(a.asname or a.name).split(".")[0]] = n
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    self.imports[a.asname or a.name] = n
            elif isinstance(n, ast.ClassDef):
                self.other[n.name] = n
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        self.other[t.id] = n

    def span(self, n: ast.FunctionDef | ast.ClassDef | ast.stmt) -> tuple[int, int]:
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        return start, n.end_lineno or n.lineno


def free_names(fn: ast.FunctionDef) -> set[str]:
    loads: set[str] = set()
    bound: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            (loads if isinstance(n.ctx, ast.Load) else bound).add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n is not fn:
            bound.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add((a.asname or a.name).split(".")[0])
    return {x for x in loads - bound if not hasattr(builtins, x)}


def classify(name: str, src: str) -> str:
    for mod, pat in RULES:
        if re.search(pat, name):
            return mod
    for mod, pat in RULES:
        if re.search(pat, src[:1500]):
            return mod
    return "pods"


def main(apply: bool) -> int:
    mods = {p: Mod(p) for p in sorted(ROOT.rglob("*.py")) if is_test_file(p)}
    groups: dict[tuple[str, str], list[Mod]] = collections.defaultdict(list)
    for m in mods.values():
        for name, fn in m.funcs.items():
            if name.startswith("test_"):
                continue
            groups[(name, dump(fn))].append(m)
    cand = {k: v for k, v in groups.items() if len(v) > 1}

    svc_only: set[tuple[str, str]] = set()
    for k in cand:
        fn = cand[k][0].funcs[k[0]]
        body = [ast.unparse(s) for s in strip_doc(fn).body]  # type: ignore[attr-defined]
        if is_fixture(fn) and body == [SERVICE_ONLY.replace('"', "'")]:
            svc_only.add(k)

    blocked: dict[tuple[str, str], str] = {}
    deps_of: dict[tuple[str, str], list[tuple[str, tuple[str, str] | str]]] = {}
    for _ in range(10):
        changed = False
        for k, ms in cand.items():
            if k in blocked or k in svc_only:
                continue
            first = ms[0]
            deps: list[tuple[str, tuple[str, str] | str]] = []
            ok = True
            for name in sorted(free_names(first.funcs[k[0]])):
                kinds = set()
                for m in ms:
                    if name in m.funcs:
                        kinds.add(("f", dump(m.funcs[name])))
                    elif name in m.imports:
                        imp = m.imports[name]
                        al = [a for a in imp.names if (a.asname or a.name).split(".")[0] == name][0]  # type: ignore[attr-defined]
                        mod = getattr(imp, "module", None) or ""
                        lvl = getattr(imp, "level", 0)
                        kinds.add(("i", type(imp).__name__, mod, lvl, al.name, al.asname))
                    elif name in m.other:
                        kinds.add(
                            (
                                "o",
                                dump(m.other[name])
                                if isinstance(m.other[name], ast.ClassDef)
                                else ast.dump(m.other[name]),
                            )
                        )
                    else:
                        kinds.add(("?", name))
                if len(kinds) != 1 or next(iter(kinds))[0] == "?":
                    blocked[k] = f"free name {name!r} differs or is unresolved"
                    ok = False
                    break
                kind = next(iter(kinds))
                if kind[0] == "f":
                    dk = (name, kind[1])
                    if dk not in cand or dk in blocked or dk in svc_only:
                        blocked[k] = f"depends on helper {name!r} that is not foldable"
                        ok = False
                        break
                    deps.append((name, dk))
                else:
                    deps.append((name, kind[0]))
            if ok:
                deps_of[k] = deps
            else:
                changed = True
        if not changed:
            break

    movable = [k for k in cand if k not in blocked and k not in svc_only]

    owner: dict[tuple[str, str], str] = {}
    for k in movable:
        fn = cand[k][0].funcs[k[0]]
        src = "\n".join(cand[k][0].lines[cand[k][0].span(fn)[0] - 1 : cand[k][0].span(fn)[1]])
        owner[k] = classify(k[0], src)

    pre_const: dict[str, dict[tuple[str, str], str]] = collections.defaultdict(dict)
    supnames: dict[tuple[str, str], str] = {}
    used: dict[str, set[str]] = collections.defaultdict(set)
    for sp in (ROOT / "support").glob("*.py"):
        for n in ast.parse(sp.read_text()).body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                used[sp.stem].add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    if isinstance(t, ast.Name):
                        used[sp.stem].add(t.id)
                        pre_const[sp.stem][(t.id, ast.dump(n))] = t.id
    for k in movable:
        base = k[0][1:] if k[0].startswith("_") and len(k[0]) > 1 else k[0]
        if hasattr(builtins, base):
            base = k[0]
        nm, i = base, 2
        while nm in used[owner[k]]:
            nm = f"{base}_{i}"
            i += 1
        used[owner[k]].add(nm)
        supnames[k] = nm

    print(
        f"groups={len(cand)} movable={len(movable)} service_only={len(svc_only)} blocked={len(blocked)}"
    )
    for k, why in blocked.items():
        print("BLOCKED", k[0], [str(m.path) for m in cand[k]][:3], why)
    by_mod = collections.Counter(owner.values())
    print(dict(by_mod))
    if not apply:
        for k in movable:
            print(owner[k], k[0], "->", supnames[k], len(cand[k]))
        return 0

    # ---- build support modules
    seen_const = pre_const
    out: dict[str, dict[str, list[str]]] = {
        m: {"imports": [], "consts": [], "defs": []} for m in by_mod
    }
    for k in movable:
        first = cand[k][0]
        fn = first.funcs[k[0]]
        mod = owner[k]
        renames: dict[str, str] = {}
        for name, d in deps_of[k]:
            if isinstance(d, tuple):
                renames[name] = supnames[d]
                if owner[d] != mod:
                    out[mod]["imports"].append(
                        f"from tests.support.{owner[d]} import {supnames[d]}"
                    )
            elif d == "i":
                imp = first.imports[name]
                al = [a for a in imp.names if (a.asname or a.name).split(".")[0] == name][0]  # type: ignore[attr-defined]
                if isinstance(imp, ast.Import):
                    out[mod]["imports"].append(
                        f"import {al.name}" + (f" as {al.asname}" if al.asname else "")
                    )
                else:
                    dots = "." * imp.level
                    out[mod]["imports"].append(
                        f"from {dots}{imp.module or ''} import {al.name}"
                        + (f" as {al.asname}" if al.asname else "")
                    )
            else:
                node = first.other[name]
                seg = "\n".join(first.lines[first.span(node)[0] - 1 : first.span(node)[1]])
                dk = ast.dump(node)
                cn = seen_const[mod].get((name, dk))
                known = cn is not None
                if cn is None:
                    cn, i = name, 2
                    taken = set(seen_const[mod].values()) | used[mod]
                    while cn in taken:
                        cn = f"{name}_{i}"
                        i += 1
                    seen_const[mod][(name, dk)] = cn
                    cseg = re.sub(rf"^{re.escape(name)}\b", cn, seg, count=1)
                    out[mod]["consts"].append(cseg)
                if cn != name:
                    renames[name] = cn
        # textual slice with renames
        s, e = first.span(fn)
        seg_lines = [ln.encode() for ln in first.lines[s - 1 : e]]
        edits = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and n.id in renames and renames[n.id] != n.id:
                edits.append((n.lineno - s, n.col_offset, n.end_col_offset, renames[n.id].encode()))
        for ln, c0, c1, new in sorted(edits, reverse=True):
            seg_lines[ln] = seg_lines[ln][:c0] + new + seg_lines[ln][c1:]
        text = b"\n".join(seg_lines).decode()
        text = re.sub(rf"^def {re.escape(k[0])}\(", f"def {supnames[k]}(", text, flags=re.M)
        out[mod]["defs"].append(text)

    sup = ROOT / "support"
    sup.mkdir(exist_ok=True)
    (sup / "__init__.py").write_text(
        '"""Shared test support: one owner per helper and fixture."""\n'
    )
    for mod, parts in out.items():
        p = sup / f"{mod}.py"
        existing = p.read_text() if p.exists() else ""
        body = (
            f'"""Shared {mod} helpers and fixtures for the docket suite."""\n\nfrom __future__ import annotations\n\n'
            + "\n".join(sorted(set(parts["imports"])))
            + "\n\n\n"
            + "\n\n\n".join(parts["consts"] + parts["defs"])
            + "\n"
        )
        if existing:
            body = (
                existing.rstrip("\n")
                + "\n\n\n"
                + "\n\n\n".join(parts["consts"] + parts["defs"])
                + "\n"
            )
            imps = "\n".join(sorted(set(parts["imports"])))
            body = body.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\n" + imps + "\n",
                1,
            )
        p.write_text(body)

    # ---- rewrite files
    touched: set[Path] = set()
    for m in mods.values():
        removals: list[tuple[int, int]] = []
        imports: dict[str, list[str]] = collections.defaultdict(list)
        assigns: list[str] = []
        for name, fn in m.funcs.items():
            if name.startswith("test_"):
                continue
            k = (name, dump(fn))
            if k in svc_only:
                removals.append(m.span(fn))
            elif k in movable:
                removals.append(m.span(fn))
                mod = owner[k]
                if is_fixture(fn):
                    assigns.append(f"{name} = _support_{mod}.{supnames[k]}")
                    imports["__mods__"].append(mod)
                else:
                    imports[mod].append(f"{supnames[k]} as {name}")
        if not removals:
            continue
        lines = list(m.lines)
        for s, e in sorted(removals, reverse=True):
            while e < len(lines) and lines[e].strip() == "":
                e += 1
            del lines[s - 1 : e]
        new_imports = []
        for mod in sorted(set(imports.pop("__mods__", []))):
            new_imports.append(f"from tests.support import {mod} as _support_{mod}")
        for mod, names in sorted(imports.items()):
            new_imports.append(f"from tests.support.{mod} import {', '.join(sorted(names))}")
        last_imp = max(
            (n.end_lineno or 0 for n in m.tree.body if isinstance(n, (ast.Import, ast.ImportFrom))),
            default=0,
        )
        shift = sum(e - s + 1 for s, e in removals if e < last_imp)
        at = last_imp - shift
        block = new_imports + ([""] + assigns if assigns else [])
        if block:
            lines[at:at] = block
        m.path.write_text("\n".join(lines))
        touched.add(m.path)

    print("touched", len(touched))
    paths = sorted(str(p) for p in touched) + [str(p) for p in sup.glob("*.py")]
    Path("/tmp/fold_touched.txt").write_text("\n".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
