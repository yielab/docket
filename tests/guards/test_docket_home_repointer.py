"""Guard: one way to repoint DOCKET_HOME, not fifty-six.

``tests/conftest.py::repoint_docket_home`` exists precisely so a test that
wants its own ``DOCKET_HOME`` never hand-writes a second, private copy of
``_DOCKET_HOME_PATHS``. Before this guard, 21 test modules had done exactly
that anyway, each with its own ``_point_at``-shaped helper -- and not one of
them covered all sixteen constants in the canonical tuple. Every one of
those tests ran against a home split in two: the constants its private
helper forgot stayed aimed at the autouse ``_isolate_docket_home`` fixture's
home, so the test looked isolated and was not, and nothing failed. This is
the same isolation failure that has already reached the developer's real
``~/.docket`` three times, one guard-shaped step earlier.

**What this guard actually checks, precisely.** A weaker version of this
guard would ask only "does this module call ``repoint_docket_home`` anywhere
in it" -- that is not what this does, and it matters: a module can call the
helper correctly in one test and still hand-roll a partial subset in
another, and a module-wide check would not catch that. This guard instead
walks every function (including nested ones -- a fixture defined inside a
test class, a helper called by several tests) and requires that a function
which itself contains a direct ``_cfg.DOCKET_HOME`` assignment also contains
a call to ``repoint_docket_home`` somewhere in its own body. Each function is
judged independently, so one correct test next to one drifted test in the
same file is still caught.

**What it does not catch, named rather than assumed away.** If a private
helper function -- call it ``_point_at`` -- hand-rolls the raw setattr calls
in its own body, and a *different* function merely calls ``_point_at(...)``,
this guard flags the defining function (where the raw assignment lives), not
every caller. That is sufficient to fail the suite and name the offending
file, which is the guard's job; it does not additionally prove that no
caller of a legitimate helper was silently relying on a partial subset
elsewhere. A reviewer reading a failure here should open the named function.

**The allowlist below is for a different shape of test, and it is currently
empty on purpose.** The card that wrote this guard asked for a class of test
that sets a ``DOCKET_HOME`` *environment variable* for a child process it
then spawns, and must never be converted. That class exists in this repo
(``tests/integration/test_run_cancellation.py``, four ``tests/agent/release/``
adapter-boundary tests, and one site inside
``test_cooperative_run_cancellation.py`` sitting next to an already-converted
in-process repoint) -- but every real instance of it sets ``os.environ`` or a
plain ``dict`` passed as a subprocess ``env=``, never ``_cfg.DOCKET_HOME``
itself, because patching the already-imported ``_cfg`` module has no way to
reach a separate process's fresh import of ``config.py``. None of those
files therefore ever trips this guard's condition, and the allowlist has
nothing legitimate to hold. It stays as a mechanism, not a graveyard: add an
entry, with a reason and the spawn site it protects, only if a future test
genuinely needs both a raw ``_cfg.DOCKET_HOME`` patch and a reason not to
call the shared helper.
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
