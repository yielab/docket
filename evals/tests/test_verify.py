"""SUBJECT: evals/harness/verify.py -- the hidden checks run on a copy the agent cannot steer."""

from __future__ import annotations

from pathlib import Path

from evals.harness.verify import RESULT_NAME, run_hidden

_CHECK = "from pathlib import Path\n\ndef test_answer():\n    assert Path('answer.txt').read_text() == '42\\n'\n"


def _task(tmp_path: Path, answer: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "answer.txt").write_text(answer)
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_answer.py").write_text(_CHECK)
    return repo, hidden


def test_a_correct_repository_passes(tmp_path: Path) -> None:
    repo, hidden = _task(tmp_path, "42\n")
    assert run_hidden(repo, hidden, tmp_path / "verify").status == "pass"


def test_a_wrong_repository_fails(tmp_path: Path) -> None:
    repo, hidden = _task(tmp_path, "41\n")
    assert run_hidden(repo, hidden, tmp_path / "verify").status == "fail"


def test_a_planted_conftest_cannot_turn_a_failure_into_a_pass(tmp_path: Path) -> None:
    repo, hidden = _task(tmp_path, "41\n")
    (repo / "conftest.py").write_text(
        "import pytest\n\n@pytest.hookimpl(hookwrapper=True)\n"
        "def pytest_runtest_makereport(item, call):\n"
        "    outcome = yield\n    outcome.get_result().outcome = 'passed'\n"
    )
    (repo / "pytest.ini").write_text("[pytest]\naddopts = --co\n")
    assert run_hidden(repo, hidden, tmp_path / "verify").status == "fail"


def test_an_earlier_result_is_deleted_and_no_tests_is_an_error(tmp_path: Path) -> None:
    repo, hidden = _task(tmp_path, "42\n")
    (hidden / "test_answer.py").unlink()
    root = tmp_path / "verify"
    root.mkdir()
    (root / RESULT_NAME).write_text("pass 0\n")
    result = run_hidden(repo, hidden, root)
    assert result.status == "error"
    assert (root / RESULT_NAME).read_text() == "error 5\n"


def test_a_missing_hidden_directory_is_an_error(tmp_path: Path) -> None:
    repo, _ = _task(tmp_path, "42\n")
    assert run_hidden(repo, tmp_path / "absent", tmp_path / "verify").status == "error"
