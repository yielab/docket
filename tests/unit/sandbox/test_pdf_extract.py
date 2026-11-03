"""The PDF extractor's limits: the address-space limit is best effort, the CPU limit is not."""

from __future__ import annotations

import resource
from types import SimpleNamespace

import pytest

from docket.sandbox import pdf_extract

SUBJECT = "docket.sandbox.pdf_extract"


def _resource(refuse: set[int]) -> SimpleNamespace:
    """A ``resource`` module whose ``setrlimit`` refuses the limits in *refuse*, as macOS may."""
    seen: list[int] = []

    def setrlimit(which: int, _value: tuple[int, int]) -> None:
        if which in refuse:
            raise ValueError("current limit exceeds maximum limit")
        seen.append(which)

    return SimpleNamespace(
        RLIMIT_AS=resource.RLIMIT_AS,
        RLIMIT_CPU=resource.RLIMIT_CPU,
        RLIM_INFINITY=resource.RLIM_INFINITY,
        getrlimit=lambda _which: (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
        setrlimit=setrlimit,
        seen=seen,
    )


def test_a_refused_address_space_limit_is_skipped_and_the_cpu_limit_still_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _resource({resource.RLIMIT_AS})
    monkeypatch.setattr(pdf_extract, "resource", fake)

    assert pdf_extract._apply_limits() is None
    assert fake.seen == [resource.RLIMIT_CPU]


def test_a_refused_cpu_limit_stops_the_reader_with_one_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_extract, "resource", _resource({resource.RLIMIT_CPU}))

    reason = pdf_extract._apply_limits()

    assert reason is not None and reason.startswith("cannot bound the reader's CPU time")
    assert "\n" not in reason


def test_both_limits_are_set_when_the_host_allows_them(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _resource(set())
    monkeypatch.setattr(pdf_extract, "resource", fake)

    assert pdf_extract._apply_limits() is None
    assert fake.seen == [resource.RLIMIT_AS, resource.RLIMIT_CPU]
