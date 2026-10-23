"""Guard: scripts/maint/refactor/hoist_imports.py hoists local docket imports and keeps real cycles.

Each test builds a toy ``docket`` package in a temporary directory and runs the tool on it, never
on this repository. The tool needs ``libcst`` and ``ruff``.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

pytest.importorskip("libcst")
if shutil.which("ruff") is None:
    pytest.skip("ruff is not on PATH", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "maint" / "refactor" / "hoist_imports.py"

PYPROJECT = """\
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = ["E501"]
[tool.ruff.lint.isort]
known-first-party = ["docket"]
"""


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_refactor_hoist_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hoist = _load()


def _write(root: Path, files: dict[str, str]) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for rel, text in files.items():
        path = root / "src" / "docket" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    init = root / "src" / "docket" / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def _run(root: Path, *extra: str) -> tuple[int, dict[str, dict[str, object]]]:
    ledger = root / "ledger.json"
    code = hoist.main(["--root", str(root), "--ledger", str(ledger), "--jobs", "2", *extra])
    data = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
    return code, data


def _read(root: Path, rel: str) -> str:
    return (root / "src" / "docket" / rel).read_text(encoding="utf-8")


def _kept(data: dict[str, dict[str, object]], module: str) -> list[dict[str, str]]:
    kept = data["modules"][module]["kept"]  # type: ignore[index]
    assert isinstance(kept, list)
    return kept


def _imports_cleanly(root: Path, module: str) -> bool:
    code = f"import sys; sys.path.insert(0, {str(root / 'src')!r}); import {module}"
    return subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


def test_a_plain_local_import_is_hoisted_merged_and_deduplicated(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "util.py": "def one() -> int:\n    return 1\n\n\ndef two() -> int:\n    return 2\n",
            "user.py": """
                from docket.util import one


                def f() -> int:
                    from docket.util import one, two

                    return one() + two()


                def g() -> int:
                    from docket.util import two

                    return two()
            """,
        },
    )
    code, data = _run(tmp_path)
    assert code == 0
    text = _read(tmp_path, "user.py")
    assert "    from docket" not in text
    assert text.count("from docket.util import") == 1
    assert "from docket.util import one, two\n" in text
    assert data["modules"]["docket.user"]["hoisted"] == 2  # type: ignore[index]
    assert _kept(data, "docket.user") == []
    assert _imports_cleanly(tmp_path, "docket.user")


def test_a_two_module_cycle_hoists_one_direction_and_still_imports(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "a.py": """
                def f() -> int:
                    from docket.b import g

                    return g()
            """,
            "b.py": """
                def g() -> int:
                    from docket.a import f

                    return 1 if f is None else 2
            """,
        },
    )
    code, data = _run(tmp_path)
    assert code == 0
    a, b = _read(tmp_path, "a.py"), _read(tmp_path, "b.py")
    assert ("from docket.b import g" in a.split("def f")[0]) != (
        "from docket.a import f" in b.split("def g")[0]
    )
    kept = _kept(data, "docket.a") + _kept(data, "docket.b")
    assert [k["reason"] for k in kept] == ["cycle"]
    assert _imports_cleanly(tmp_path, "docket.a")
    assert _imports_cleanly(tmp_path, "docket.b")


def test_a_name_that_clashes_with_a_module_level_name_stays_local(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "util.py": "def helper() -> str:\n    return 'util'\n",
            "user.py": """
                def helper() -> str:
                    return 'mine'


                def f() -> str:
                    from docket.util import helper

                    return helper()


                def g() -> str:
                    from docket.util import helper as other

                    return other()


                def h(x: int) -> int:
                    from docket.util import helper

                    helper = x
                    return helper
            """,
        },
    )
    code, data = _run(tmp_path)
    assert code == 0
    text = _read(tmp_path, "user.py")
    assert "    from docket.util import helper\n" in text
    assert "from docket.util import helper as other" in text.split("def f")[0]
    reasons = sorted(k["reason"] for k in _kept(data, "docket.user"))
    assert reasons == ["collision", "collision"]
    assert _imports_cleanly(tmp_path, "docket.user")


def test_an_existing_import_under_another_alias_does_not_stand_in_for_the_name(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        {
            "util.py": "def one() -> int:\n    return 1\n",
            "user.py": """
                from docket.util import one as _one


                def f() -> int:
                    from docket.util import one

                    return one() + _one()
            """,
        },
    )
    code, data = _run(tmp_path)
    assert code == 0
    assert "    from docket.util import one\n" not in _read(tmp_path, "user.py")
    assert _kept(data, "docket.user") == []
    assert _imports_cleanly(tmp_path, "docket.user")
    flakes = subprocess.run(
        ["ruff", "check", "--isolated", "--select", "F", str(tmp_path / "src/docket/user.py")],
        check=False,
        capture_output=True,
    )
    assert flakes.returncode == 0, flakes.stdout.decode()


def test_a_function_that_rebinds_the_name_keeps_the_import_local(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "util.py": "def one() -> int:\n    return 1\n",
            "user.py": """
                def f(flag: bool) -> int:
                    from docket.util import one

                    if flag:
                        one = lambda: 2  # noqa: E731
                    return one()
            """,
        },
    )
    code, data = _run(tmp_path)
    assert code == 0
    assert "    from docket.util import one\n" in _read(tmp_path, "user.py")
    assert [k["reason"] for k in _kept(data, "docket.user")] == ["collision"]


def test_type_checking_and_optional_imports_are_left_untouched(tmp_path: Path) -> None:
    source = """
        from __future__ import annotations

        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from docket.util import one


        def f() -> int:
            if TYPE_CHECKING:
                from docket.util import two
            try:
                from docket.util import three
            except ImportError:
                three = None
            return one() if three is None else 0
    """
    _write(
        tmp_path,
        {
            "util.py": "def one() -> int:\n    return 1\n\n\ndef two() -> int:\n    return 2\n"
            "\n\ndef three() -> int:\n    return 3\n",
            "user.py": source,
        },
    )
    before = _read(tmp_path, "user.py")
    code, data = _run(tmp_path)
    assert code == 0
    assert _read(tmp_path, "user.py") == before
    assert [k["reason"] for k in _kept(data, "docket.user")] == ["optional"]
    assert data["totals"]["found"] == 1  # type: ignore[index]


def test_a_second_run_changes_nothing_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "util.py": "def one() -> int:\n    return 1\n",
            "a.py": "def f() -> int:\n    from docket.b import g\n\n    return g()\n",
            "b.py": "def g() -> int:\n    from docket.a import f\n\n    return 1 if f else 2\n",
            "c.py": "def k() -> int:\n    from docket.util import one\n\n    return one()\n",
        },
    )
    files = ["util.py", "a.py", "b.py", "c.py"]
    pristine = {f: _read(tmp_path, f) for f in files}
    code, dry = _run(tmp_path, "--dry-run")
    assert code == 0
    assert {f: _read(tmp_path, f) for f in files} == pristine
    assert dry["totals"]["hoisted"] == 2  # type: ignore[index]

    assert _run(tmp_path)[0] == 0
    first = {f: _read(tmp_path, f) for f in files}
    assert first != pristine
    code, again = _run(tmp_path)
    assert code == 0
    assert {f: _read(tmp_path, f) for f in files} == first
    assert again["totals"]["hoisted"] == 0  # type: ignore[index]
    assert again["totals"]["cycle"] == 1  # type: ignore[index]


def test_templates_are_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "templates/skel.py": "def f() -> None:\n    from docket.nothing import x\n",
            "ok.py": "X = 1\n",
        },
    )
    before = _read(tmp_path, "templates/skel.py")
    code, data = _run(tmp_path)
    assert code == 0
    assert data["totals"]["found"] == 0  # type: ignore[index]
    assert _read(tmp_path, "templates/skel.py") == before
