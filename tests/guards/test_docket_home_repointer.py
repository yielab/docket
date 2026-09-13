"""Guard: one way to repoint DOCKET_HOME, not many private copies.

``tests/conftest.py::repoint_docket_home`` exists so a test that wants its
own ``DOCKET_HOME`` never hand-writes a second, private copy of
``_DOCKET_HOME_PATHS``. A hand-rolled helper that forgets even one of the
sixteen constants leaves a home split in two: the forgotten constants stay
aimed at the autouse ``_isolate_docket_home`` fixture's home, so the test
looks isolated and is not, and nothing fails. This has already reached the
developer's real ``~/.docket`` more than once.

**What this checks, precisely.** Not "does this module call
``repoint_docket_home`` anywhere" -- a module can call it correctly in one
test and still hand-roll a partial subset in another. This walks every
function (including nested ones) independently and requires that a
function containing a direct ``_cfg.DOCKET_HOME`` assignment also calls
``repoint_docket_home`` somewhere in its own body.

**What it does not catch.** If a private helper hand-rolls the raw setattr
calls and a *different* function merely calls that helper, this flags the
defining function, not every caller -- enough to fail the suite and name
the offending file, not proof that no caller relies on a partial subset
elsewhere.

**A second uncovered shape.** The condition keys on ``_cfg.DOCKET_HOME``
itself, so a function that repoints only *derived* constants (traces,
sessions, approvals) and never claims a home at all does not trip it.
Several functions do exactly that deliberately -- ``conftest.py`` blesses
a single deliberate override, and the autouse fixture still isolates
everything else they leave alone -- but several hand-rolled together
would be a private partial copy again, and telling the two apart needs a
threshold this guard does not implement. Do not read this guard's silence
as proof those functions are uniform.

**The allowlist is empty on purpose.** It exists for tests that set a
``DOCKET_HOME`` *environment variable* for a spawned child process and
must never be converted -- but every real instance of that pattern sets
``os.environ`` or a subprocess ``env=`` dict, never ``_cfg.DOCKET_HOME``
itself, since patching the already-imported ``_cfg`` module cannot reach
a separate process's fresh import of ``config.py``. None of those files
trips this guard's condition. Add an entry, with a reason and the spawn
site it protects, only if a future test genuinely needs both a raw
``_cfg.DOCKET_HOME`` patch and a reason not to call the shared helper.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
_THIS_FILE = Path(__file__).resolve()

# path (relative to the tests/ dir) -> reason. Empty on purpose -- see the
# module docstring's last section for why every real environment-variable
# child-process case in this repo never trips the check below at all.
ALLOWLIST: dict[str, str] = {}


def _is_cfg_docket_home_setattr(call: ast.Call) -> bool:
    """True for `<anything>.setattr(_cfg, "DOCKET_HOME", ...)`, any monkeypatch alias."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "setattr"):
        return False
    if len(call.args) < 2:
        return False
    mod_arg, attr_arg = call.args[0], call.args[1]
    if not (isinstance(mod_arg, ast.Name) and mod_arg.id == "_cfg"):
        return False
    return isinstance(attr_arg, ast.Constant) and attr_arg.value == "DOCKET_HOME"


def _is_repoint_call(node: ast.AST) -> bool:
    """True for a call to the shared `repoint_docket_home` helper, by any name binding."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "repoint_docket_home"
    if isinstance(func, ast.Attribute):
        return func.attr == "repoint_docket_home"
    return False


def _function_violations(tree: ast.AST) -> list[tuple[str, int]]:
    """Every (name, lineno) of a function that sets _cfg.DOCKET_HOME directly
    without also calling repoint_docket_home somewhere in its own body."""
    violations: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        sets_directly = any(
            isinstance(sub, ast.Call) and _is_cfg_docket_home_setattr(sub) for sub in ast.walk(node)
        )
        if not sets_directly:
            continue
        if any(_is_repoint_call(sub) for sub in ast.walk(node)):
            continue
        violations.append((node.name, node.lineno))
    return violations


def _test_module_files() -> list[Path]:
    files = []
    for path in TESTS_ROOT.rglob("*.py"):
        if path.name == "conftest.py" or path.resolve() == _THIS_FILE:
            continue
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return sorted(files)


class TestOneWayToRepointDocketHome:
    def test_no_function_hand_rolls_docket_home_outside_the_shared_helper(self) -> None:
        failures: list[str] = []
        for path in _test_module_files():
            rel = str(path.relative_to(TESTS_ROOT))
            if rel in ALLOWLIST:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for func_name, lineno in _function_violations(tree):
                failures.append(f"tests/{rel}:{lineno} in {func_name}()")
        assert not failures, (
            "these functions patch _cfg.DOCKET_HOME directly instead of calling "
            "tests.conftest.repoint_docket_home, and are not on this guard's "
            f"ALLOWLIST: {failures}"
        )

    def test_allowlist_entries_still_exist_and_still_need_the_exemption(self) -> None:
        """A shrink-only ratchet: an allowlist entry must name a real file, and
        that file must still actually trip the raw-setattr condition -- an
        entry nobody needs any more is a graveyard slot, not a decision."""
        for rel, reason in ALLOWLIST.items():
            assert reason.strip(), f"{rel} has no reason on the allowlist"
            path = TESTS_ROOT / rel
            assert path.is_file(), f"allowlisted path does not exist: {rel}"
            tree = ast.parse(path.read_text(), filename=str(path))
            assert _function_violations(tree), (
                f"{rel} is allowlisted but no longer sets _cfg.DOCKET_HOME "
                "directly -- remove the now-unneeded entry"
            )
