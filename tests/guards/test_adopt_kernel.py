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
    assert {"ids", "text", "clock", "errors", "config-reads", "repointers"} <= set(_CODEMOD.RULES)


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


# config-reads ----------------------------------------------------------------------------------

CURRENT_HOME_IMPORT = "from docket.kernel.home import current_home\n"


def _quiet(rule: str, source: str, rel: str = REL) -> bool:
    """True when *rule* finds nothing to rewrite and nothing to refuse in *source*."""
    outcome = _CODEMOD.RULES[rule][0](ast.parse(source), source, rel)
    return not outcome.edits and not outcome.unmappable


@pytest.mark.parametrize(
    ("read", "rewritten"),
    [
        ("_cfg.TRACES_DIR / 'x'", "current_home().traces_dir / 'x'"),
        ("_cfg.DOCKET_HOME", "current_home().root"),
        ("_cfg.workspace_dir(agent)", "current_home().workspace_dir(agent)"),
        ("_cfg.user_recipes_dir()", "current_home().user_recipes_dir"),
        ("_cfg.TRACE_RETENTION_S", "current_home().trace_retention_s"),
    ],
)
def test_config_read_becomes_a_current_home_read(
    read: str, rewritten: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f"import docket.config as _cfg\n\n\ndef f(agent):\n    return {read}\n"
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert f"return {rewritten}\n" in plan.after
    assert plan.after.count(CURRENT_HOME_IMPORT) == 1
    assert not plan.unmappable


def test_config_read_through_a_from_import_of_the_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "from docket import config\n\n\ndef f():\n    return config.AUDIT_LOG\n"
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert "return current_home().audit_log" in plan.after


def test_config_read_in_a_nested_function_default_is_not_import_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "import docket.config as _cfg\n\n\ndef f():\n"
        "    def g(path=_cfg.TRACES_DIR):\n        return path\n"
        "    return lambda: _cfg.AUDIT_LOG\n"
    )
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert "def g(path=current_home().traces_dir)" in plan.after
    assert "lambda: current_home().audit_log" in plan.after
    assert not plan.unmappable


def test_config_read_inside_an_fstring_follows_the_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = 'import docket.config as _cfg\n\n\ndef f():\n    return f"in {_cfg.AUDIT_LOG}"\n'
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    if sys.version_info >= (3, 12):
        assert 'return f"in {current_home().audit_log}"' in plan.after
    else:
        assert plan.after == source
        assert [why for _, why in plan.unmappable if "f-string" in why]


def test_every_home_value_in_config_has_a_home_member() -> None:
    import docket.config as config

    packaged = {"PROVIDER_TEMPLATES_DIR", "EXPORTER_TEMPLATES_DIR", "CHANNEL_TEMPLATES_DIR"}
    names = [n for n in dir(config) if n.isupper() and n not in packaged]
    assert [n for n in names if _CODEMOD._home_member(n) is None] == []


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("X = _cfg.TRACES_DIR", "read at import time (module level)"),
        ("def f(p=_cfg.TRACES_DIR): ...", "read at import time (default argument value)"),
        ("class C:\n    limit = _cfg.TOOL_MAX_OUTPUT_CHARS", "read at import time (class body)"),
        ("@dec(_cfg.TRACES_DIR)\ndef f(): ...", "read at import time (decorator argument)"),
        ("def f():\n    return _cfg.mkdir_private", "no Home field"),
        ("def f():\n    return _cfg.PROVIDER_TEMPLATES_DIR", "no Home field"),
        ("def f():\n    _cfg.AUDIT_LOG = 1", "a write to the module's constant"),
        ("def f():\n    return _cfg.user_recipes_dir", "is a Home property"),
        ("def f(m):\n    m.setattr(_cfg, 'AUDIT_LOG', 1)", "patches config.AUDIT_LOG"),
        ("def f():\n    return vars(_cfg)", "handed on as a value"),
        ("def f():\n    return 'docket.config.AUDIT_LOG'", "named by a string"),
        ("def f(_cfg):\n    return _cfg.AUDIT_LOG", "also a variable, parameter or definition"),
    ],
)
def test_config_read_that_cannot_be_rewritten_is_listed(
    body: str, why: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f"import docket.config as _cfg\n\n\n{body}\n"
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert [reason for _, reason in plan.unmappable if why in reason]


def test_config_name_imported_directly_is_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "from docket.config import AUDIT_LOG\n\n\ndef f():\n    return AUDIT_LOG\n"
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert [why for _, why in plan.unmappable if "imported by name" in why]


def test_config_read_keeps_a_refusal_next_to_a_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "import docket.config as _cfg\n\nLIMIT = _cfg.SESSION_TIMEOUT\n\n\n"
        "def f():\n    return _cfg.SESSION_TIMEOUT\n"
    )
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert "LIMIT = _cfg.SESSION_TIMEOUT" in plan.after
    assert "return current_home().session_timeout" in plan.after
    assert len(plan.unmappable) == 1


def test_module_binding_current_home_to_something_else_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "import docket.config as _cfg\n\ncurrent_home = dict\n\n\n"
        "def f():\n    return _cfg.AUDIT_LOG\n"
    )
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert plan.after == source
    assert plan.skipped


def test_config_reads_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = "import docket.config as _cfg\n\n\ndef f():\n    return _cfg.AUDIT_LOG\n"
    plan = _plan("config-reads", source, tmp_path, monkeypatch)
    assert _quiet("config-reads", plan.after)


# repointers ------------------------------------------------------------------------------------

TEST_REL = "tests/integration/test_sample.py"
HOME_IMPORTS = "from docket.kernel.home import Home\nfrom docket.kernel.home import use_home\n"
HEAD = "import pytest\nfrom tests.conftest import repoint_docket_home\n\n\n"


def _repoint(source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return _plan("repointers", HEAD + source, tmp_path, monkeypatch, TEST_REL)


def test_repoint_in_a_test_wraps_the_rest_of_the_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "def test_a(monkeypatch, tmp_path):\n"
        "    before = 1\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'h')\n"
        "    # kept\n"
        "    run(\n        before,\n    )\n"
        "    assert True\n",
        tmp_path,
        monkeypatch,
    )
    assert (
        "    before = 1\n"
        "    with use_home(Home(tmp_path / 'h')):\n"
        "        # kept\n"
        "        run(\n            before,\n        )\n"
        "        assert True\n"
    ) in plan.after
    assert HOME_IMPORTS in plan.after
    assert not plan.unmappable


def test_repoint_in_a_test_method_of_a_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "class TestIt:\n"
        "    def test_a(self, monkeypatch, tmp_path):\n"
        "        repoint_docket_home(monkeypatch, tmp_path)\n"
        "        run()\n",
        tmp_path,
        monkeypatch,
    )
    assert "        with use_home(Home(tmp_path)):\n            run()\n" in plan.after


def test_two_repoints_in_one_test_nest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _repoint(
        "def test_a(monkeypatch, tmp_path):\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'a')\n"
        "    one()\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'b')\n"
        "    two()\n",
        tmp_path,
        monkeypatch,
    )
    assert (
        "    with use_home(Home(tmp_path / 'a')):\n"
        "        one()\n"
        "        with use_home(Home(tmp_path / 'b')):\n"
        "            two()\n"
    ) in plan.after
    assert not plan.unmappable


def test_repoint_in_a_monkeypatch_context_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "def helper(home):\n"
        "    with pytest.MonkeyPatch.context() as mp:\n"
        "        repoint_docket_home(mp, home)\n"
        "        save()\n",
        tmp_path,
        monkeypatch,
    )
    assert "        with use_home(Home(home)):\n            save()\n" in plan.after


def test_repoint_in_a_fixture_that_returns_yields_inside_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "@pytest.fixture\n"
        "def home(monkeypatch, tmp_path) -> str:\n"
        "    repoint_docket_home(monkeypatch, tmp_path)\n"
        "    value = make()\n"
        "    return value\n",
        tmp_path,
        monkeypatch,
    )
    assert "def home(monkeypatch, tmp_path) -> Iterator[str]:" in plan.after
    assert (
        "    with use_home(Home(tmp_path)):\n        value = make()\n        yield value\n"
    ) in plan.after
    assert "from collections.abc import Iterator\n" in plan.after


def test_repoint_in_a_fixture_that_ends_without_a_return_gets_a_closing_yield(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "@pytest.fixture(autouse=True)\n"
        "def _isolate(tmp_path, monkeypatch) -> None:\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'home')\n",
        tmp_path,
        monkeypatch,
    )
    assert "def _isolate(tmp_path, monkeypatch) -> Iterator[None]:" in plan.after
    assert "    with use_home(Home(tmp_path / 'home')):\n        yield\n" in plan.after


def test_repoint_in_a_generator_fixture_keeps_its_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(
        "@pytest.fixture\n"
        "def home(monkeypatch, tmp_path):\n"
        "    repoint_docket_home(monkeypatch, tmp_path)\n"
        "    yield 1\n"
        "    cleanup()\n",
        tmp_path,
        monkeypatch,
    )
    assert (
        "    with use_home(Home(tmp_path)):\n        yield 1\n        cleanup()\n"
    ) in plan.after
    assert "Iterator" not in plan.after


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (
            "def _seed(monkeypatch, tmp_path):\n    repoint_docket_home(monkeypatch, tmp_path)\n",
            "outlives the function",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n    if tmp_path:\n"
            "        repoint_docket_home(monkeypatch, tmp_path)\n        run()\n",
            "inside a If",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n    for p in tmp_path:\n"
            "        repoint_docket_home(monkeypatch, p)\n        run()\n",
            "inside a For",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n    repoint_docket_home(monkeypatch, tmp_path)\n",
            "nothing follows the repoint",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n"
            "    repoint_docket_home(monkeypatch, tmp_path)  # why\n    run()\n",
            "a comment inside the repoint statement",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n"
            "    repoint_docket_home(monkeypatch, tmp_path)\n"
            "    text = '''a\nb'''\n",
            "multi-line string literal",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n"
            "    repoint_docket_home(monkeypatch, tmp_path)\n"
            "    threading.Thread(target=run).start()\n",
            "starts threads",
        ),
        (
            "def test_a(mp, tmp_path):\n    repoint_docket_home(mp, tmp_path)\n    run()\n",
            "not the monkeypatch of its own scope",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n"
            "    repoint_docket_home(monkeypatch, tmp_path, extra=1)\n    run()\n",
            "arguments other than (monkeypatch, path)",
        ),
        (
            "def test_a(monkeypatch, tmp_path):\n"
            "    x = repoint_docket_home(monkeypatch, tmp_path)\n    run()\n",
            "used as a value",
        ),
        (
            "@pytest.fixture\ndef home(monkeypatch, tmp_path):\n"
            "    repoint_docket_home(monkeypatch, tmp_path)\n"
            "    if tmp_path:\n        return 1\n    return 2\n",
            "a return that is not its last statement",
        ),
    ],
)
def test_repoint_that_cannot_be_reproduced_is_left_alone(
    body: str, why: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repoint(body, tmp_path, monkeypatch)
    assert plan.after == HEAD + body
    assert [reason for _, reason in plan.unmappable if why in reason]


def test_repoint_rewrite_holds_the_home_for_the_scope_and_ends_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docket.kernel.home import current_home

    plan = _repoint(
        "def test_a(monkeypatch, tmp_path):\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'h')\n"
        "    return current_home().root\n"
        "\n\n"
        "@pytest.fixture\n"
        "def fx(monkeypatch, tmp_path) -> Path:\n"
        "    repoint_docket_home(monkeypatch, tmp_path / 'f')\n"
        "    return tmp_path\n",
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(pytest, "fixture", lambda fn: fn)
    scope: dict[str, Any] = {"repoint_docket_home": None, "current_home": current_home}
    exec(compile(plan.after, "sample", "exec"), scope)
    before = current_home().root
    assert scope["test_a"](None, tmp_path) == tmp_path / "h"
    fixture = scope["fx"](None, tmp_path)
    assert next(fixture) == tmp_path
    assert current_home().root == tmp_path / "f"
    with pytest.raises(StopIteration):
        next(fixture)
    assert current_home().root == before


def test_repointers_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _repoint(
        "def test_a(monkeypatch, tmp_path):\n"
        "    repoint_docket_home(monkeypatch, tmp_path)\n"
        "    run()\n",
        tmp_path,
        monkeypatch,
    )
    assert _quiet("repointers", plan.after, TEST_REL)


def test_the_two_rules_scan_the_trees_the_guard_counts() -> None:
    assert _CODEMOD.RULE_ROOTS["repointers"] == (_CODEMOD.TESTS_ROOT,)
    assert _CODEMOD.SRC_ROOT in _CODEMOD.RULE_ROOTS["config-reads"]
