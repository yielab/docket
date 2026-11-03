"""The perimeter outbound HTTP calls stay inside (`platform/perimeter.py`): addresses, one lookup, redirects."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from typing import Any

import pytest

from docket.kernel.errors import Refused
from docket.platform import perimeter as _perimeter

SUBJECT = "docket.platform.perimeter"

_STREAM, _TCP, _INET = 1, 6, 2
_REDIRECT_TO_LOOPBACK = (
    b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/x\r\nContent-Length: 0\r\n\r\n"
)
_OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nhi"


class TestAddressRefused:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.1.2.3",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.0.9",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "fd12:3456::1",
            "ff02::1",
            "fec0::1",
            "::7f00:1",
            "::ffff:127.0.0.1",
            "::ffff:7f00:1",
            "::ffff:10.0.0.1",
            "::ffff:169.254.169.254",
            "64:ff9b::7f00:1",
            "64:ff9b::a9fe:a9fe",
            "2002:7f00:1::",
            "2002:a00:1::1",
        ],
    )
    def test_refuses_a_non_public_address(self, address: str) -> None:
        assert _perimeter.address_refused(address)

    @pytest.mark.parametrize(
        "address", ["2130706433", "0x7f000001", "0177.0.0.1", "127.1", "localhost", "", "1.2.3"]
    )
    def test_refuses_what_does_not_parse_so_no_numeric_spelling_slips_by(
        self, address: str
    ) -> None:
        assert _perimeter.address_refused(address)

    @pytest.mark.parametrize(
        "address",
        [
            "93.184.216.34",
            "8.8.8.8",
            "2606:2800:220:1::1",
            "::ffff:93.184.216.34",
            "64:ff9b::5db8:d822",
        ],
    )
    def test_allows_a_public_address(self, address: str) -> None:
        assert not _perimeter.address_refused(address)


class _Sock:
    """What `http.client` needs of a socket, answering with canned bytes."""

    def __init__(self, reply: bytes) -> None:
        self._reply = reply
        self.sent = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, *_args: object, **_kwargs: object) -> io.BytesIO:
        return io.BytesIO(self._reply)

    def settimeout(self, *_args: object) -> None:
        return None

    def setsockopt(self, *_args: object) -> None:
        return None

    def close(self) -> None:
        return None


class _Net:
    """A resolver and a dialer that never touch the network; each records what it was asked."""

    def __init__(self, names: dict[str, list[list[str]]], replies: dict[str, bytes]) -> None:
        self.names = names
        self.replies = replies
        self.lookups: list[str] = []
        self.dialed: list[str] = []

    def resolve(self, host: str, port: int, **_kw: object) -> list[Any]:
        answers = self.names[host]
        answer = answers[min(len(self.lookups), len(answers) - 1)]
        self.lookups.append(host)
        return [(_INET, _STREAM, _TCP, "", (ip, port)) for ip in answer]

    def dial(
        self, _family: int, _type: int, _proto: int, sockaddr: tuple[Any, ...], *_rest: object
    ) -> Any:
        self.dialed.append(sockaddr[0])
        return _Sock(self.replies.get(sockaddr[0], _OK))


def _opener(
    net: _Net, *, permitted: tuple[str, ...] = ("page.test",), listed: frozenset[str] = frozenset()
) -> urllib.request.OpenerDirector:
    return _perimeter.build_opener(
        permitted.__contains__,
        listed,
        outside="not on the list",
        fix="list the host to permit it",
        resolve=net.resolve,
        dial=net.dial,
    )


class TestOneCheckedLookup:
    def test_the_connection_goes_to_the_first_answer_and_the_name_is_looked_up_once(self) -> None:
        net = _Net({"page.test": [["93.184.216.34"], ["127.0.0.1"]]}, {})
        with _opener(net).open("http://page.test/x") as resp:
            assert resp.read() == b"hi"
        assert net.lookups == ["page.test"]
        assert net.dialed == ["93.184.216.34"]

    def test_a_name_with_one_private_answer_among_public_ones_is_refused_unsent(self) -> None:
        net = _Net({"page.test": [["93.184.216.34", "10.0.0.5"]]}, {})
        with pytest.raises(Refused, match=r"resolves to 10\.0\.0\.5.*list the host to permit it"):
            _opener(net).open("http://page.test/x")
        assert net.dialed == []

    @pytest.mark.parametrize(
        "ip", ["127.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "::ffff:127.0.0.1", "fd00::1"]
    )
    def test_a_name_that_resolves_to_a_private_address_is_refused_unsent(self, ip: str) -> None:
        net = _Net({"page.test": [[ip]]}, {})
        with pytest.raises(Refused, match="private, loopback or link-local"):
            _opener(net).open("http://page.test/x")
        assert net.dialed == []

    def test_an_ip_literal_is_checked_like_a_name(self) -> None:
        net = _Net({"127.0.0.1": [["127.0.0.1"]], "[::1]": [["::1"]]}, {})
        with pytest.raises(Refused):
            _opener(net, permitted=("127.0.0.1",)).open("http://127.0.0.1/x")
        assert net.dialed == []

    def test_a_listed_host_keeps_its_private_address(self) -> None:
        net = _Net({"page.test": [["10.0.0.5"]]}, {})
        opener = _opener(net, listed=frozenset({"page.test"}))
        with opener.open("http://page.test/x") as resp:
            assert resp.read() == b"hi"
        assert net.dialed == ["10.0.0.5"]

    def test_a_permitted_host_that_is_not_listed_does_not_keep_it(self) -> None:
        net = _Net({"page.test": [["10.0.0.5"]]}, {})
        with pytest.raises(Refused):
            _opener(net, listed=frozenset({"other.test"})).open("http://page.test/x")
        assert net.dialed == []

    def test_a_redirect_to_a_private_address_is_refused_after_the_first_hop_only(self) -> None:
        net = _Net(
            {"page.test": [["93.184.216.34"]], "127.0.0.1": [["127.0.0.1"]]},
            {"93.184.216.34": _REDIRECT_TO_LOOPBACK},
        )
        with pytest.raises(Refused, match="which is not on the list"):
            _opener(net).open("http://page.test/x")
        assert net.dialed == ["93.184.216.34"]


class TestRedirectGuard:
    @staticmethod
    def _follow(start: str, target: str, permitted: tuple[str, ...] = ("a.test", "b.test")) -> Any:
        opener = _opener(_Net({}, {}), permitted=permitted)
        (guard,) = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        return guard.redirect_request(urllib.request.Request(start), None, 302, "Found", {}, target)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("https://a.test/", "https://b.test/next"),
            ("http://a.test/", "http://b.test/next"),
            ("http://a.test/", "https://b.test/next"),
        ],
    )
    def test_follows_a_redirect_inside_the_set_that_keeps_or_raises_the_scheme(
        self, start: str, target: str
    ) -> None:
        assert self._follow(start, target) is not None

    def test_refuses_https_down_to_http_even_on_a_permitted_host(self) -> None:
        with pytest.raises(Refused, match="downgrade"):
            self._follow("https://a.test/", "http://b.test/next")

    @pytest.mark.parametrize(
        "target",
        [
            "http://other.test/",
            "http://127.0.0.1/",
            "http://2130706433/",
            "ftp://a.test/file",
            "file:///etc/passwd",
            "gopher://a.test/",
        ],
    )
    def test_refuses_a_redirect_off_the_set_or_off_http(self, target: str) -> None:
        with pytest.raises(Refused, match="which is not on the list"):
            self._follow("http://a.test/", target)

    def test_the_refusal_is_not_an_http_error(self) -> None:
        with pytest.raises(Refused) as caught:
            self._follow("http://a.test/", "http://other.test/")
        assert not isinstance(caught.value, urllib.error.HTTPError)
