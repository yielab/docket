"""Same-origin redirect handler for credential-bearing requests (`platform/redirects.py`)."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from docket.platform import redirects as _redirects

SUBJECT = "docket.platform.redirects"

_ORIGIN = "https://api.example.test:8443/v1/models"


def _redirect(newurl: str) -> urllib.request.Request | None:
    request = urllib.request.Request(_ORIGIN, headers={"Authorization": "Bearer k"})
    return _redirects.SameOriginRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, newurl
    )


@pytest.mark.parametrize(
    "newurl",
    [
        "https://other.example.test:8443/v1/models",
        "https://api.example.test:9443/v1/models",
        "http://api.example.test:8443/v1/models",
        "https://api.example.test.evil.test:8443/v1/models",
    ],
)
def test_refuses_a_redirect_off_the_origin(newurl: str) -> None:
    """A redirect that changes the host, port or scheme is refused."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        _redirect(newurl)
    assert caught.value.code == 302
    assert "not the origin" in str(caught.value.msg)


def test_follows_a_redirect_on_the_same_origin_and_keeps_the_header() -> None:
    """A same-origin redirect is followed and the credential header rides along."""
    followed = _redirect("https://api.example.test:8443/v1/models-moved")
    assert followed is not None
    assert followed.full_url == "https://api.example.test:8443/v1/models-moved"
    assert followed.get_header("Authorization") == "Bearer k"


def test_explicit_default_port_is_the_same_origin() -> None:
    """An explicit default port equals the implicit one, so the origin stays followable."""
    request = urllib.request.Request("https://api.example.test/v1/models")
    followed = _redirects.SameOriginRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, "https://api.example.test:443/v1/models-moved"
    )
    assert followed is not None
