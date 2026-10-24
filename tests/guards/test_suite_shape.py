"""The shape of the test suite.

No helper or fixture is defined, with an identical body, in two test files: a shared helper has
one owner under ``tests/support/`` and a second file imports it. Beyond that: a unit file opens
no socket or process and does not sleep; ``SUBJECT`` names a module; a test file is at most 800
lines; ``setenv`` and ``in result.output`` on a ``--json`` command only shrink. The ratchets
read ``suite_shape_baseline.txt``; a line there that no longer offends must be deleted.
"""

from __future__ import annotations

import ast
import collections
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
_SKIPPED_DIRS = {"fixtures", "golden", "__pycache__"}


def _shape(fn: ast.FunctionDef) -> str:
    body = fn.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        fn = ast.FunctionDef(**{**dict(ast.iter_fields(fn)), "body": body[1:] or [ast.Pass()]})
    return ast.dump(fn)


def duplicated_helpers(root: Path) -> list[str]:
    """Return one line per helper or fixture that two or more files define identically."""
    seen: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        if _SKIPPED_DIRS & set(path.relative_to(root).parts):
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
                seen[(node.name, _shape(node))].append(str(path.relative_to(root)))
    return [
        f"{name} is defined identically in {', '.join(files)}"
        for (name, _), files in sorted(seen.items())
        if len(set(files)) > 1
    ]


def test_no_helper_or_fixture_is_defined_twice() -> None:
    found = duplicated_helpers(TESTS)
    assert found == [], "move each to tests/support/ and import it:\n" + "\n".join(found)


def test_the_check_sees_a_planted_copy(tmp_path: Path) -> None:
    helper = 'def _seed(tmp_path):\n    """doc"""\n    return tmp_path / "x"\n'
    (tmp_path / "test_a.py").write_text(helper, encoding="utf-8")
    (tmp_path / "test_b.py").write_text(helper.replace('"""doc"""', '"""other doc"""'))
    (tmp_path / "test_c.py").write_text("def _seed(tmp_path):\n    return 1\n", encoding="utf-8")

    found = duplicated_helpers(tmp_path)

    assert len(found) == 1
    assert "test_a.py" in found[0] and "test_b.py" in found[0] and "test_c.py" not in found[0]


def test_a_test_function_defined_twice_is_not_a_helper(tmp_path: Path) -> None:
    body = "def test_x():\n    assert True\n"
    (tmp_path / "test_a.py").write_text(body, encoding="utf-8")
    (tmp_path / "test_b.py").write_text(body, encoding="utf-8")

    assert duplicated_helpers(tmp_path) == []


# ── unit purity, SUBJECT, size, setenv, --json output ────────────────────────

SRC = ROOT / "src" / "docket"
MAX_TEST_FILE_LINES = 800
_BASELINE = Path(__file__).with_name("suite_shape_baseline.txt")
_NETWORK_AND_PROCESS_MODULES = {
    "socket",
    "socketserver",
    "http.server",
    "http.client",
    "subprocess",
    "multiprocessing",
    "selectors",
}
_SERVER_AND_PROCESS_CALLS = {
    "HTTPServer",
    "ThreadingHTTPServer",
    "ContextHTTPServer",
    "Popen",
    "create_connection",
    "serve_forever",
    "fork",
    "create_server",
    "start_server",
}
# The registry tests drive the CLI package's own __init__, and the fixture contract names a
# fixture module, so neither can name a module file of docket.
_STRUCTURAL_SUBJECTS = {
    "interfaces/cli/test_app.py",
    "interfaces/cli/test_registry.py",
    "test_runtime_adapter_fixture_contract.py",
}
# Tests of the module that reads the environment may set it.
_ENVIRONMENT_PARSERS = {"unit/kernel/test_home.py"}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _test_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("test_*.py") if not _SKIPPED_DIRS & set(p.relative_to(root).parts)
    )


def _is_banned_module(name: str) -> bool:
    return name in _NETWORK_AND_PROCESS_MODULES or name.split(".")[0] in {
        "socket",
        "socketserver",
        "subprocess",
        "multiprocessing",
    }


def _opens_io(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(_is_banned_module(a.name) for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and _is_banned_module(node.module):
            return True
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _SERVER_AND_PROCESS_CALLS:
                return True
            if (
                func.attr in {"system", "sleep"}
                and isinstance(func.value, ast.Name)
                and func.value.id in {"os", "time"}
            ):
                return True
        elif isinstance(func, ast.Name) and func.id in _SERVER_AND_PROCESS_CALLS | {"sleep"}:
            return True
    return False


def unit_files_with_io(unit_root: Path) -> list[str]:
    """Return the unit files that open a socket or a process, or sleep."""
    return [
        _rel(p, unit_root)
        for p in _test_files(unit_root)
        if _opens_io(ast.parse(p.read_text(encoding="utf-8")))
    ]


def subjects_naming_a_package(root: Path, src: Path) -> list[str]:
    """Return the test files whose SUBJECT is not a module file under ``src``."""
    out = []
    for path in _test_files(root):
        found = re.search(r'^SUBJECT = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        if found is None:
            continue
        parts = found.group(1).split(".")
        if parts[0] != "docket" or not src.joinpath(*parts[1:]).with_suffix(".py").is_file():
            out.append(f"{_rel(path, root)}: {found.group(1)}")
    return out


def files_over_the_line_limit(root: Path) -> list[str]:
    """Return the Python files under ``root`` longer than the limit."""
    out = []
    for path in sorted(root.rglob("*.py")):
        if _SKIPPED_DIRS & set(path.relative_to(root).parts):
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_TEST_FILE_LINES:
            out.append(f"{_rel(path, root)}: {lines} lines")
    return out


def setenv_counts(root: Path) -> dict[str, int]:
    """Return the number of ``.setenv(`` calls per test file."""
    counts: dict[str, int] = {}
    for path in _test_files(root):
        n = len(re.findall(r"\.setenv\(", path.read_text(encoding="utf-8")))
        if n:
            counts[_rel(path, root)] = n
    return counts


def _invoked_path(call: ast.Call, commands: set[tuple[str, ...]]) -> tuple[str, ...] | None:
    """Return the command path a ``runner.invoke(app, [...])`` call names, if it has --json."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "invoke"):
        return None
    if len(call.args) < 2 or not isinstance(call.args[1], ast.List):
        return None
    words: list[str] = []
    for el in call.args[1].elts:
        if (
            isinstance(el, ast.Constant)
            and isinstance(el.value, str)
            and not el.value.startswith("-")
        ):
            words.append(el.value)
        else:
            break
    for end in range(len(words), 0, -1):
        if tuple(words[:end]) in commands:
            return tuple(words[:end])
    return None


def json_output_counts(root: Path, commands: set[tuple[str, ...]]) -> dict[str, int]:
    """Count ``"x" in result.output`` asserts on a command that has ``--json``."""
    counts: dict[str, int] = {}
    for path in _test_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n = 0
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            results: set[str] = set()
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                    and _invoked_path(node.value, commands)
                ):
                    results.add(node.targets[0].id)
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Compare)
                    and any(isinstance(op, ast.In) for op in node.ops)
                    and isinstance(node.comparators[0], ast.Attribute)
                    and node.comparators[0].attr in {"output", "stdout"}
                    and isinstance(node.comparators[0].value, ast.Name)
                    and node.comparators[0].value.id in results
                ):
                    n += 1
        if n:
            counts[_rel(path, root)] = n
    return counts


def _json_commands() -> set[tuple[str, ...]]:
    from typer.main import get_command

    from docket.interfaces.cli.app import app

    found: set[tuple[str, ...]] = set()

    def walk(cmd: object, path: tuple[str, ...]) -> None:
        opts = {o for p in getattr(cmd, "params", []) for o in getattr(p, "opts", [])}
        if path and "--json" in opts:
            found.add(path)
        for name, sub in (getattr(cmd, "commands", None) or {}).items():
            walk(sub, (*path, name))

    walk(get_command(app), ())
    return found


def _read_baseline(path: Path) -> dict[str, dict[str, int]]:
    sections: dict[str, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, path, *count = line.split()
        sections.setdefault(kind, {})[path] = int(count[0]) if count else 1
    return sections


def _ratchet(kind: str, current: dict[str, int], path: Path = _BASELINE) -> list[str]:
    """Return what grew past the baseline and what the baseline still lists but no longer holds."""
    baseline = _read_baseline(path).get(kind, {})
    grew = [
        f"{p}: {n} (baseline {baseline.get(p, 0)})"
        for p, n in current.items()
        if n > baseline.get(p, 0)
    ]
    stale = [
        f"{p}: baseline {n}, now {current.get(p, 0)}"
        for p, n in baseline.items()
        if current.get(p, 0) < n
    ]
    return [*(f"grew {g}" for g in grew), *(f"lower the baseline {s}" for s in stale)]


def test_a_unit_file_opens_no_socket_or_process_and_does_not_sleep() -> None:
    found = _ratchet("unit_io", {f"unit/{p}": 1 for p in unit_files_with_io(TESTS / "unit")})
    assert found == [], "move the I/O to tests/integration or fake it:\n" + "\n".join(found)


def test_subject_names_a_module_never_a_package() -> None:
    found = [
        f
        for f in subjects_naming_a_package(TESTS / "unit", SRC)
        + subjects_naming_a_package(TESTS / "integration", SRC)
        if f.split(":")[0] not in _STRUCTURAL_SUBJECTS
    ]
    assert found == [], "name the module the file drives:\n" + "\n".join(found)


def test_a_test_file_is_at_most_800_lines() -> None:
    found = files_over_the_line_limit(TESTS)
    assert found == [], "split the file by flow:\n" + "\n".join(found)


def test_setenv_only_where_the_environment_is_parsed() -> None:
    counts = {
        f"{top}/{p}": n
        for top in ("unit", "integration")
        for p, n in setenv_counts(TESTS / top).items()
        if f"{top}/{p}" not in _ENVIRONMENT_PARSERS
    }
    found = _ratchet("setenv", counts)
    assert found == [], "use a Home value or a fake instead of setenv:\n" + "\n".join(found)


def test_json_commands_are_asserted_through_json_not_output_substrings() -> None:
    commands = _json_commands()
    counts = {
        f"{top}/{p}": n
        for top in ("unit", "integration")
        for p, n in json_output_counts(TESTS / top, commands).items()
    }
    found = _ratchet("json_output", counts)
    assert found == [], "parse the --json document instead:\n" + "\n".join(found)


# ── each check is seen to fail on a plant ────────────────────────────────────


def test_the_io_check_sees_a_planted_socket_process_and_sleep(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text("import socket\n", encoding="utf-8")
    (tmp_path / "test_b.py").write_text("import time\n\ndef f():\n    time.sleep(1)\n")
    (tmp_path / "test_c.py").write_text("from http.server import ThreadingHTTPServer\n")
    (tmp_path / "test_d.py").write_text("import subprocess\n", encoding="utf-8")
    (tmp_path / "test_e.py").write_text("import json\n\ndef f():\n    json.dumps(1)\n")

    assert unit_files_with_io(tmp_path) == ["test_a.py", "test_b.py", "test_c.py", "test_d.py"]


def test_the_subject_check_sees_a_planted_package(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (src / "mod.py").write_text("", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text('SUBJECT = "docket.mod"\n', encoding="utf-8")
    (tests / "test_pkg.py").write_text('SUBJECT = "docket.pkg"\n', encoding="utf-8")

    assert subjects_naming_a_package(tests, src) == ["test_pkg.py: docket.pkg"]


def test_the_size_check_sees_a_planted_long_file(tmp_path: Path) -> None:
    (tmp_path / "test_long.py").write_text("x = 1\n" * (MAX_TEST_FILE_LINES + 1), encoding="utf-8")
    (tmp_path / "test_short.py").write_text("x = 1\n" * MAX_TEST_FILE_LINES, encoding="utf-8")

    assert files_over_the_line_limit(tmp_path) == [f"test_long.py: {MAX_TEST_FILE_LINES + 1} lines"]


def test_the_setenv_check_counts_a_planted_call(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text("def t(monkeypatch):\n    monkeypatch.setenv('A', '1')\n")
    (tmp_path / "test_b.py").write_text("def t():\n    pass\n", encoding="utf-8")

    assert setenv_counts(tmp_path) == {"test_a.py": 1}


def test_the_json_check_sees_a_planted_output_substring(tmp_path: Path) -> None:
    body = (
        "def t(runner, app):\n"
        "    result = runner.invoke(app, ['task', 'list', '--json'])\n"
        "    assert 'x' in result.output\n"
        "    other = runner.invoke(app, ['task', 'cancel', 'x'])\n"
        "    assert 'y' in other.output\n"
    )
    (tmp_path / "test_a.py").write_text(body, encoding="utf-8")

    assert json_output_counts(tmp_path, {("task", "list")}) == {"test_a.py": 1}


def test_the_ratchet_reports_growth_and_a_stale_line(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("kind a.py 2\nkind gone.py 1\n", encoding="utf-8")

    found = _ratchet("kind", {"a.py": 3, "new.py": 1}, baseline)

    assert sorted(found) == [
        "grew a.py: 3 (baseline 2)",
        "grew new.py: 1 (baseline 0)",
        "lower the baseline gone.py: baseline 1, now 0",
    ]
