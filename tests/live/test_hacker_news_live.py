"""Opt-in, live: the hacker-news recipe against the real Hacker News search API and the operator's model.

This lane has no duration ceiling: a real model run takes minutes (DOCKET_RUN_LIVE_HN=1)."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.kernel.templates import RECIPES_DIR
from tests.support.e2e import World
from tests.support.e2e_workdir import workdir_pod

_FRONT_PAGE = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(
    {
        "tags": "front_page",
        "hitsPerPage": 10,
        "attributesToRetrieve": "title,points,num_comments,objectID,url,created_at",
        "attributesToHighlight": "none",
    }
)
_ENDPOINT = "http://127.0.0.1:8081/v1"
_RUN_TIMEOUT_S = 1800


class _Endpoint:
    """What a ``World`` reads of its model: the base URL the whole process is pointed at."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


def _front_page_titles() -> set[str]:
    with urllib.request.urlopen(_FRONT_PAGE, timeout=30) as response:
        hits = json.loads(response.read())["hits"]
    return {str(hit["title"]) for hit in hits}


def _rows(w: World) -> list[dict[str, Any]]:
    shown = w.docket("pod", "records", "stories", "--pod", w.pod, "--json").json()
    rows = shown["rows"]
    assert isinstance(rows, list)
    return rows


@pytest.mark.skipif(
    os.environ.get("DOCKET_RUN_LIVE_HN") != "1",
    reason="set DOCKET_RUN_LIVE_HN=1 to run the hacker-news recipe against hn.algolia.com",
)
def test_the_hacker_news_recipe_digests_the_real_front_page_and_writes_both_reports(
    tmp_path: Path,
) -> None:
    """Opt-in evidence with the operator's local model (``DOCKET_LIVE_HN_ENDPOINT``)."""
    endpoint = os.environ.get("DOCKET_LIVE_HN_ENDPOINT", _ENDPOINT)
    env = {
        "DOCKET_LLM_BASE_URL": endpoint,
        "DOCKET_LLM_API_KEY": os.environ.get("DOCKET_LLM_API_KEY", "live"),
        "DOCKET_TOOL_MAX_OUTPUT_CHARS": os.environ.get("DOCKET_TOOL_MAX_OUTPUT_CHARS", "4000"),
        "NO_PROXY": "127.0.0.1,localhost",
    }
    on_front_page = _front_page_titles()
    assert on_front_page, "the real front page answered with no stories"

    w, work_dir = workdir_pod(
        lambda model: World(tmp_path / "world", model, env=env),
        _Endpoint(endpoint),  # type: ignore[arg-type]
    )
    w.docket("pod", "update", "hacker-news", "--pod", w.pod)
    run = ("run", "--pod", w.pod, "--timeout", str(_RUN_TIMEOUT_S))

    w.add_task("Digest the Hacker News front page", "--pipeline", "digest")
    w.docket(*run, check=False, timeout=_RUN_TIMEOUT_S + 60)
    rows = [r for r in _rows(w) if r["title"] in on_front_page and (r["comments"] or 0) > 0]
    assert rows, f"no captured story is on the real front page with comments: {_rows(w)}"
    assert any(str(r["summary"] or "").strip() and str(r["discussion"] or "").strip() for r in rows)

    routine = yaml.safe_load(
        (RECIPES_DIR / "hacker-news" / "routines" / "weekly-report.yaml").read_text("utf-8")
    )
    w.add_task(routine["task"]["description"])
    w.docket(*run, check=False, timeout=_RUN_TIMEOUT_S + 60)
    report = (work_dir / "report.md").read_text(encoding="utf-8")
    analysis = (work_dir / "analysis.md").read_text(encoding="utf-8")
    assert report.strip() and analysis.strip()
    assert any(r["title"] in report for r in rows), report
