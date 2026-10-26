"""``kernel.errors`` -- one root to catch, builtin compatibility kept, one document error shape."""

from __future__ import annotations

import pytest

from docket.kernel.errors import (
    Conflict,
    DocketError,
    DocumentError,
    InvalidInput,
    NotFound,
    Refused,
    Unavailable,
)

SUBJECT = "docket.kernel.errors"

_KINDS = (InvalidInput, NotFound, Conflict, Refused, Unavailable)


@pytest.mark.parametrize("kind", _KINDS)
def test_every_kind_is_caught_at_the_root(kind: type[DocketError]) -> None:
    with pytest.raises(DocketError) as caught:
        raise kind("pod is full", "free a slot")
    assert str(caught.value) == "pod is full"
    assert caught.value.message == "pod is full"
    assert caught.value.hint == "free a slot"


def test_the_hint_is_optional() -> None:
    assert DocketError("no").hint == ""


def test_builtin_catches_keep_working() -> None:
    with pytest.raises(ValueError, match="bad"):
        raise InvalidInput("bad")
    with pytest.raises(LookupError, match="gone"):
        raise NotFound("gone")


def test_kinds_do_not_catch_each_other() -> None:
    for kind in _KINDS:
        others = tuple(k for k in _KINDS if k is not kind)
        assert not issubclass(kind, others)


def test_a_document_error_names_file_field_and_reason() -> None:
    err = DocumentError("p.yaml", "auth.type", "unknown")
    assert str(err) == "p.yaml: auth.type: unknown"
    assert err.message == "unknown"
    assert err.args == ("p.yaml: auth.type: unknown",)


def test_a_document_error_lists_the_accepted_values() -> None:
    err = DocumentError("p.yaml", "dialect", "unknown", ("openai", "anthropic"))
    assert str(err) == "p.yaml: dialect: unknown (valid: openai, anthropic)"


def test_a_document_error_is_invalid_input() -> None:
    assert issubclass(DocumentError, (InvalidInput, ValueError))
