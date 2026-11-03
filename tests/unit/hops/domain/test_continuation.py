"""The continuation message names the stop, the report and the changed paths, and says continue."""

from __future__ import annotations

from docket.hops.domain import continuation as _c

SUBJECT = "docket.hops.domain.continuation"


def test_names_the_stop_the_error_and_the_instruction() -> None:
    text = _c.continuation_message("model timed out", "", [])
    assert "stopped before it finished: model timed out." in text
    assert text.endswith(
        "Continue from where you stopped; do not start over; finish as the step asks."
    )


def test_carries_the_summary_when_there_is_one() -> None:
    assert "What it reported: wrote app.txt" in _c.continuation_message("e", "wrote app.txt", [])
    assert "What it reported" not in _c.continuation_message("e", "  ", [])


def test_lists_at_most_twenty_changed_paths() -> None:
    paths = [f"f{i}.py" for i in range(25)]
    text = _c.continuation_message("e", "", paths)
    assert "f19.py" in text
    assert "f20.py" not in text
    assert "(+5 more)" in text


def test_is_deterministic_text_only() -> None:
    assert _c.continuation_message("e", "s", ["a"]) == _c.continuation_message("e", "s", ["a"])
    assert "Paths changed" not in _c.continuation_message("e", "s", [])
