"""The report answers the question and cites three distinct public hosts, all from the allowed list."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(os.environ["EVAL_REPO"])
ALLOWED = {"docs.python.org", "peps.python.org", "en.wikipedia.org"}


def _report() -> str:
    return (REPO / "report.md").read_text(encoding="utf-8")


def _hosts() -> set[str]:
    urls = re.findall(r"https?://[^\s)>\]\"'`]+", _report())
    return {(urlsplit(u).hostname or "").lower() for u in urls}


def test_three_distinct_allowed_hosts_are_cited() -> None:
    assert len(_hosts() & ALLOWED) >= 3, _hosts()


def test_no_host_outside_the_allowed_list_is_cited() -> None:
    assert _hosts() <= ALLOWED, _hosts()


def test_the_answer_names_the_version_and_the_feature() -> None:
    text = _report()
    assert "3.7" in text
    assert "dataclass" in text.lower()
    assert len(text.split()) >= 40
