"""Guard: config.py is the ONLY declaration site for an owned config constant.

A constant independently redeclared (its own ``os.environ.get``/default)
at a second site means a changed default requires finding every copy by
hand -- easy to miss one and ship two commands that silently disagree.

AST-based guard: walks every module under ``src/docket/`` other than
``config.py`` and fails if any calls ``os.environ.get``/``os.getenv``
with an env var name this file promises to own. AST-based rather than a
text grep, since a substring search would also match the name inside an
unrelated string (a docstring, an error message).
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent
_CONFIG_FILE = _SRC_ROOT / "config.py"

# The env var names config.py is the single declaration site for. Each is
# read either as a plain module-level constant (METRICS_WINDOW,
# RUNAWAY_TURNS_THRESHOLD, RUNAWAY_COST_THRESHOLD, DOCKET_KEY_MAX_AGE_DAYS,
# DOCKET_KEYRING_SERVICE, DOCKET_SANDBOX_IMAGE) or, where call-time re-reads
# matter (a test toggles it with monkeypatch.setenv after config.py's first
# import -- see no_trace()/secrets_backend_requested()'s docstrings), through
# a config.py function that still owns the one os.environ.get call
# (DOCKET_NO_TRACE, DOCKET_SECRETS_BACKEND).
_OWNED_ENV_VARS: frozenset[str] = frozenset(
    {
        "METRICS_WINDOW",
        "RUNAWAY_TURNS_THRESHOLD",
        "RUNAWAY_COST_THRESHOLD",
        "DOCKET_KEY_MAX_AGE_DAYS",
        "DOCKET_SECRETS_BACKEND",
        "DOCKET_KEYRING_SERVICE",
        "DOCKET_NO_TRACE",
        "DOCKET_SANDBOX_IMAGE",
        "DOCKET_TOOL_MAX_OUTPUT_CHARS",
    }
)


def _python_files_except_config() -> list[Path]:
    return sorted(p for p in _SRC_ROOT.rglob("*.py") if p != _CONFIG_FILE)


def _is_env_read_call(node: ast.AST) -> bool:
    """True for ``os.environ.get(...)`` or ``os.getenv(...)`` call nodes."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get":
        value = func.value
        return (
            isinstance(value, ast.Attribute)
            and value.attr == "environ"
            and isinstance(value.value, ast.Name)
            and value.value.id == "os"
        )
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        return isinstance(func.value, ast.Name) and func.value.id == "os"
    return False


def _owned_env_var_reads(path: Path) -> list[str]:
    """Names from ``_OWNED_ENV_VARS`` this file reads via a fresh env call."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not _is_env_read_call(node):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value in _OWNED_ENV_VARS
        ):
            offenders.append(first.value)
    return offenders


def test_no_module_outside_config_redeclares_an_owned_constant() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files_except_config():
        found = _owned_env_var_reads(path)
        if found:
            offenders[str(path.relative_to(_SRC_ROOT))] = found
    assert not offenders, (
        "these owned config constants have a second os.environ.get/os.getenv "
        f"declaration site outside config.py -- read them from docket.config "
        f"instead: {offenders}"
    )


def test_the_owned_set_matches_what_config_py_actually_declares() -> None:
    """The guard is only as good as its list -- pin it against config.py's
    own source so a renamed constant cannot silently stop being covered."""
    tree = ast.parse(_CONFIG_FILE.read_text())
    declared: set[str] = set()
    for node in ast.walk(tree):
        if not _is_env_read_call(node):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            declared.add(first.value)
    missing = _OWNED_ENV_VARS - declared
    assert not missing, f"config.py no longer declares {sorted(missing)} -- update the guard's list"
