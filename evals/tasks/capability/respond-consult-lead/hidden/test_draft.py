"""The operator's answer to the Lead's consult reached the reply; nothing retired was offered."""

import os
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def _draft() -> str:
    return (REPO / "draft.md").read_text(encoding="utf-8")


def test_the_first_line_names_the_recipient() -> None:
    assert _draft().splitlines()[0].strip() == "To: marisol.quintero@example.test"


def test_the_operators_code_is_offered() -> None:
    text = _draft()
    assert "AMBER-15" in text
    assert "15 percent" in text or "15%" in text


def test_no_retired_code_is_offered() -> None:
    text = _draft()
    assert "SUMMER-10" not in text and "WELCOME-5" not in text


def test_the_reply_addresses_the_customer() -> None:
    assert "marisol" in _draft().lower()
