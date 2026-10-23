"""Guard: the kernel-adoption codemod rewrites the shapes it names and refuses the rest.

``scripts/maint/adopt_kernel.py`` edits source in bulk and has no other check than a human
reading its diff. Each test feeds a small module through one rule and the frame that merges
the rule's edits, then asserts the rewritten text or the refusal.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

SUBJECT = "docket.kernel"

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "adopt_kernel.py"
REL = "src/docket/core/sample.py"
ERRORS_IMPORT = "from docket.kernel.errors import InvalidInput\n"


def _load_codemod() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_adopt_kernel_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CODEMOD = _load_codemod()


def _plan(
    rule: str, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str = REL
) -> Any:
    """The frame's plan for *source* under one rule, as if it lived at *rel* in the repo."""
    monkeypatch.setattr(_CODEMOD, "REPO_ROOT", tmp_path)
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    tree = ast.parse(source)
    outcome = _CODEMOD.RULES[rule][0](tree, source, rel)
    plan = _CODEMOD.plan_outcomes(path, source, tree, [(rule, outcome)])
    assert plan is not None
    return plan


def test_every_rule_is_registered() -> None:
    wanted = {"ids", "text", "clock", "errors"}
    assert wanted <= set(_CODEMOD.RULES)


def test_ids_prefixed_uuid_becomes_new_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = 'import uuid\n\n\ndef f():\n    return f"task-{uuid.uuid4()}"\n'
    plan = _plan("ids", source, tmp_path, monkeypatch)
    assert 'return _ids.new_id("task")' in plan.after
    assert "from docket.kernel import ids as _ids\n" in plan.after


def test_ids_import_already_bound_is_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "import uuid\nfrom docket.kernel import ids as _ids\n\n\n"
        "def f():\n    return str(uuid.uuid4())\n"
    )
    plan = _plan("ids", source, tmp_path, monkeypatch)
    assert "return _ids.new_uuid()" in plan.after
    assert plan.after.count("from docket.kernel import ids as _ids") == 1


def test_clock_utc_isoformat_becomes_iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = "from datetime import UTC, datetime\n\nSTAMP = datetime.now(UTC).isoformat()\n"
    plan = _plan("clock", source, tmp_path, monkeypatch)
    assert "STAMP = _clock.iso()" in plan.after
    assert "from docket.kernel import clock as _clock\n" in plan.after


def test_clock_local_now_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = "from datetime import datetime\n\nNOW = datetime.now()\n"
    plan = _plan("clock", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert "local time" in plan.unmappable[0][1]


def test_text_one_line_collapse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = 'import os\n\n\ndef f(t):\n    return " ".join(t.split())\n'
    plan = _plan("text", source, tmp_path, monkeypatch)
    assert "return _text.one_line(t)" in plan.after
    assert "from docket.kernel import text as _text\n" in plan.after


def test_text_ellipsis_cut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = 'import os\n\n\ndef f(t):\n    return t if len(t) <= 20 else t[:19] + "…"\n'
    plan = _plan("text", source, tmp_path, monkeypatch)
    assert "return _text.ellipsize(t, 20)" in plan.after


def test_value_error_raise_becomes_invalid_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        'import os\n\n\ndef f(x):\n    if x:\n        raise ValueError("bad")\n'
        '    raise ValueError(f"also {x}")\n'
    )
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert 'raise InvalidInput("bad")' in plan.after
    assert 'raise InvalidInput(f"also {x}")' in plan.after
    assert plan.after.count(ERRORS_IMPORT) == 1
    assert not plan.unmappable


def test_raise_keeps_its_from_clause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = "import os\n\n\ndef f(exc):\n    raise ValueError( 'bad' )  from exc\n"
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert "raise InvalidInput( 'bad' )  from exc" in plan.after


@pytest.mark.parametrize(
    ("raising", "why"),
    [
        ("raise ValueError", "bare"),
        ("raise ValueError()", "without a message"),
        ("raise ValueError('a', 'b')", "other than one positional"),
        ("raise ValueError('a', hint='b')", "other than one positional"),
        ("raise ValueError(*parts)", "other than one positional"),
        ("raise RuntimeError('boom')", "no kind replaces"),
    ],
)
def test_unmappable_raise_is_left_alone(
    raising: str, why: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f"import os\n\n\ndef f(parts):\n    {raising}\n"
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert [reason for _, reason in plan.unmappable if why in reason]


def test_class_in_the_table_is_reparented(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_CODEMOD.CLASS_KINDS, "PodError", "InvalidInput")
    source = 'import os\n\n\nclass PodError(ValueError):\n    """A pod is wrong."""\n'
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert "class PodError(InvalidInput):" in plan.after
    assert ERRORS_IMPORT in plan.after


@pytest.mark.parametrize(
    ("definition", "why"),
    [
        ("class PodError(ValueError): ...", "CLASS_KINDS"),
        ("class Listed(ValueError, Mixin): ...", "more than one base"),
        ("class Listed(ValueError, metaclass=Meta): ...", "more than one base"),
        ("class Listed(ValueError):\n    def __init__(self): ...", "__init__"),
        ("class Listed(ValueError):\n    def __str__(self): ...", "__str__"),
    ],
)
def test_class_that_cannot_be_reparented_is_left_alone(
    definition: str, why: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(_CODEMOD.CLASS_KINDS, "Listed", "InvalidInput")
    source = f"import os\n\n\n{definition}\n"
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert [reason for _, reason in plan.unmappable if why in reason]


def test_errors_import_already_present_is_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f'{ERRORS_IMPORT}\n\ndef f():\n    raise ValueError("bad")\n'
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert 'raise InvalidInput("bad")' in plan.after
    assert plan.after.count(ERRORS_IMPORT) == 1


def test_module_binding_the_kind_to_something_else_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = 'import os\n\nInvalidInput = dict\n\n\ndef f():\n    raise ValueError("bad")\n'
    plan = _plan("errors", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert plan.skipped
