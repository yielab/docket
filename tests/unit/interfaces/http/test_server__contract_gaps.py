"""The HTTP server's body cap and socket timeout bound."""

from __future__ import annotations

from docket.interfaces.http import exchange
from docket.interfaces.http.server import _DocketHandler

SUBJECT = "docket.interfaces.http.server"


class _FakeRFile:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.read_called = False

    def read(self, n: int) -> bytes:
        self.read_called = True
        return self._data[:n]


class TestReadBodyCap:
    """Direct seam test for `_DocketHandler._read_body` -- a real oversized
    upload would only make the same point more slowly."""

    def _bare_handler(self, content_length: str, data: bytes = b"") -> _DocketHandler:
        handler = _DocketHandler.__new__(_DocketHandler)
        handler.headers = {"Content-Length": content_length}  # type: ignore[assignment]
        handler.rfile = _FakeRFile(data)  # type: ignore[assignment]
        handler._sent = []  # type: ignore[attr-defined]

        def _send_json_error(msg: str, status: int = 400) -> None:
            handler._sent.append((msg, status))  # type: ignore[attr-defined]

        handler._send_json_error = _send_json_error  # type: ignore[method-assign]
        return handler

    def test_over_cap_sends_413_without_touching_rfile(self) -> None:
        handler = self._bare_handler(str(exchange.MAX_POST_BODY_BYTES + 1))
        result = handler._read_body()
        assert result is None
        assert handler.rfile.read_called is False  # type: ignore[attr-defined]
        assert handler._sent == [("Request body too large", 413)]  # type: ignore[attr-defined]

    def test_small_body_is_read_normally(self) -> None:
        payload = b"{}"
        handler = self._bare_handler(str(len(payload)), data=payload)
        result = handler._read_body()
        assert result == payload
        assert handler.rfile.read_called is True  # type: ignore[attr-defined]

    def test_exactly_at_the_cap_is_still_read_not_rejected(self) -> None:
        payload = b"x" * exchange.MAX_POST_BODY_BYTES
        handler = self._bare_handler(str(exchange.MAX_POST_BODY_BYTES), data=payload)
        result = handler._read_body()
        assert result == payload
        assert handler.rfile.read_called is True  # type: ignore[attr-defined]

    def test_no_content_length_reads_as_empty_object(self) -> None:
        handler = self._bare_handler("0")
        result = handler._read_body()
        assert result == b"{}"


class TestSocketTimeoutBound:
    def test_handler_declares_a_positive_read_timeout(self) -> None:
        assert isinstance(_DocketHandler.timeout, (int, float))
        assert _DocketHandler.timeout > 0
