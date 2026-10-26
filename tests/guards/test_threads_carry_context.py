"""Guard: a thread docket starts runs in its spawner's context.

``current_home()`` and the test clock read a ``ContextVar``, which a bare ``threading.Thread``
does not inherit, so such a thread would serve the process default home instead of the one it
was started under. Outside ``kernel/threads.py`` no module may call ``threading.Thread`` or
``Timer``, build a ``ThreadingHTTPServer``, or call ``.submit`` without handing it a context's
``run``. No baseline: the count is 0.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

SUBJECT = "docket.kernel.threads"

_SRC = Path(docket.__file__).resolve().parent
_HELPER = _SRC / "kernel" / "threads.py"
_BARE = {"Thread", "Timer"}


def violations(source: str) -> list[str]:
    """What in *source* starts a thread, a server or a pool task outside the helper."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in _BARE:
                found.append(f"line {node.lineno}: {name}() starts a thread with an empty context")
            if isinstance(fn, ast.Attribute) and fn.attr == "submit":
                first = node.args[0] if node.args else None
                via_helper = isinstance(fn.value, ast.Name) and fn.value.id.endswith("threads")
                if not via_helper and not (
                    isinstance(first, ast.Attribute) and first.attr == "run"
                ):
                    found.append(f"line {node.lineno}: .submit() without a copied context's run")
        named = getattr(node, "attr", getattr(node, "id", ""))
        if isinstance(node, ast.Name | ast.Attribute) and named == "ThreadingHTTPServer":
            found.append(f"line {node.lineno}: ThreadingHTTPServer, not ContextHTTPServer")
        if isinstance(node, ast.ImportFrom) and any(
            a.name == "ThreadingHTTPServer" for a in node.names
        ):
            found.append(f"line {node.lineno}: imports ThreadingHTTPServer")
    return found


def test_the_guard_sees_each_planted_violation() -> None:
    assert violations("import threading\nthreading.Thread(target=f).start()")
    assert violations("from threading import Thread\nThread(target=f)")
    assert violations("import threading\nthreading.Timer(1, f)")
    assert violations("from http.server import ThreadingHTTPServer\nThreadingHTTPServer(a, h)")
    assert violations("import http.server as s\ns.ThreadingHTTPServer(a, h)")
    assert violations("pool.submit(fn, 1)")
    assert not violations(
        "_threads.submit(pool, fn)\npool.submit(ctx.run, fn, 1)\nthreading.Event()\nthreading.Lock()"
    )


def test_no_module_starts_a_thread_outside_the_kernel_helper() -> None:
    offenders = {
        str(p.relative_to(_SRC)): found
        for p in sorted(_SRC.rglob("*.py"))
        if p != _HELPER and (found := violations(p.read_text()))
    }
    assert not offenders, f"start threads through docket.kernel.threads: {offenders}"
