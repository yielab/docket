"""``core.document_fields`` -- the field checks the provider, exporter and channel documents share."""

from __future__ import annotations

import pytest

from docket.kernel import document_fields as documents
from docket.kernel.errors import InvalidInput

SUBJECT = "docket.kernel.document_fields"


def test_a_valid_name_passes_and_an_invalid_one_names_what_it_was() -> None:
    assert documents.check_name("my-exporter2", "exporter") == "my-exporter2"
    for bad in ("", "-x", "Upper", "a_b"):
        with pytest.raises(InvalidInput, match="not a valid exporter name"):
            documents.check_name(bad, "exporter")


def test_only_http_and_https_urls_pass() -> None:
    assert documents.check_http_url("https://example.test/v1") == "https://example.test/v1"
    assert documents.check_http_url("http://127.0.0.1:9/v1")
    with pytest.raises(InvalidInput, match="http:// or https://"):
        documents.check_http_url("ftp://example.test")


def test_a_credential_name_passes_and_a_pasted_value_gets_its_own_refusal() -> None:
    assert documents.check_credential_name("OPENAI_API_KEY", "secret") == "OPENAI_API_KEY"
    with pytest.raises(
        InvalidInput, match=r"looks like a credential VALUE.*'secret' names a stored secret"
    ):
        documents.check_credential_name("sk-abcdefghijklmnopqrstuvwxyz", "'secret'")
    with pytest.raises(InvalidInput, match="not a valid credential name"):
        documents.check_credential_name("lower", "'secret'")


def test_custom_headers_pass_and_reserved_ones_are_refused_whatever_their_case() -> None:
    value = {"X-Org": "acme"}
    assert documents.reject_reserved_headers(value) is value
    for name in ("Authorization", " content-type ", "ACCEPT"):
        with pytest.raises(InvalidInput, match="reserved header name"):
            documents.reject_reserved_headers({name: "x"})
