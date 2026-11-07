"""SUBJECT: evals/evaluator/online.py -- the production figures of a home, windowed, with Wilson
intervals, read through the CLI and the queue file, never a live model."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from docket.tasks.domain.task import HopResult
from evals.evaluator.run import app
from evals.tests.homes import finished, hop, make_home, success_series

runner = CliRunner()


def report(home: Path, *flags: str) -> str:
    result = runner.invoke(app, ["online-report", "--home", str(home), *flags])
    assert result.exit_code == 0, result.output
    return result.output


def line(text: str, figure: str, **parts: str) -> str:
    for row in text.splitlines():
        if row.startswith(figure) and all(f"{k}={v}" in row for k, v in parts.items()):
            return row
    raise AssertionError(f"no {figure} line with {parts} in:\n{text}")


def test_a_drop_from_eight_in_ten_to_four_in_ten_is_marked(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"alpha": success_series(wins_recent=16, wins_prior=32)})

    out = report(home, "--trend")

    row = line(out, "success", pod="alpha", role="implementer")
    assert "16/40" in row and "32/40" in row
    assert "worse" in row
    assert "not detectable" not in row


def test_a_drop_inside_the_intervals_is_not_marked(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"alpha": success_series(wins_recent=28, wins_prior=32)})

    row = line(report(home, "--trend"), "success", pod="alpha")

    assert "not detectable" in row
    assert "worse" not in row and "better" not in row


def test_a_rise_between_disjoint_intervals_is_marked_better(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"alpha": success_series(wins_recent=36, wins_prior=16)})

    assert "better" in line(report(home, "--trend"), "success", pod="alpha")


def test_too_few_samples_in_a_window_is_not_detectable(tmp_path: Path) -> None:
    tasks = [finished(1, done=False) for _ in range(3)] + [
        finished(12 + i * 0.2) for i in range(40)
    ]
    home = make_home(tmp_path, {"alpha": tasks})

    row = line(report(home, "--trend"), "success", pod="alpha")

    assert "not detectable" in row
    assert "worse" not in row


def test_a_rate_always_carries_its_n_and_its_wilson_interval(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"alpha": success_series(wins_recent=16, wins_prior=32)})

    row = line(report(home), "success", pod="alpha")

    assert "16/40" in row and "n=40" in row and "Wilson 95%" in row
    assert "0.40" in row
    assert "32/40" not in row, "the plain report is the last 7 days only"


def test_figures_are_split_by_pod_role_model_and_prompt_hash(tmp_path: Path) -> None:
    tasks = [
        *(finished(1 + i * 0.1, hops=[hop(model="anthropic/model-a")]) for i in range(6)),
        *(
            finished(1 + i * 0.1, hops=[hop(model="anthropic/model-b", identity="c" * 64)])
            for i in range(6)
        ),
    ]
    home = make_home(tmp_path, {"alpha": tasks, "beta": [finished(1)]})

    out = report(home)

    assert "model=anthropic/model-a" in line(out, "success", pod="alpha", model="anthropic/model-a")
    assert "prompt=aaaaaaaa" in line(out, "success", pod="alpha", model="anthropic/model-a")
    assert "prompt=cccccccc" in line(out, "success", pod="alpha", model="anthropic/model-b")
    assert "n=6" in line(out, "success", pod="alpha", model="anthropic/model-b")
    assert "pod=beta" in line(out, "success", pod="beta")


def test_reviewer_rejection_is_counted_per_verdict_hop(tmp_path: Path) -> None:
    def reviewed(verdict: str) -> list[HopResult]:
        return [hop("implementer"), hop("reviewer", verdict=verdict)]

    tasks = [finished(1, hops=reviewed("approve")) for _ in range(3)]
    tasks += [finished(2, done=False, hops=reviewed("rework")) for _ in range(2)]
    home = make_home(tmp_path, {"alpha": tasks})

    row = line(report(home), "reviewer_rejection", pod="alpha", role="reviewer")

    assert "2/5" in row


def test_a_task_that_went_back_for_rework_counts_in_the_rework_share(tmp_path: Path) -> None:
    tasks = [finished(1, hops=[hop(cycle=1)]), finished(1), finished(1)]
    home = make_home(tmp_path, {"alpha": tasks})

    assert "1/3" in line(report(home), "rework", pod="alpha")


def test_tasks_older_than_the_windows_and_unfinished_tasks_are_left_out(tmp_path: Path) -> None:
    from tests.support.tasks import task

    tasks = [finished(40), task(status="running", hops=[hop()]), finished(2)]
    home = make_home(tmp_path, {"alpha": tasks})

    out = report(home, "--trend")

    assert "1/1" in line(out, "success", pod="alpha")
    assert "prior 28d 0/0" in line(out, "success", pod="alpha")


def test_the_report_names_no_price_and_states_the_rule(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"alpha": success_series(wins_recent=16, wins_prior=32)})

    out = report(home, "--trend")

    assert "$" not in out
    assert "do not overlap" in out


def test_an_empty_home_says_so_and_exits_zero(tmp_path: Path) -> None:
    home = make_home(tmp_path, {})

    assert "no terminal tasks" in report(home, "--trend")


def test_a_missing_home_fails_with_one_line(tmp_path: Path) -> None:
    result = runner.invoke(app, ["online-report", "--home", str(tmp_path / "nope")])

    assert result.exit_code == 1
    assert result.output.startswith("FAIL")
