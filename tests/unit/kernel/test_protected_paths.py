"""Which paths a change may not touch alone: the defaults, a team's globs, files a check names."""

from __future__ import annotations

import pytest

from docket.kernel import protected_paths as _pp

SUBJECT = "docket.kernel.protected_paths"


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "web/package.json",
        "uv.lock",
        "pyproject.toml",
        "Cargo.toml",
        ".eslintrc.json",
        "eslint.config.mjs",
        "tsconfig.build.json",
        "vitest.config.ts",
        "jest.config.js",
        "ruff.toml",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        "mypy.ini",
        ".docket/pod.yaml",
        ".docket/teams/web/pod.yaml",
        ".github/workflows/ci.yml",
    ],
)
def test_the_defaults_protect_manifests_check_configuration_and_ci(path: str) -> None:
    assert _pp.matches(path, _pp.DEFAULT_PATTERNS)


@pytest.mark.parametrize(
    "path", ["src/app.js", "README.md", "docs/package.json.md", "github/workflows/ci.yml"]
)
def test_ordinary_files_are_not_protected(path: str) -> None:
    assert not _pp.matches(path, _pp.DEFAULT_PATTERNS)


def test_a_pattern_with_a_slash_matches_the_whole_path_and_one_without_the_name() -> None:
    assert _pp.matches("src/api/schema.sql", ["src/*/schema.sql"])
    assert not _pp.matches("lib/schema.sql", ["src/*/schema.sql"])
    assert _pp.matches("a/b/Makefile", ["Makefile"])


@pytest.mark.parametrize("bad", ["", "  ", "/abs", "a/../b", "a,b", "a\nb", "a\x00b", "x" * 201])
def test_check_pattern_refuses_unsafe_globs(bad: str) -> None:
    with pytest.raises(ValueError):
        _pp.check_pattern(bad)


def test_check_pattern_keeps_the_stripped_glob() -> None:
    assert _pp.check_pattern("  src/*.js ") == "src/*.js"


def test_command_files_finds_tracked_files_a_command_names() -> None:
    tracked = {"scripts/check.sh", "lint.cfg", "src/app.js"}
    found = _pp.command_files(
        ["bash ./scripts/check.sh && eslint --config=lint.cfg src", "echo 'scripts/other.sh'"],
        tracked,
    )
    assert found == {"scripts/check.sh", "lint.cfg"}


def test_command_files_names_nothing_for_a_directory_or_an_unknown_file() -> None:
    assert _pp.command_files(["pytest tests/", "make check"], {"tests/a.py", "Makefile"}) == set()


def test_command_files_survives_an_unbalanced_quote() -> None:
    assert _pp.command_files(["bash 'scripts/check.sh"], {"scripts/check.sh"}) == set()


def test_protected_among_unites_patterns_and_named_files_sorted() -> None:
    got = _pp.protected_among(
        ["src/z.js", "package.json", "scripts/check.sh", "src/app.js"],
        [*_pp.DEFAULT_PATTERNS, "src/z.*"],
        {"scripts/check.sh"},
    )
    assert got == ["package.json", "scripts/check.sh", "src/z.js"]


def test_changed_protected_sees_a_file_inside_a_new_untracked_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A protected file in a directory git has never seen is found by its own path."""
    listed = {False: ["config/"], True: ["config/tsconfig.json"]}
    monkeypatch.setattr(_pp._git, "git_diff_names", lambda *_a: [])
    monkeypatch.setattr(
        _pp._git, "git_changed_files", lambda _cwd, *, all_untracked=False: listed[all_untracked]
    )
    monkeypatch.setattr(_pp._git, "git_tracked_files", lambda _cwd: [])
    assert _pp.changed_protected("/wt", "base", "branch", (), ()) == ["config/tsconfig.json"]
