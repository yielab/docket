"""The ticket is triaged to the policy's category, priority and refund, and the reply promises no more."""

import os
import re
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def _lines() -> list[str]:
    return (REPO / "reply.md").read_text(encoding="utf-8").splitlines()


def test_the_header_lines_follow_the_format() -> None:
    lines = _lines()
    assert (
        lines[0].startswith("To:") and "dana.okafor@example.test" in lines[0]
    )  # a display name may lead
    assert lines[1].strip() == "Priority: P2"
    assert lines[2].strip().lower() == "category: damaged-item"


def test_the_refund_is_the_item_price_and_not_the_postage() -> None:
    text = "\n".join(_lines()[3:])
    assert re.search(r"\$\s?18\.50", text), text
    assert "23.40" not in text  # the order total with postage; naming the postage it keeps is right


def test_the_reply_promises_no_replacement() -> None:
    text = "\n".join(_lines()[3:]).lower()
    assert "dana" in text
    assert "we will send a replacement" not in text
    assert "replacement is on its way" not in text
