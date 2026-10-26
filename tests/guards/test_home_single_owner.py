"""Guard: Home.from_environ (kernel/home.py) is the only reader of an owned environment variable.

A setting read independently (its own ``os.environ.get``/default) at a second site means a
changed default requires finding every copy by hand -- easy to miss one and ship two commands
that silently disagree.

AST-based guard: walks every module under ``src/docket/`` other than ``kernel/home.py`` and
fails if any calls ``os.environ.get``/``os.getenv`` with an env var name this file promises to
own. AST-based rather than a text grep, since a substring search would also match the name
inside an unrelated string (a docstring, an error message).
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent
_HOME_FILE = _SRC_ROOT / "kernel" / "home.py"

# The env var names Home.from_environ is the single reader of, each a field of Home
# (METRICS_WINDOW, RUNAWAY_TURNS_THRESHOLD, RUNAWAY_COST_THRESHOLD, DOCKET_KEY_MAX_AGE_DAYS,
# DOCKET_KEYRING_SERVICE, DOCKET_SANDBOX_IMAGE, DOCKET_TOOL_MAX_OUTPUT_CHARS). DOCKET_NO_TRACE,
# DOCKET_NO_EXPORT and DOCKET_SECRETS_BACKEND are read live (a test toggles them with
# monkeypatch.setenv) by one function each in edges/adapters/system.py, not by Home.
_OWNED_ENV_VARS: frozenset[str] = frozenset(
    {
        "METRICS_WINDOW",
        "RUNAWAY_TURNS_THRESHOLD",
        "RUNAWAY_COST_THRESHOLD",
        "DOCKET_KEY_MAX_AGE_DAYS",
        "DOCKET_KEYRING_SERVICE",
        "DOCKET_SANDBOX_IMAGE",
        "DOCKET_TOOL_MAX_OUTPUT_CHARS",
    }
)


def _python_files_except_home() -> list[Path]:
    return sorted(p for p in _SRC_ROOT.rglob("*.py") if p != _HOME_FILE)


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


def test_no_module_outside_home_reads_an_owned_variable() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files_except_home():
        found = _owned_env_var_reads(path)
        if found:
            offenders[str(path.relative_to(_SRC_ROOT))] = found
    assert not offenders, (
        "these owned environment variables are read by os.environ.get/os.getenv "
        f"outside kernel/home.py -- read them from current_home() instead: {offenders}"
    )


def test_the_owned_set_matches_what_home_py_actually_reads() -> None:
    """The guard is only as good as its list -- pin it against home.py's own source so a
    renamed variable cannot silently stop being covered."""
    tree = ast.parse(_HOME_FILE.read_text())
    named = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing = _OWNED_ENV_VARS - named
    assert not missing, f"home.py no longer reads {sorted(missing)} -- update the guard's list"
