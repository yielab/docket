"""The suite summary and the paired comparison read synthetic `trials.jsonl` lines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from evals.evaluator.compare import ComparisonError, compare_runs, render, resolve_run
from evals.evaluator.report import read_trials, summarize, write_report
from evals.evaluator.run import app
from evals.tests.lines import trial


def write_run(directory: Path, lines: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line) + "\n" for line in lines)
    (directory / "trials.jsonl").write_text(text, encoding="utf-8")
    return directory


def epochs(task: str, passes: int, total: int = 3, **extra: Any) -> list[dict[str, Any]]:
    return [trial(task, i < passes, "model", epoch=i, **extra) for i in range(total)]


def tasks(passes: dict[str, int]) -> list[dict[str, Any]]:
    return [line for task, count in passes.items() for line in epochs(task, count)]


def test_a_task_whose_version_changed_is_left_out_of_the_pairing_and_listed(tmp_path: Path) -> None:
    base = write_run(tmp_path / "base", tasks({"a@1": 3, "b@1": 3, "c@1": 0}))
    head = write_run(tmp_path / "head", tasks({"a@1": 3, "b@2": 0, "c@1": 3}))
    result = compare_runs(head, base)
    assert result.paired.matched == ["a@1", "c@1"]
    assert result.version_changed == [("b", "1", "2")]
    text = render(result)
    assert "b: version 1 -> 2" in text
    assert "b@1" not in result.paired.matched


def test_an_interval_that_crosses_zero_is_not_detectable(tmp_path: Path) -> None:
    base = write_run(tmp_path / "base", tasks({"a@1": 3, "b@1": 0, "c@1": 3, "d@1": 0}))
    head = write_run(tmp_path / "head", tasks({"a@1": 0, "b@1": 3, "c@1": 3, "d@1": 0}))
    text = render(compare_runs(head, base))
    assert "no detectable difference" in text
    assert "better" not in text and "worse" not in text


def test_a_small_suite_difference_under_20_points_is_not_detectable(tmp_path: Path) -> None:
    names = [f"t{i}@1" for i in range(12)]
    base = write_run(tmp_path / "base", tasks(dict.fromkeys(names, 2)))
    head_passes = dict.fromkeys(names, 2)
    head_passes.update({f"t{i}@1": 3 for i in range(6)})  # +16.7 points, interval above 0
    head = write_run(tmp_path / "head", tasks(head_passes))
    text = render(compare_runs(head, base))
    assert "not detectable" in text
    assert "under 20 points" in text


def test_a_large_consistent_gain_is_reported_as_a_difference(tmp_path: Path) -> None:
    names = [f"t{i}@1" for i in range(40)]
    base = write_run(tmp_path / "base", tasks(dict.fromkeys(names, 0)))
    head = write_run(
        tmp_path / "head", tasks({n: (3 if i % 4 else 2) for i, n in enumerate(names)})
    )
    result = compare_runs(head, base)
    assert result.paired.ci[0] > 0
    assert "no detectable difference" not in render(result)


def test_an_infra_trial_is_left_out_of_the_comparison(tmp_path: Path) -> None:
    lines = [*epochs("a@1", 3), trial("a@1", False, "infra", epoch=3)]
    base = write_run(tmp_path / "base", lines)
    head = write_run(tmp_path / "head", epochs("a@1", 3))
    assert compare_runs(head, base).paired.mean == 0.0


def test_a_base_sha_resolves_to_its_saved_run(tmp_path: Path) -> None:
    saved = write_run(tmp_path / "evals-v2" / "abc1234", tasks({"a@1": 3}))
    assert resolve_run("abc1234", tmp_path / "evals-v2") == saved
    assert resolve_run(str(saved), tmp_path / "evals-v2") == saved
    with pytest.raises(ComparisonError, match="deadbee"):
        resolve_run("deadbee", tmp_path / "evals-v2")


def test_the_summary_opens_with_the_verdict_line(tmp_path: Path) -> None:
    lines = tasks({"a@1": 3, "b@1": 1})
    lines[0]["graders"] = {
        "governance.no_violation": {"status": "fail", "reason": "x", "required": True}
    }
    lines.append(
        trial("b@1", True, tokens={"lead": {"input": 100, "output": 20}}, epoch=3, wall_s=2.0)
    )
    lines.append(trial("b@1", False, "infra", epoch=4))
    summary = summarize(lines, base="abc1234")
    assert summary["suite"] == "regression"
    assert summary["tasks"] == 2
    assert summary["violations"] == 1
    assert summary["failure_counts"] == {"infra": 1, "model": 2}
    assert summary["tokens_per_passed_task"]["lead"]["p50"] == 120
    out = write_report(tmp_path / "out", lines, base="abc1234")
    md = out["md"].read_text(encoding="utf-8").splitlines()
    assert md[0].startswith("regression | m | 2 tasks x ")
    assert "abc1234" in md[0] and "pass@1" in md[0]
    assert json.loads(out["json"].read_text(encoding="utf-8"))["suite"] == "regression"


def test_read_trials_skips_blank_lines(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", tasks({"a@1": 1}))
    with (run / "trials.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert len(read_trials(run)) == 3


def test_the_compare_subcommand_prints_the_paired_table(tmp_path: Path) -> None:
    base = write_run(tmp_path / "base", tasks({"a@1": 3, "b@1": 0}))
    head = write_run(tmp_path / "head", tasks({"a@1": 3, "b@2": 3}))
    done = CliRunner().invoke(app, ["compare", "--base", str(base), "--head", str(head)])
    assert done.exit_code == 0, done.output
    assert "a@1" in done.output
    assert "b: version 1 -> 2" in done.output
    missing = CliRunner().invoke(
        app, ["compare", "--base", str(tmp_path / "nope"), "--head", str(head)]
    )
    assert missing.exit_code == 1
