"""The perimeter every outbound HTTP call docket makes itself stays inside.

`call_operation` (a service's operation) and `fetch_url` (the `fetch` tool) run in docket's own
process, not in the jail, so what such a call may reach is decided here and nowhere else: the
address check, the connector that dials only an address it has just checked, and the redirect
guard, composed by `build_opener`. Like the callers' host sets it is containment, independent of the
gate that decided before the call, and it holds no policy vocabulary: a caller says which host names
it permits and which of them it has listed exactly, and the wording of a refusal.

Zero new dependencies: stdlib `urllib` and `http.client`.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol
from urllib.request import HTTPHandler, HTTPSHandler

from docket.kernel import clock as _clock
from docket.kernel.errors import Refused

_READ_CHUNK = 8192

Resolver = Callable[..., list[Any]]
Dialer = Callable[
    [int, int, int, tuple[Any, ...], float | None, tuple[str, int] | None], socket.socket
]

_V6_RESERVED = ipaddress.ip_network("::/8")
_V6_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """The IPv4 addresses an IPv6 one carries: 6to4, Teredo (server and client) and NAT64."""
    found: list[ipaddress.IPv4Address] = []
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in _NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def address_refused(address: str) -> bool:
    """True for an address that is not a public unicast one (or does not parse); an IPv6 address
    that carries an IPv4 one (mapped, 6to4, Teredo, NAT64) is judged by it, and `::/8` and
    `fec0::/10` are refused."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif (
            (ip in _V6_RESERVED and ip not in _NAT64)
            or ip in _V6_SITE_LOCAL
            or any(address_refused(str(v4)) for v4 in _embedded_v4(ip))
        ):
            return True
    return not ip.is_global or ip.is_multicast


def _dial(
    family: int,
    socktype: int,
    proto: int,
    sockaddr: tuple[Any, ...],
    timeout: float | None,
    source_address: tuple[str, int] | None,
) -> socket.socket:
    sock = socket.socket(family, socktype, proto)
    try:
        if timeout is not None:
            sock.settimeout(timeout)
        if source_address:
            sock.bind(source_address)
        sock.connect(sockaddr)
    except BaseException:
        sock.close()
        raise
    return sock


def _connector(
    listed: frozenset[str], fix: str, resolve: Resolver, dial: Dialer
) -> Callable[..., socket.socket]:
    """`socket.create_connection` that resolves once and dials only an address it has checked."""

    def connect(
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        host, port = address
        found = resolve(host, port, type=socket.SOCK_STREAM)
        if host.lower() not in listed:
            for info in found:
                if address_refused(str(info[4][0])):
                    raise Refused(
                        f"{host!r} resolves to {info[4][0]}, a private, loopback or link-local "
                        f"address; {fix}",
                    )
        error: OSError = OSError(f"{host!r} did not resolve")
        for family, socktype, proto, _canon, sockaddr in found:
            try:
                return dial(family, socktype, proto, sockaddr, timeout, source_address)
            except OSError as ex:
                error = ex
        raise error

    return connect


class _Conn(http.client.HTTPConnection):
    def __init__(self, host: str, *, connect: Callable[..., socket.socket], **kw: Any) -> None:
        super().__init__(host, **kw)
        self._create_connection = connect


class _SecureConn(http.client.HTTPSConnection):
    def __init__(self, host: str, *, connect: Callable[..., socket.socket], **kw: Any) -> None:
        super().__init__(host, **kw)
        self._create_connection = connect


class _HttpHandler(HTTPHandler):
    def __init__(self, connect: Callable[..., socket.socket]) -> None:
        super().__init__()
        self._connect = connect

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(lambda host, **kw: _Conn(host, connect=self._connect, **kw), req)


class _HttpsHandler(HTTPSHandler):
    def __init__(self, connect: Callable[..., socket.socket]) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(context=self._tls)
        self._connect = connect

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            lambda host, **kw: _SecureConn(host, connect=self._connect, **kw),
            req,
            context=self._tls,
        )


class _PerimeterRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect off the permitted hosts, off http(s), or from https down to http."""

    def __init__(self, permits: Callable[[str], bool], outside: str) -> None:
        self._permits = permits
        self._outside = outside

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urllib.parse.urlsplit(newurl)
        host = (target.hostname or "").lower()
        if target.scheme not in ("http", "https") or not self._permits(host):
            raise Refused(
                f"redirected to {host or newurl!r} over {target.scheme or '?'}, "
                f"which is {self._outside}",
            )
        if req.full_url.startswith("https:") and target.scheme != "https":
            raise Refused(f"redirected to {host!r} over http from https, a downgrade")
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def build_opener(
    permits: Callable[[str], bool],
    listed: frozenset[str],
    *,
    outside: str,
    fix: str,
    resolve: Resolver = socket.getaddrinfo,
    dial: Dialer = _dial,
) -> urllib.request.OpenerDirector:
    """The one opener an outbound call opens through (no proxy, one lookup, a checked address).
    *permits* judges a redirect's host; only the *listed* names keep a private address."""
    connect = _connector(listed, fix, resolve, dial)
    opener = urllib.request.OpenerDirector()
    for handler in (
        _HttpHandler(connect),
        _HttpsHandler(connect),
        _PerimeterRedirects(permits, outside),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


class _Body(Protocol):
    def read1(self, n: int, /) -> bytes: ...


def read_until_deadline(resp: _Body, cap: int, deadline: float) -> bytes | None:
    """Up to *cap* + 1 bytes of *resp*; None when the monotonic *deadline* passes first."""
    buf = bytearray()
    while len(buf) <= cap:
        chunk = resp.read1(min(_READ_CHUNK, cap + 1 - len(buf)))
        if not chunk:
            break
        buf += chunk
        if _clock.monotonic() >= deadline:
            return None
    return bytes(buf)
