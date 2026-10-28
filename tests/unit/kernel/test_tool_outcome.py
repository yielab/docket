"""``kernel.tool_outcome`` -- the one place a tool result is cut, and where its whole is kept."""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import (
    artifact_path_in,
    artifact_scope,
    bounded_text,
    text_outcome,
)

SUBJECT = "docket.kernel.tool_outcome"


@pytest.fixture
def capped() -> Iterator[None]:
    """A 100-character cap and a pod called ``pod`` that exists in the home."""
    (current_home().pods_dir / "pod").mkdir(parents=True)
    with use_home(dataclasses.replace(current_home(), tool_max_output_chars=100)):
        yield


def _whole() -> str:
    return "".join(f"line {n:04d}\n" for n in range(60))


def test_a_result_over_the_cap_is_stored_whole_and_names_its_file(capped: None) -> None:
    whole = _whole()

    with artifact_scope("pod"):
        out = text_outcome(whole)

    path = artifact_path_in(out.content)
    assert path is not None
    assert Path(path).read_text() == whole
    assert Path(path).name == f"{hashlib.sha256(whole.encode()).hexdigest()}.txt"
    assert Path(path).parent == current_home().pod_cache_dir("pod") / "artifacts"
    assert out.content.endswith(
        f"[full output: {path} \u2014 read it with read(path, offset, limit)]"
    )
    assert "[truncated:" in out.content


def test_the_artifact_and_its_directory_are_private(capped: None) -> None:
    with artifact_scope("pod"):
        out = text_outcome(_whole())

    path = Path(artifact_path_in(out.content) or "")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


def test_a_result_that_fits_writes_nothing(capped: None) -> None:
    with artifact_scope("pod"):
        out = text_outcome("short")

    assert out.content == "short"
    assert not (current_home().pod_cache_dir("pod") / "artifacts").exists()


def test_equal_text_is_stored_once(capped: None) -> None:
    with artifact_scope("pod"):
        first = text_outcome(_whole())
        second = text_outcome(_whole())

    assert first.content == second.content
    assert len(list((current_home().pod_cache_dir("pod") / "artifacts").iterdir())) == 1


def test_a_tail_share_puts_the_end_of_the_text_after_the_marker(capped: None) -> None:
    whole = _whole()

    with artifact_scope("pod"):
        cut = bounded_text(whole, 0.6)

    body = cut.split("\n\n[full output:")[0].strip()
    assert body.endswith(whole.strip().splitlines()[-1])
    assert "[truncated:" in body


def test_outside_a_scope_the_result_is_cut_and_nothing_is_stored(capped: None) -> None:
    out = text_outcome(_whole())

    assert "[truncated:" in out.content
    assert artifact_path_in(out.content) is None
    assert not (current_home().pods_dir / "pod" / "cache").exists()


@pytest.mark.parametrize("pod", ["", "ghost", "../pod", "a/b", ".."])
def test_a_pod_that_does_not_exist_or_is_not_a_name_stores_nothing(capped: None, pod: str) -> None:
    with artifact_scope(pod):
        out = text_outcome(_whole())

    assert artifact_path_in(out.content) is None
    assert "[truncated:" in out.content


def test_an_unwritable_artifacts_directory_degrades_to_a_plain_cut(capped: None) -> None:
    cache = current_home().pod_cache_dir("pod")
    cache.mkdir(parents=True)
    (cache / "artifacts").write_text("a file where the directory should be")

    with artifact_scope("pod"):
        out = text_outcome(_whole())

    assert artifact_path_in(out.content) is None
    assert "[truncated:" in out.content


def test_artifact_path_in_finds_only_the_closing_line() -> None:
    assert artifact_path_in("no marker here") is None
    text = "x\n\n[full output: /a b/c.txt \u2014 read it with read(path, offset, limit)]"
    assert artifact_path_in(text) == "/a b/c.txt"


def test_the_artifact_line_counts_against_the_cap(capped: None) -> None:
    big = "x" * 9_000

    with (
        use_home(dataclasses.replace(current_home(), tool_max_output_chars=2_000)),
        artifact_scope("pod"),
    ):
        out = text_outcome(big)

    assert artifact_path_in(out.content) is not None
    assert len(out.content) <= 2_000 + len("\n\n[truncated: 7000 more characters]") + 2
