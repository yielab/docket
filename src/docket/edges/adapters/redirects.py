"""Same-origin redirect policy for outbound requests that carry a credential.

urllib's default opener follows any redirect and re-sends the request headers, so an
`Authorization` or webhook signature reaches whatever host a 3xx names. The chat and probe
calls, the OTLP exporter and the ntfy and webhook channels open through `open_same_origin`,
which refuses a redirect to another scheme, host or port. `fetch` keeps its own allowlist.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None] | None:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        return None
    return (scheme, (parts.hostname or "").lower(), port)


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect whose scheme, host or port differs from the request's own."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        if _origin(newurl) is None or _origin(newurl) != _origin(req.full_url):
            target = urllib.parse.urlsplit(newurl).hostname or ""
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                f"redirected to {target!r}, which is not the origin of this request",
                {},  # type: ignore[arg-type]
                None,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


_OPENER = urllib.request.build_opener(SameOriginRedirectHandler())


def open_same_origin(request: urllib.request.Request, *args: Any, **kwargs: Any) -> Any:
    """`urlopen` for a credential-bearing request: redirects stay on the request's origin."""
    return _OPENER.open(request, *args, **kwargs)
