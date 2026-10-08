"""No file under the green roots invokes a command the eleven-command surface removed.

The rewrite table lives in scripts/maint/rewrite_cli_names.py; this guard runs its
check in process, plus the table's own tests.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "rewrite_cli_names", ROOT / "scripts" / "maint" / "rewrite_cli_names.py"
)
assert _SPEC is not None and _SPEC.loader is not None
rcn = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rcn)

# Roots proven free of removed names; a doc set joins this tuple when its sweep lands.
ROOTS: tuple[str, ...] = (
    "src/docket",
    "scripts",
    "tests/unit",
    "tests/integration",
    "tests/guards",
    "examples",
    "benchmarks",
)
# Files inside ROOTS whose owners have not swept them yet.
PENDING: tuple[str, ...] = ("src/docket/templates",)


class TestRoots:
    def test_no_removed_name_survives_under_the_roots(self) -> None:
        start = time.monotonic()
        hits = rcn.check(ROOTS, PENDING)
        assert hits == [], "removed command names still invoked:\n" + "\n".join(hits)
        assert time.monotonic() - start < 2.0

    def test_every_replacement_is_a_live_command(self) -> None:
        assert rcn.self_check() == []

    def test_the_check_sees_a_planted_removed_name(self, tmp_path: Path) -> None:
        planted = tmp_path / "x.py"
        planted.write_text("# run `docket delegate` to queue\n", encoding="utf-8")
        assert len(rcn.check([planted])) == 1


class TestTable:
    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("docket pod myapp dispatch", "docket run"),
            ('docket pod "$POD" dispatch --resume', "docket run --resume"),
            ("docket pod {pod} dispatch", "docket run"),
            ('docket pod <p> delegate "x"', 'docket task add "x"'),
            ("docket pod <p> queue", "docket task list"),
            ("docket pod <project> config set budgetUsd 20", "docket pod set budgetUsd 20"),
            ("docket pod <project> config unset pipeline", "docket pod unset pipeline"),
            ("docket pod <p> apply recipe", "docket pod apply recipe"),
            ("docket pod <p> remove x-reviewer", "docket pod remove x-reviewer"),
            (
                'docket pod <p> set-verify x-impl "make test"',
                'docket pod set verify "make test" --member x-impl',
            ),
            ("docket add reviewer", "docket pod add reviewer"),
            ("docket delete myapp", "docket pod delete --pod myapp"),
            ("docket approve apr-1", "docket task approve apr-1"),
            ("docket chat x-lead", "docket task answer x-lead"),
            ("docket gates status", "docket setup sandbox status"),
            ("docket models provider add x", "docket setup provider add x"),
            ("docket models set", "docket setup model set"),
            ("docket keys add TOKEN", "docket setup provider add TOKEN --credential"),
            ("docket wire x-lead", "docket setup notify bind x-lead"),
            ("docket exporters list", "docket setup export list"),
            ("docket mcp servers list", "docket setup mcp list"),
            ("docket mcp serve", "docket start --mcp"),
            ("docket completions zsh", "docket setup shell zsh"),
            ("docket doctor --fix", "docket setup --fix"),
            ("docket serve --dispatch", "docket start --dispatch"),
            ("docket harness run --x", "docket exec --x"),
            ("docket audit verify", "docket log verify"),
            ("docket runs show r1", "docket task show r1"),
            ("docket trace tail myapp", "docket task trace --tail"),
            ("docket cost", "docket status"),
            ("docket snapshot", "docket status --all --json"),
            ("docket validate .docket", "docket pod validate .docket"),
            ("docket pipeline plan", "docket pod plan"),
            ("docket pipeline run f.yaml", "docket run --pipeline f.yaml"),
            ("docket policies test x", "docket pod check x"),
            ("docket roles list", "docket pod roles"),
            ("docket plugins list", "docket pod policies --plugins"),
            ("docket profile x-lead --resume", "docket run --resume"),
            ("docket profile x-lead --budget 5", "docket pod set budgetUsd 5"),
            ("docket maintain x-lead check", "docket setup --fix"),
        ],
    )
    def test_rewrites_one_invocation(self, old: str, new: str) -> None:
        assert rcn.rewrite_line(f"run `{old}` now\n") == f"run `{new}` now\n"

    def test_rewrite_is_idempotent(self) -> None:
        text = "\n".join(
            f"docket {x}"
            for x in (
                "pod myapp dispatch",
                "pod p config set a b",
                "pod p set-verify i 'c'",
                "delete myapp",
                "keys add K",
                "mcp serve",
                "runs show 1",
                "info x",
            )
        )
        once = rcn.rewrite_text(text)
        assert rcn.rewrite_text(once) == once

    def test_live_pod_verbs_are_not_taken_for_a_pod_name(self) -> None:
        for line in ("docket pod set budgetUsd 20", "docket pod apply x", "docket pod reset m"):
            assert rcn.rewrite_line(line) == line
            assert not rcn.survivors(line)

    def test_prose_about_what_docket_runs_is_not_an_invocation(self) -> None:
        assert not rcn.survivors("docket runs teams of coding agents")
        assert rcn.survivors("see `docket runs`")

    def test_allowed_substrings_are_not_flagged(self) -> None:
        assert not rcn.survivors('"title": "docket harness contract"')

    def test_unmappable_lines_are_reported_and_left_alone(self) -> None:
        for line in ("docket info x", "docket scope x set k", "docket pod p lead", "docket help"):
            assert rcn.rewrite_line(line) == line
            assert rcn.unmappable(line)
        assert not rcn.unmappable("docket cost")

    def test_every_removed_top_level_name_is_detected(self) -> None:
        for name in rcn.REMOVED_TOP_LEVEL:
            tail = " show" if name == "runs" else ""
            assert rcn.survivors(f"docket {name}{tail}"), name

    def test_the_self_check_rejects_a_replacement_that_is_not_live(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rcn, "TABLE", [*rcn.TABLE, (re.compile("x"), "docket nosuch verb")])
        assert any("nosuch" in p for p in rcn.self_check())


class TestRecord:
    def test_a_spec_changelog_is_neither_checked_nor_rewritten(self, tmp_path: Path) -> None:
        spec = rcn.ROOT / "specs" / "functional" / "_rcn_probe.spec.md"
        text = "# X\n\nUse `docket task add`.\n\n## Changelog\n\n- Added `docket delegate`.\n"
        spec.write_text(text, encoding="utf-8")
        try:
            assert rcn.check([spec]) == []
            assert list(rcn.diffs([spec])) == []
        finally:
            spec.unlink()
