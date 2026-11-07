"""Which paths a change may not touch alone: the defaults, a team's globs, files a check names."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from tests.support.fakes import FakeGit

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
    fake_git: FakeGit,
) -> None:
    """A protected file in a directory git has never seen is found by its own path."""
    listed = {False: ["config/"], True: ["config/tsconfig.json"]}
    fake_git.git_diff_names = lambda *_a: []
    fake_git.git_changed_files = lambda _cwd, *, all_untracked=False: listed[all_untracked]
    fake_git.git_tracked_files = lambda _cwd: []
    assert _pp.changed_protected("/wt", "base", "branch", (), ()) == ["config/tsconfig.json"]


def _folder(root: Path) -> Path:
    """A folder with a protected file, a file a check names, and an ordinary one."""
    (root / "checks").mkdir(parents=True)
    (root / "checks" / "verify.sh").write_text("exit 0\n")
    (root / "package.json").write_text("{}\n")
    (root / "report.md").write_text("draft\n")
    return root


def test_hash_protected_digests_defaults_patterns_and_command_named_files(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    (root / "notes.cfg").write_text("x\n")

    got = _pp.hash_protected(root, ["*.cfg"], ["sh checks/verify.sh"])

    assert sorted(got) == ["checks/verify.sh", "notes.cfg", "package.json"]
    assert got["package.json"] == hashlib.sha256(b"{}\n").hexdigest()


def test_hash_protected_skips_vcs_and_dependency_directories_and_symlinks(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    for skipped in (".git", "node_modules"):
        (root / skipped).mkdir()
        (root / skipped / "package.json").write_text("{}\n")
    (root / "link.json").symlink_to(root / "package.json")

    assert sorted(_pp.hash_protected(root, ["*.json"], ())) == ["package.json"]


def test_hash_protected_of_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert _pp.hash_protected(tmp_path / "absent", (), ["sh a.sh"]) == {}


def test_changed_hashes_lists_an_edited_added_and_removed_protected_file_sorted(
    tmp_path: Path,
) -> None:
    root = _folder(tmp_path)
    (root / "ruff.toml").write_text("a\n")
    before = _pp.hash_protected(root, (), ["sh checks/verify.sh"])

    (root / "checks" / "verify.sh").write_text("exit 0 # edited\n")
    (root / "ruff.toml").unlink()
    (root / "tox.ini").write_text("new\n")
    (root / "report.md").write_text("final\n")

    assert _pp.changed_hashes(root, before, (), ["sh checks/verify.sh"]) == [
        "checks/verify.sh",
        "ruff.toml",
        "tox.ini",
    ]


def test_changed_hashes_is_empty_when_only_an_ordinary_file_changed(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    before = _pp.hash_protected(root, (), ["sh checks/verify.sh"])

    (root / "report.md").write_text("final\n")

    assert _pp.changed_hashes(root, before, (), ["sh checks/verify.sh"]) == []


def test_changed_hashes_does_not_protect_a_named_file_the_task_created(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    before = _pp.hash_protected(root, (), ["cat brief.md"])

    (root / "brief.md").write_text("the deliverable\n")

    assert before == {"package.json": hashlib.sha256(b"{}\n").hexdigest()}
    assert _pp.changed_hashes(root, before, (), ["cat brief.md"]) == []


class TestPrivateControlNames:
    def test_the_list_names_docket_state_once(self) -> None:
        assert _pp.PRIVATE_CONTROL_NAMES == (
            "HEARTBEAT.md",
            "AGENTS.md",
            "TOOLS.md",
            "MEMORY.md",
            ".docket",
        )

    @pytest.mark.parametrize(
        ("parts", "expected"),
        [
            (("MEMORY.md",), "MEMORY.md"),
            ((".docket", "pod.yaml"), ".docket"),
            (("a", ".docket"), ".docket"),
            (("docs", "AGENTS.md"), None),
            (("src", "memory.py"), None),
            (("AGENTS.md.bak",), None),
        ],
    )
    def test_files_count_at_the_root_and_the_directory_anywhere(
        self, tmp_path: Path, parts: tuple[str, ...], expected: str | None
    ) -> None:
        assert _pp.private_control_name(tmp_path, parts) == expected

    def test_a_repository_checkout_keeps_its_own_instruction_files(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: elsewhere\n")

        assert _pp.private_control_name(tmp_path, ("AGENTS.md",)) is None
        assert _pp.private_control_name(tmp_path, (".docket",)) == ".docket"
