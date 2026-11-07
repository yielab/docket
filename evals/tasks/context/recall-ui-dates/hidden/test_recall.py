"""The answer carries the four facts of 01-start.md: decision, failure, file, open item."""

import json
import os
from pathlib import Path

import pytest

ANSWER = Path(os.environ["EVAL_REPO"]) / "answer.json"


def _value(key: str) -> str:
    assert ANSWER.is_file(), "answer.json was not written"
    data = json.loads(ANSWER.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get(key), str), f"no string key {key}"
    return data[key].lower()


@pytest.mark.parametrize(
    ("key", "needles"),
    [
        ("decision", ["utc", "iso"]),
        ("failure", ["07/11/2026", "2026-11-07"]),
        ("file", ["src/ui/dates.py"]),
        ("open_item", ["emails/templates/receipt.html"]),
    ],
)
def test_the_answer_recalls(key: str, needles: list[str]) -> None:
    value = _value(key)
    missing = [n for n in needles if n.lower() not in value]
    assert not missing, f"{key} lost {missing}"
