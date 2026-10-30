"""The hacker-news recipe: a routine pod digests a news site, keeps the stories, and reports on them.

The whole product runs for real as ``python -m docket`` subprocesses; only the model and the site
(a local server that answers the way the Hacker News search API does) are fake.
"""

from __future__ import annotations

import http.server
import json
import shutil
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.kernel.templates import RECIPES_DIR
from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.e2e_workdir import workdir_pod
from tests.support.model_server import FakeModel, Reply, call, say

RECIPE = RECIPES_DIR / "hacker-news"

_STORIES = [
    {
        "objectID": "9001",
        "title": "Rust 3.0 ships a new borrow checker",
        "points": 410,
        "num_comments": 120,
        "url": "https://example.test/rust-3",
        "created_at": "2026-10-29T08:00:00Z",
    },
    {
        "objectID": "9002",
        "title": "Postgres is enough for your queue",
        "points": 880,
        "num_comments": 340,
        "url": "https://example.test/postgres-queue",
        "created_at": "2026-10-29T09:30:00Z",
    },
    {
        "objectID": "9003",
        "title": "Show HN: A tiny static site generator",
        "points": 150,
        "num_comments": 45,
        "created_at": "2026-10-30T07:10:00Z",
    },
]
_COMMENTS = {
    "9001": ["The new borrow checker rejects fewer valid programs", "Compile times got worse"],
    "9002": ["A table with SKIP LOCKED is all a queue needs", "It stops scaling past one box"],
    "9003": ["Nice, but how does it handle incremental builds", "I would use it for docs"],
}
_FRONT_PAGE_QUERY = {
    "tags": "front_page",
    "hitsPerPage": 10,
    "attributesToRetrieve": "title,points,num_comments,objectID,url,created_at",
    "attributesToHighlight": "none",
}
_COMMENTS_QUERY = {
    "hitsPerPage": 4,
    "attributesToRetrieve": "author,comment_text,points",
    "attributesToHighlight": "none",
}
_SUMMARY = {
    "9001": "Rust 3.0 replaces the borrow checker, so fewer correct programs are refused.",
    "9002": "An essay arguing that a Postgres table can serve as a job queue.",
    "9003": "A small static site generator shown by its author.",
}
_QUOTE = {
    "9001": "rejects fewer valid programs",
    "9002": "SKIP LOCKED is all a queue needs",
    "9003": "how does it handle incremental builds",
}
_DISCUSSION = {
    "9001": 'Readers welcome it but dispute compile times; one says it "rejects fewer valid programs".',
    "9002": 'Most agree a table is enough, though one objects it "stops scaling past one box"; another: "SKIP LOCKED is all a queue needs".',
    "9003": 'Interest in docs use; the main question is "how does it handle incremental builds".',
}


class _HnHandler(http.server.BaseHTTPRequestHandler):
    """A fake of ``hn.algolia.com/api/v1``: ``GET /search`` answers a front page or the comments of
    one story. Every request is recorded with its method, path, query, Host and task header."""

    def do_GET(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.server.calls.append(  # type: ignore[attr-defined]
            {
                "method": "GET",
                "path": parts.path,
                "query": query,
                "host": self.headers.get("Host", ""),
                "task": self.headers.get("X-Docket-Task", ""),
            }
        )
        tags = query.get("tags", "")
        if tags == "front_page":
            payload: dict[str, Any] = {"hits": _STORIES, "nbHits": len(_STORIES)}
        elif tags.startswith("comment,story_"):
            story = tags.removeprefix("comment,story_")
            hits = [
                {"author": f"user{n}", "comment_text": text, "points": None}
                for n, text in enumerate(_COMMENTS.get(story, []))
            ]
            payload = {"hits": hits, "nbHits": len(hits)}
        else:
            self.send_error(400, "unexpected tags")
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the test output quiet."""


@pytest.fixture()
def hn_server() -> Iterator[http.server.HTTPServer]:
    """The fake site on 127.0.0.1 and an ephemeral port; ``calls`` lists what it received."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _HnHandler)
    server.calls = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _recipe_on(w: World, server: http.server.HTTPServer) -> Path:
    """The shipped recipe with its service pointed at the fake site, which is on loopback and so
    must be listed as a host; nothing else of the recipe changes."""
    recipe = w.root / "hacker-news-recipe"
    shutil.copytree(RECIPE, recipe)
    document = yaml.safe_load((recipe / "services" / "hn.yaml").read_text(encoding="utf-8"))
    document["baseUrl"] = f"http://127.0.0.1:{server.server_port}/api/v1"
    document["hosts"] = ["127.0.0.1"]
    (recipe / "services" / "hn.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    return recipe


def _as_sent(arguments: dict[str, Any]) -> dict[str, str]:
    """The arguments of a service call as the site receives them: a query string of text."""
    return {k: str(v) for k, v in arguments.items()}


def _story_row(story: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": story["objectID"],
        "title": story["title"],
        "url": story.get("url", f"https://news.ycombinator.com/item?id={story['objectID']}"),
        "points": story["points"],
        "comments": story["num_comments"],
        "captured": story["created_at"][:10],
    }


def _digest_analyst(first: bool) -> list[Reply]:
    """The Analyst's replies for one digest: read the front page and add the stories (the second
    digest sees the same page), then fill the stories that have no summary yet."""
    collect = [call("svc__hn__search", f"s{int(first)}", **_FRONT_PAGE_QUERY)]
    for n, story in enumerate(_STORIES if first else _STORIES[:2]):
        collect.append(call("rec__stories__add", f"a{int(first)}{n}", **_story_row(story)))
    collect.append(say("Added the stories; any that were already there were returned."))
    find = call(
        "rec__query",
        f"q{int(first)}",
        sql="SELECT id, title FROM stories WHERE summary IS NULL OR summary = ''",
    )
    if not first:
        return [*collect, find, say("Every story already has its summary and discussion.")]
    fill: list[Reply] = [find]
    for story in _STORIES:
        sid = story["objectID"]
        fill.append(
            call("svc__hn__comments", f"c{sid}", tags=f"comment,story_{sid}", **_COMMENTS_QUERY)
        )
        fill.append(
            call(
                "rec__stories__update",
                f"u{sid}",
                match={"id": sid},
                values={"summary": _SUMMARY[sid], "discussion": _DISCUSSION[sid]},
            )
        )
    return [*collect, *fill, say("Filled the summary and discussion of every story.")]


def _script() -> dict[str, list[Reply]]:
    export_sql = (
        "SELECT title, comments, points, url, summary, discussion FROM stories "
        "WHERE _at >= date('now', '-7 days') ORDER BY comments DESC"
    )
    analysis = "# Analysis\n\n" + "".join(
        f"- {s['title']}: {_DISCUSSION[s['objectID']]}\n" for s in _STORIES
    )
    return {
        "analyst": [
            *_digest_analyst(True),
            *_digest_analyst(False),
            call("rec__query", "r1", sql="SELECT COUNT(*) AS n, SUM(comments) AS c FROM stories"),
            say("Compiled: three stories, the Postgres one has the most comments."),
        ],
        "reviewer": [
            call("rec__query", "v1", sql="SELECT id, summary, discussion FROM stories"),
            say("APPROVE: every row has a summary and a discussion."),
            call("rec__query", "v2", sql="SELECT COUNT(*) AS n FROM stories"),
            say("APPROVE: still three rows."),
            say("APPROVE"),
        ],
        "writer": [
            call("rec__export", "w1", sql=export_sql, path="report.md", format="md"),
            call("write", "w2", path="analysis.md", content=analysis),
            say("report.md and analysis.md are written."),
        ],
    }


def _rows(w: World) -> list[dict[str, Any]]:
    shown = w.docket("pod", "records", "stories", "--pod", w.pod, "--json").json()
    assert isinstance(shown, dict)
    rows = shown["rows"]
    assert isinstance(rows, list)
    return rows


def _run(w: World) -> None:
    w.docket("run", "--pod", w.pod, "--timeout", "60")


def test_the_shipped_service_reads_the_public_search_api_and_cannot_write() -> None:
    document = yaml.safe_load((RECIPE / "services" / "hn.yaml").read_text(encoding="utf-8"))
    assert document["baseUrl"] == "https://hn.algolia.com/api/v1"
    assert document["hosts"] == ["hn.algolia.com"]
    assert "auth" not in document
    assert {op["method"] for op in document["operations"]} == {"GET"}
    assert {op["name"] for op in document["operations"]} == {"search", "comments"}
    assert all(op.get("access", "read") == "read" for op in document["operations"])


def test_a_pod_digests_a_news_site_keeps_one_row_per_story_and_reports_on_the_week(
    world: Callable[..., World],
    fake_model: Callable[..., FakeModel],
    hn_server: http.server.HTTPServer,
) -> None:
    calls: list[dict[str, Any]] = hn_server.calls  # type: ignore[attr-defined]
    model = fake_model(script=_script())
    w, work_dir = workdir_pod(world, model)
    w.docket("pod", "update", str(_recipe_on(w, hn_server)), "--pod", w.pod)

    first = w.add_task("Digest the Hacker News front page", "--pipeline", "digest")
    _run(w)
    assert w.task(first)["task"]["status"] == "done", w.task(first)
    rows = _rows(w)
    assert {r["id"]: r["comments"] for r in rows} == {"9001": 120, "9002": 340, "9003": 45}
    assert all(r["summary"] and r["discussion"] for r in rows)
    assert {r["_task"] for r in rows} == {first}
    assert {r["id"]: r["url"] for r in rows}["9003"] == "https://news.ycombinator.com/item?id=9003"

    # the comments the site returned reached the model, and the discussion quotes them
    analyst = model.by_role("analyst")
    assert "svc__hn__search" in analyst[0].tools and "svc__hn__comments" in analyst[0].tools
    for sid, quote in _QUOTE.items():
        seen = next(r.tool_result(f"c{sid}") for r in analyst if r.tool_result(f"c{sid}"))
        assert quote in (seen or "")

    # a second capture of the same page adds nothing: one row per story
    second = w.add_task("Digest the Hacker News front page again", "--pipeline", "digest")
    _run(w)
    assert w.task(second)["task"]["status"] == "done", w.task(second)
    assert sorted(r["id"] for r in _rows(w)) == ["9001", "9002", "9003"]
    assert all(r["_task"] == first for r in _rows(w))

    # the weekly routine's own task writes both files from the set
    routine = yaml.safe_load((RECIPE / "routines" / "weekly-report.yaml").read_text("utf-8"))
    assert routine["task"].get("pipeline") is None
    report_task = w.add_task(routine["task"]["description"])
    _run(w)
    assert w.task(report_task)["task"]["status"] == "done", w.task(report_task)

    report = (work_dir / "report.md").read_text(encoding="utf-8")
    titles = [s["title"] for s in sorted(_STORIES, key=lambda s: -s["num_comments"])]
    positions = [report.index(t) for t in titles]
    assert positions == sorted(positions), report
    assert titles[0] == "Postgres is enough for your queue"
    for story in _STORIES:
        sid = story["objectID"]
        assert _SUMMARY[sid] in report and _QUOTE[sid] in report, sid
    analysis = (work_dir / "analysis.md").read_text(encoding="utf-8")
    assert sum(s["title"] in analysis for s in _STORIES) > 1, analysis

    # the site saw only reads, on the declared host, each carrying the task that made it
    assert [c["query"]["tags"] for c in calls] == [
        "front_page",
        *(f"comment,story_{s['objectID']}" for s in _STORIES),
        "front_page",
    ]
    assert {c["method"] for c in calls} == {"GET"}
    assert {c["host"] for c in calls} == {f"127.0.0.1:{hn_server.server_port}"}
    assert {c["path"] for c in calls} == {"/api/v1/search"}
    assert calls[0]["query"] == _as_sent(_FRONT_PAGE_QUERY)
    assert calls[1]["query"] == _as_sent({**_COMMENTS_QUERY, "tags": "comment,story_9001"})
    assert [c["task"] for c in calls] == [first] * 4 + [second]
    oracles.assert_log_verifies(w)
