"""Prove scripts/metrics.py's --check gate actually catches drift.

scripts/metrics.py replaces the Bash-era scripts/metrics.sh, which counted
`lib/commands/*.sh` — deleted at the M6 Bash→Python cutover — so its counts
silently resolved to (near) zero and the README drift guard went blind. This
suite exercises the rewritten checker against synthetic README fixtures (never
the real README.md) so the test's pass/fail is not coupled to whether CH-0's
manual number fix has landed in this tree.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "metrics.py"


def _load_metrics_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_ch9_metrics_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses (used by scripts/metrics.py) resolves annotations via
    # sys.modules[cls.__module__] — register before exec_module or it 404s.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


METRICS = _load_metrics_module()


def _synthetic_readme(
    tests: int,
    loc: int,
    specs: int,
    *,
    tests_comment: int | None = None,
    commands: int = 30,
) -> str:
    """Render a minimal README fragment using the exact phrasing check_readme parses."""
    comment_tests = tests if tests_comment is None else tests_comment
    return (
        f"- **{tests} tests** in the pytest suite (`tests/python/`)\n"
        f"- **~{loc:,} lines** of Python in the shipped `docket` package\n"
        f"- **{specs} specifications** (RFC 2119), validated in CI\n"
        f"- **{commands} commands**, each documented in docs/commands.md\n"
        f"uv run pytest                                        # {comment_tests}-test Python suite\n"
    )


class TestCheckReadmeUnit:
    """Direct unit coverage of check_readme() against synthetic metrics."""

    def test_passes_when_all_numbers_match(self, tmp_path: Path) -> None:
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(_synthetic_readme(700, 12000, 15))

        assert METRICS.check_readme(readme, metrics) == []

    def test_tolerates_rounded_loc_within_the_nearest_hundred(self, tmp_path: Path) -> None:
        # README says "~12,000"; tree has 12,043 — still round-trips to the
        # same hundred, so this is not drift.
        metrics = {"tests": 700, "loc": 12043, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(_synthetic_readme(700, 12000, 15))

        assert METRICS.check_readme(readme, metrics) == []

    def test_fails_on_planted_test_count_drift(self, tmp_path: Path) -> None:
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        # Deliberately wrong test count planted in the bullet only.
        readme.write_text(_synthetic_readme(999, 12000, 15, tests_comment=700))

        problems = METRICS.check_readme(readme, metrics)

        assert problems
        assert any("999" in p and "700" in p for p in problems)

    def test_fails_on_planted_spec_count_drift(self, tmp_path: Path) -> None:
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(_synthetic_readme(700, 12000, 999))

        problems = METRICS.check_readme(readme, metrics)

        assert any("specifications" in p for p in problems)

    def test_fails_on_planted_loc_drift_outside_rounding_tolerance(self, tmp_path: Path) -> None:
        metrics = {"tests": 700, "loc": 20000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(_synthetic_readme(700, 12000, 15))

        problems = METRICS.check_readme(readme, metrics)

        assert any("lines of Python" in p for p in problems)

    def test_fails_on_planted_command_count_drift(self, tmp_path: Path) -> None:
        # The command count is computed by compute() but went unguarded until the
        # README stated it -- a metric nothing quotes is a metric nothing checks.
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(_synthetic_readme(700, 12000, 15, commands=99))

        problems = METRICS.check_readme(readme, metrics)

        assert any("commands" in p for p in problems)

    def test_one_reworded_claim_is_skipped_not_failed(self, tmp_path: Path) -> None:
        # Rewording *a* claim out of the prose is a docs concern, not drift —
        # the remaining claims still gate. This is the original, correct half of
        # the skip rule.
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        full = _synthetic_readme(700, 12000, 15)
        without_specs = "\n".join(
            line for line in full.splitlines() if "specifications" not in line
        )
        readme.write_text(without_specs + "\n")

        assert METRICS.check_readme(readme, metrics) == []

    def test_readme_stating_no_claims_at_all_is_a_hard_failure(self, tmp_path: Path) -> None:
        """A guard that verified nothing must not report success.

        Regression test for the fail-open hole: `check_readme` used to skip every
        unmatched claim silently, so a README stating none of them returned "in
        sync" while checking zero numbers. Combined with the comma bug below,
        the real gate went fully vacuous.
        """
        metrics = {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text("Just some unrelated prose with no quoted numbers.\n")

        problems = METRICS.check_readme(readme, metrics)

        assert problems, "a README with zero recognizable claims must not pass"
        assert any("UNGUARDED" in p for p in problems)

    def test_thousands_separator_in_a_claim_is_still_checked(self, tmp_path: Path) -> None:
        """Regression: `**1,188 tests**` must be parsed, not silently skipped.

        The claim patterns used `(\\d+)`, which cannot match a comma-formatted
        number, so the tests guard silently disarmed itself the moment the suite
        crossed 1,000 cases — while still printing "in sync".
        """
        metrics = {"tests": 1188, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text(
            "- **1,188 tests** in the pytest suite (`tests/python/`)\n"
            "- **~12,000 lines** of Python in the shipped `docket` package\n"
            "- **15 specifications** (RFC 2119), validated in CI\n"
        )

        assert METRICS.check_readme(readme, metrics) == []

    def test_thousands_separator_drift_is_caught(self, tmp_path: Path) -> None:
        metrics = {"tests": 1188, "loc": 12000, "commands": 30, "specs": 15}
        readme = tmp_path / "README.md"
        readme.write_text("- **1,042 tests** in the pytest suite (`tests/python/`)\n")

        problems = METRICS.check_readme(readme, metrics)

        assert any("1042" in p and "1188" in p for p in problems)

    def test_spec_count_matches_the_blocking_validator(self) -> None:
        """`count_specs()` must agree with `scripts/validate-specs.sh`.

        These two scripts are both authorities on "how many specifications does
        this repo have", and they disagreed by one for as long as
        `specs/acceptance/user-stories.md` has existed: the validator globs
        `specs/acceptance/*.md`, while `count_specs()` used
        `rglob("*.spec.md")` and could not see a file without that suffix.
        README followed the metrics script and published 20 where the
        CI-blocking gate counted 21.

        Pinning them against each other is the only thing that keeps a future
        category directory — or a future spec that does not use the `.spec.md`
        suffix — from re-opening the same one-off silently.
        """
        validator = SCRIPT_PATH.parent / "validate-specs.sh"
        out = subprocess.run(
            ["bash", str(validator)],
            capture_output=True,
            text=True,
            cwd=SCRIPT_PATH.parent.parent,
            check=False,
        ).stdout
        match = re.search(r"Total Specifications:\s*(\d+)", out)
        assert match, f"could not read a spec total out of the validator:\n{out}"

        assert METRICS.count_specs() == int(match.group(1))

    def test_count_specs_includes_a_non_spec_md_suffixed_specification(self) -> None:
        """The acceptance spec is the concrete file the old suffix filter missed."""
        counted = {p.name for p in (SCRIPT_PATH.parent.parent / "specs").glob("*/*.md")}

        assert "user-stories.md" in counted
        assert "README.md" not in counted, "the specs index is not itself a specification"

    def test_claims_found_reports_live_and_disarmed_guards(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("- **700 tests** in the pytest suite (`tests/python/`)\n")

        stated, missing = METRICS.claims_found(readme)

        assert "tests (by-the-numbers bullet)" in stated
        assert "specifications" in missing
        assert "lines of Python" in missing


class TestMainCheckExitCodes:
    """main(["--check", ...]) end-to-end, with compute() mocked to keep it fast."""

    def test_exit_0_on_synthetic_tree_in_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            METRICS, "compute", lambda: {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        )
        good = tmp_path / "GOOD.md"
        good.write_text(_synthetic_readme(700, 12000, 15))

        rc = METRICS.main(["--check", "--readme", str(good)])

        assert rc == 0
        assert "in sync" in capsys.readouterr().out

    def test_exit_1_on_synthetic_planted_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            METRICS, "compute", lambda: {"tests": 700, "loc": 12000, "commands": 30, "specs": 15}
        )
        bad = tmp_path / "BAD.md"
        # Deliberately wrong number, planted only for this test.
        bad.write_text(_synthetic_readme(700, 12000, 4242))

        rc = METRICS.main(["--check", "--readme", str(bad)])

        assert rc == 1
        assert "DRIFT" in capsys.readouterr().out


def test_cli_subprocess_check_catches_planted_drift_against_live_counts(tmp_path: Path) -> None:
    """Full CLI invocation (subprocess, not import) against real live counts.

    Builds a synthetic README from the tree's actual current metrics (so this
    doesn't depend on whether CH-0's README fix has landed), verifies --check
    passes on it, then plants drift in a copy and verifies it fails — proving
    the gate CI runs (`uv run python scripts/metrics.py --check`) is real.
    """
    json_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert json_result.returncode == 0, json_result.stderr
    live = json.loads(json_result.stdout)

    good = tmp_path / "GOOD.md"
    good.write_text(
        _synthetic_readme(live["tests"], live["loc"], live["specs"], commands=live["commands"])
    )
    good_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check", "--readme", str(good)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert good_result.returncode == 0, good_result.stdout + good_result.stderr

    bad = tmp_path / "BAD.md"
    bad.write_text(
        _synthetic_readme(live["tests"] + 1, live["loc"], live["specs"], commands=live["commands"])
    )
    bad_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check", "--readme", str(bad)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert bad_result.returncode == 1
    assert "DRIFT" in bad_result.stdout
