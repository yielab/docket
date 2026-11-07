"""The stories set holds one real row per story, with a summary and a discussion, and both reports exist.

Ported from the opt-in live test of the hacker-news recipe: the records are read from the export the
trial wrote (`EVAL_RECORDS`), the reports from the repository.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

REPO = Path(os.environ["EVAL_REPO"])
RECORDS = Path(os.environ["EVAL_RECORDS"])
FRONT_PAGE = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(
    {
        "tags": "front_page",
        "hitsPerPage": 30,
        "attributesToRetrieve": "title",
        "attributesToHighlight": "none",
    }
)


def _rows() -> list[dict]:
    return json.loads((RECORDS / "stories.json").read_text(encoding="utf-8"))["rows"]


def test_there_is_one_row_per_story() -> None:
    rows = _rows()
    assert len(rows) >= 3, rows
    ids = [str(r["id"]) for r in rows]
    assert len(set(ids)) == len(ids), ids


def test_each_row_is_a_commented_story_with_a_summary_and_a_discussion() -> None:
    for row in _rows():
        assert str(row["title"]).strip(), row
        assert (row["comments"] or 0) > 0, row
        assert str(row["summary"] or "").strip(), row
        discussion = str(row["discussion"] or "").strip()
        assert discussion and discussion != str(row["title"]).strip(), row


def test_both_reports_exist_and_the_report_names_a_recorded_story() -> None:
    report = (REPO / "report.md").read_text(encoding="utf-8")
    analysis = (REPO / "analysis.md").read_text(encoding="utf-8")
    assert report.strip() and analysis.strip()
    assert any(r["title"] in report for r in _rows()), report


def test_a_recorded_story_is_on_the_real_front_page() -> None:
    if os.environ.get("EVAL_SOLUTION_CHECK") == "1":
        pytest.skip("a reference solution holds fixed rows, not today's front page")
    try:
        with urllib.request.urlopen(FRONT_PAGE, timeout=30) as response:
            live = {str(h["title"]) for h in json.loads(response.read())["hits"]}
    except (urllib.error.URLError, OSError, ValueError):
        pytest.skip("hn.algolia.com did not answer")
    assert any(r["title"] in live for r in _rows()), "no recorded story is on the front page"
