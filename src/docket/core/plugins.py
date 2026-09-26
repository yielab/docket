"""Loader and evaluator for operator-scoped predicate plugins (see ``docket.plugins`` for the
public API a plugin file imports). Discovery is restricted to ``PLUGINS_DIR`` (global) and a
pod's own ``config/plugins/`` -- never a codebase -- because a policy runs inside the gate on
every tool call the agent itself makes, and a plugin loaded from the codebase would let an
agent rewrite its own gate for the next turn.

``discover`` imports each ``*.py`` with ``importlib.util.spec_from_file_location``, draining
``docket.plugins.REGISTRY`` after each file; a cache keyed by ``(mtime_ns, size)`` skips
re-importing an unchanged file. ``evaluate`` runs one predicate under a wall-clock budget and
never raises; every call is audited as ``policy.plugin``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docket.config as _cfg
import docket.plugins as _api
from docket.core.audit import audit_log

DEFAULT_BUDGET_MS = 250


class PluginError(ValueError):
    """A plugin file failed to import, or two files registered the same predicate name."""


@dataclass(frozen=True)
class LoadedPredicate:
    """One registered predicate: its name, scope (``"global"`` or ``"pod:<p>"``), source file,
    that file's sha256, and the callable itself."""

    name: str
    scope: str
    file: Path
    sha256: str
    fn: Callable[..., bool]


# Keyed by file path; value is ((mtime_ns, size), {name: LoadedPredicate}) for that file alone.
_CACHE: dict[Path, tuple[tuple[int, int], dict[str, LoadedPredicate]]] = {}


def _file_key(path: Path) -> tuple[int, int]:
    st = path.stat()
    return (st.st_mtime_ns, st.st_size)


def _load_file(path: Path, scope: str) -> dict[str, LoadedPredicate]:
    """Import *path* fresh; return every predicate it registers, keyed by name."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(f"docket_plugin_{digest[:12]}", path)
    if spec is None or spec.loader is None:
        raise PluginError(f"{path}: cannot load as a Python module")
    module = importlib.util.module_from_spec(spec)
    before = len(_api.REGISTRY)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del _api.REGISTRY[before:]
        raise PluginError(f"{path}: failed to import: {exc}") from exc
    registered = _api.REGISTRY[before:]
    del _api.REGISTRY[before:]
    return {
        name: LoadedPredicate(name=name, scope=scope, file=path, sha256=digest, fn=fn)
        for name, fn in registered
    }


def _scoped_dirs(project: str) -> list[tuple[Path, str]]:
    dirs = [(_cfg.PLUGINS_DIR, "global")]
    if project:
        dirs.append((_cfg.pod_config_dir(project) / "plugins", f"pod:{project}"))
    return dirs


def discover(project: str = "") -> dict[str, LoadedPredicate]:
    """Every predicate applied in scope -- global, then *project*'s pod when given -- never a
    codebase. Raises ``PluginError`` on a duplicate name across files or a file that fails to
    import."""
    found: dict[str, LoadedPredicate] = {}
    for directory, scope in _scoped_dirs(project):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            key = _file_key(path)
            cached = _CACHE.get(path)
            loaded = (
                cached[1] if cached is not None and cached[0] == key else _load_file(path, scope)
            )
            _CACHE[path] = (key, loaded)
            for name, pred in loaded.items():
                if name in found:
                    raise PluginError(
                        f"predicate '{name}' is registered twice: {found[name].file} and "
                        f"{pred.file}"
                    )
                found[name] = pred
    return found


def evaluate(
    pred: LoadedPredicate,
    call: _api.ToolCall,
    ctx: _api.PolicyContext,
    with_: dict[str, Any],
    *,
    budget_ms: int = DEFAULT_BUDGET_MS,
) -> tuple[bool, str]:
    """Run *pred* and return ``(verdict, reason)``; never raises. A raise, a non-bool return, or
    exceeding *budget_ms* (measured wall clock around the call) all deny with a *reason*; a
    normal ``bool`` return carries ``reason=""``. Always audits one ``policy.plugin`` entry."""
    start = time.perf_counter()
    try:
        result = pred.fn(call, ctx, **with_)
    except Exception as exc:
        verdict, reason = False, f"raised {type(exc).__name__}: {exc}"
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > budget_ms:
            verdict, reason = False, f"exceeded {budget_ms} ms"
        elif not isinstance(result, bool):
            verdict, reason = False, f"returned {type(result).__name__}"
        else:
            verdict, reason = result, ""
    audit_log(
        "policy.plugin",
        f"name={pred.name} scope={pred.scope} sha256={pred.sha256} "
        f"verdict={'allow' if verdict else 'deny'} reason={reason!r}",
    )
    return verdict, reason
