"""The pure helpers of the service executor (`platform/service_http.py`)."""

from __future__ import annotations

import pytest

from docket.kernel.errors import InvalidInput
from docket.kernel.service import ResponseProjection
from docket.platform import service_http as _svc

SUBJECT = "docket.platform.service_http"


def _req(**kwargs: object) -> _svc.ServiceRequest:
    kwargs.setdefault("method", "GET")
    kwargs.setdefault("base_url", "https://api.example.test/v1/")
    return _svc.ServiceRequest(**kwargs)  # type: ignore[arg-type]


class TestBuildUrl:
    def test_joins_the_base_and_the_path_without_a_double_slash(self) -> None:
        assert _svc.build_url(_req(path="/things")) == "https://api.example.test/v1/things"

    def test_encodes_every_unsafe_character_of_a_parameter(self) -> None:
        url = _svc.build_url(_req(path="/a/{id}", path_params={"id": "x/y z?#%"}))
        assert url == "https://api.example.test/v1/a/x%2Fy%20z%3F%23%25"

    def test_appends_the_query_encoded_with_booleans_as_words(self) -> None:
        url = _svc.build_url(_req(path="/s", query={"q": "a&b", "on": True, "off": False}))
        assert url.endswith("/s?q=a%26b&on=true&off=false")

    @pytest.mark.parametrize(
        "path, params",
        [("/a/{id}", {}), ("/a/{id}", {"id": ".."}), ("/a/{id}", {"id": "."}), ("/a/{", {})],
    )
    def test_refuses_an_unresolvable_path(self, path: str, params: dict[str, str]) -> None:
        with pytest.raises(InvalidInput):
            _svc.build_url(_req(path=path, path_params=params))


class TestCheckHeaders:
    @pytest.mark.parametrize(
        "headers",
        [
            {"X": "a\nb"},
            {"X": "a\rb"},
            {"X": "a\x00b"},
            {"Bad Name": "v"},
            {"": "v"},
            {"content-length": "3"},
            {"Transfer-Encoding": "chunked"},
            {"HOST": "x"},
        ],
    )
    def test_refuses_an_unsafe_header(self, headers: dict[str, str]) -> None:
        with pytest.raises(InvalidInput):
            _svc.check_headers(headers)

    def test_accepts_ordinary_headers(self) -> None:
        _svc.check_headers({"Authorization": "Bearer t", "X-Api-Version": "2"})


class TestRedaction:
    def test_collects_credential_headers_by_name_and_each_word(self) -> None:
        values = _svc.redactions(
            {"Authorization": "Bearer abc123", "Accept": "application/json", "X-Api-Key": "k9"},
            ("extra",),
        )
        assert set(values) == {"Bearer abc123", "abc123", "k9", "extra"}

    def test_replaces_the_longest_first(self) -> None:
        text = _svc.redact("echo Bearer abc123 and abc123", ("abc123", "Bearer abc123"))
        assert text == "echo [REDACTED] and [REDACTED]"

    def test_ignores_an_empty_value(self) -> None:
        assert _svc.redact("kept", ("",)) == "kept"


_ROWS = {"results": [{"title": "a", "url": "u1", "score": 1}, {"title": "b", "url": "u2"}]}


class TestProjectResponse:
    def test_a_list_at_the_path_is_reduced_to_the_fields_in_order(self) -> None:
        shape = ResponseProjection(items="results", fields=["url", "title"])

        assert _svc.project_response(_ROWS, shape) == [
            {"url": "u1", "title": "a"},
            {"url": "u2", "title": "b"},
        ]

    def test_a_dotted_path_walks_objects(self) -> None:
        shape = ResponseProjection(items="web.results", fields=["url"])

        assert _svc.project_response({"web": _ROWS}, shape) == [{"url": "u1"}, {"url": "u2"}]

    @pytest.mark.parametrize(
        "body",
        [{"other": 1}, {"results": {"url": "u"}}, {"results": "text"}, [1, 2], "words", 7],
    )
    def test_a_body_without_a_list_at_the_path_comes_back_whole(self, body: object) -> None:
        shape = ResponseProjection(items="results", fields=["url"])

        assert _svc.project_response(body, shape) is body

    def test_an_element_that_is_not_an_object_is_kept(self) -> None:
        shape = ResponseProjection(items="results", fields=["url"])

        assert _svc.project_response({"results": ["x", {"url": "u", "t": 1}]}, shape) == [
            "x",
            {"url": "u"},
        ]
