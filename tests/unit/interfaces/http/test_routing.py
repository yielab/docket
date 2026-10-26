"""SUBJECT: interfaces.http.routing -- how a path matches a table row, and the table itself."""

from __future__ import annotations

from docket.interfaces.http.exchange import HttpExchange
from docket.interfaces.http.routes.table import ROUTES
from docket.interfaces.http.routing import Route, find_route

SUBJECT = "docket.interfaces.http.routing"


def _noop(_h: HttpExchange, _arg: str) -> None:
    return None


class TestMatch:
    def test_literal_pattern_matches_only_itself(self) -> None:
        route = Route("GET", "/health", _noop)
        assert route.match("/health") == ""
        assert route.match("/health/x") is None

    def test_placeholder_captures_everything_after_the_prefix(self) -> None:
        route = Route("GET", "/runs/<id>", _noop)
        assert route.match("/runs/a/b") == "a/b"
        assert route.match("/runs") is None

    def test_bare_also_matches_the_prefix_with_an_empty_capture(self) -> None:
        route = Route("POST", "/escalations/<id>", _noop, bare=True)
        assert route.match("/escalations") == ""
        assert Route("POST", "/escalations/<id>", _noop).match("/escalations") is None

    def test_suffix_is_cut_from_the_capture(self) -> None:
        route = Route("GET", "/tasks/<pod>/<id>/diff", _noop, overlap=True)
        assert route.match("/tasks/demo/t1/diff") == "demo/t1"

    def test_overlap_decides_whether_prefix_and_suffix_may_share_characters(self) -> None:
        assert Route("GET", "/tasks/<id>/diff", _noop, overlap=True).match("/tasks/diff") == ""
        assert Route("POST", "/tasks/<id>/cancel", _noop).match("/tasks/cancel") is None


class TestTable:
    def test_first_matching_row_wins_and_method_must_agree(self) -> None:
        found = find_route(ROUTES, "GET", "/tasks/demo/t1/diff")
        assert found is not None
        assert found[0].pattern == "/tasks/<pod>/<id>/diff"
        assert found[1] == "demo/t1"
        assert find_route(ROUTES, "POST", "/health") is None

    def test_only_the_probe_routes_are_open(self) -> None:
        assert {r.pattern for r in ROUTES if not r.auth} == {"/status.json", "/metrics", "/health"}

    def test_no_method_and_pattern_pair_repeats(self) -> None:
        pairs = [(r.method, r.pattern) for r in ROUTES]
        assert len(pairs) == len(set(pairs))
