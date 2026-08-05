"""Guard: config.py is the ONLY declaration site for an owned config constant.

CLAUDE.md claims ``config.py`` holds "every path/constant" -- that was false
in two ways before this card: ``METRICS_WINDOW`` was independently declared
(with its own ``os.environ.get`` call and default literal) in both
``config.py`` and ``cli/_metrics.py`` -- and ``config.py``'s copy had no
reader, a knob advertised but dead. ``RUNAWAY_TURNS_THRESHOLD``,
``RUNAWAY_COST_THRESHOLD`` and ``DOCKET_KEY_MAX_AGE_DAYS`` never reached
``config.py`` at all: each was read straight from the environment, with its
default literal repeated, at up to three separate use sites across
``cli/_doctor.py`` and ``cli/_cost.py``. Changing a default correctly meant
finding every copy by hand -- easy to miss one and ship two commands that
silently disagree.

This is an AST-based guard (sibling of ``test_no_print_in_core_edges.py``'s
no-``print()`` check): it walks every module under ``src/docket/`` other
than ``config.py`` itself and fails if any of them calls
``os.environ.get``/``os.getenv`` with one of the env var names this file
promises to own. AST-based rather than a text grep because a naive substring
search on the env var name would also match it inside an unrelated string
(a docstring, an error message) that is not a second declaration site.
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
    own source so a future rename of one of these constants cannot silently
    stop being covered without a test noticing (same reasoning as
    ``test_docket_home_isolation.py``'s equivalent check)."""
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
