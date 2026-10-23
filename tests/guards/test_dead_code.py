"""Ratchet: dead and duplicated code under src/docket may only shrink.

``scripts/maint/measure_dead_code.py`` counts the definitions no file names (``dead``), those only
a test names (``test-only``) and the groups of identical function bodies (``duplicate``).
``dead_code_baseline.txt`` records the totals. A count above its baseline is new dead code; one
below it is a deletion that forgot to lower the baseline, which would leave room for it to come
back, so both fail.
"""

from __future__ import annotations

import functools
import importlib.util
import sys
import textwrap
import types
from pathlib import Path

import pytest

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "measure_dead_code.py"


def _load_measure_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_measure_dead_code_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MEASURE = _load_measure_module()
SEE = "see: python3 scripts/maint/measure_dead_code.py --list"


def test_the_baseline_names_every_count() -> None:
    assert set(_MEASURE.read_baseline()) == set(_MEASURE.KINDS)


@functools.cache
def _counts() -> dict[str, int]:
    counts: dict[str, int] = _MEASURE.scan().counts()
    return counts


@pytest.mark.parametrize("kind", list(_MEASURE.KINDS))
def test_count_equals_the_baseline(kind: str) -> None:
    count, baseline = _counts()[kind], _MEASURE.read_baseline()[kind]
    assert count <= baseline, f"{kind} grew to {count}, above baseline {baseline}; {SEE}"
    assert count >= baseline, (
        f"{kind} fell to {count}, below baseline {baseline}; record it with "
        "`python3 scripts/maint/measure_dead_code.py --write`"
    )


def _repo(tmp_path: Path, src: str, test: str = "", extra: dict[str, str] | None = None) -> Path:
    files = {"src/docket/mod.py": src, "tests/test_mod.py": test, **(extra or {})}
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return tmp_path


def _names(sites: list[tuple[str, int, str]]) -> set[str]:
    return {name for _, _, name in sites}


def test_a_name_nobody_mentions_is_dead(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def lonely():\n    return 1\n\nLIMIT = 3\n\nclass Gone: ...\n")
    assert _names(_MEASURE.scan(repo).dead) == {"lonely", "LIMIT", "Gone"}


def test_a_recursive_call_does_not_keep_a_function_alive(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def spin(n):\n    return spin(n - 1)\n")
    assert _names(_MEASURE.scan(repo).dead) == {"spin"}


def test_only_tests_naming_a_site_makes_it_test_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def helper():\n    return 1\n", "from docket.mod import helper\n")
    result = _MEASURE.scan(repo)
    assert _names(result.test_only) == {"helper"}
    assert not result.dead


@pytest.mark.parametrize(
    "caller",
    [
        "def use():\n    return mod.helper()\n",
        "def use():\n    return getattr(mod, 'helper')\n",
        "PATCH = 'docket.mod.helper'\n",
    ],
)
def test_a_src_or_script_mention_keeps_a_site_alive(tmp_path: Path, caller: str) -> None:
    repo = _repo(
        tmp_path,
        "def helper():\n    return 1\n",
        extra={"scripts/tool.py": "import docket.mod as mod\n" + caller},
    )
    result = _MEASURE.scan(repo)
    assert "helper" not in _names(result.dead + result.test_only)


def test_a_docstring_mention_does_not_keep_a_site_alive(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 'def helper():\n    return 1\n\ndef main():\n    """Calls helper."""\n')
    assert "helper" in _names(_MEASURE.scan(repo).dead)


def test_an_entry_point_in_pyproject_is_alive(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "def main():\n    return 0\n",
        extra={"pyproject.toml": '[project.scripts]\ndocket = "docket.mod:main"\n'},
    )
    assert not _MEASURE.scan(repo).dead


def test_exports_registrations_and_overrides_are_never_reported(tmp_path: Path) -> None:
    src = """
        import threading
        from http.server import BaseHTTPRequestHandler
        from typing import Protocol
        import typer
        from pydantic import BaseModel, field_validator

        __all__ = ["exported"]
        app = typer.Typer()

        def exported(): ...

        @app.command()
        def registered(): ...

        class Port(Protocol):
            def method(self) -> None: ...

        class Worker(threading.Thread):
            def run(self) -> None: ...

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): ...
            def do_HEAD(self): ...

        class Model(BaseModel):
            @field_validator("x")
            @classmethod
            def check(cls, v): return v
    """
    repo = _repo(tmp_path, src, extra={"scripts/use.py": "from docket.mod import app, Port\n"})
    assert _names(_MEASURE.scan(repo).dead) == {"Worker", "Handler", "Model"}


def test_an_in_repo_base_class_method_is_an_override(tmp_path: Path) -> None:
    src = """
        class Base:
            def hook(self): ...

        class Child(Base):
            def hook(self): ...
            def extra(self): ...
    """
    repo = _repo(tmp_path, src, extra={"scripts/use.py": "from docket.mod import Child, Base\n"})
    assert _names(_MEASURE.scan(repo).dead) == {"Base.hook", "Child.extra"}


BODY = """\
    def {name}({arg}):
        {local} = {arg} + 1
        for item in {local}:
            print(item)
        return {local}
"""


def _body(name: str, arg: str, local: str) -> str:
    return textwrap.dedent(BODY).format(name=name, arg=arg, local=local)


def test_identical_bodies_with_renamed_locals_form_one_group(tmp_path: Path) -> None:
    src = _body("one", "a", "b") + _body("two", "x", "y")
    groups = _MEASURE.scan(_repo(tmp_path, src)).duplicates
    assert [[name for _, _, name in group] for group in groups] == [["one", "two"]]


def test_different_bodies_and_short_bodies_are_not_duplicates(tmp_path: Path) -> None:
    other = _body("two", "x", "y").replace("+ 1", "+ 2")
    short = "def s1(a):\n    return a\n\ndef s2(b):\n    return b\n"
    src = _body("one", "a", "b") + other + short
    assert not _MEASURE.scan(_repo(tmp_path, src)).duplicates


def test_a_count_above_the_baseline_fails_and_one_below_asks_for_write(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def lonely():\n    return 1\n")
    counts = _MEASURE.scan(repo).counts()
    assert counts == {"dead": 1, "test-only": 0, "duplicate": 0}
    above = _MEASURE.regressions(counts, {"dead": 0, "test-only": 0, "duplicate": 0})
    assert above == ["dead grew to 1, above baseline 0"]
    below = _MEASURE.regressions(counts, {"dead": 2, "test-only": 0, "duplicate": 0})
    assert len(below) == 1 and "--write" in below[0]
    assert not _MEASURE.regressions(counts, counts)
