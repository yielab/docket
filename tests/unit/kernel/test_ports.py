"""``kernel.ports`` -- a port forwards to the adapter bound at call time, and a block can swap it."""

from __future__ import annotations

import pytest
from tests.support.fakes import FakeProcess

from docket.kernel.ports import Binding, PortNotBound, process, process_port

SUBJECT = "docket.kernel.ports"


def test_a_binding_with_no_adapter_names_what_to_call() -> None:
    with pytest.raises(PortNotBound, match="no adapter"):
        Binding[object]("nothing").current()


def test_a_bound_adapter_is_the_default_and_a_block_overrides_it_then_restores_it() -> None:
    binding: Binding[str] = Binding("text")
    binding.bind("real")
    assert binding.current() == "real"
    with binding.use("fake"):
        assert binding.current() == "fake"
        with binding.use("inner"):
            assert binding.current() == "inner"
        assert binding.current() == "fake"
    assert binding.current() == "real"


def test_blocks_closed_out_of_order_leave_no_override_behind() -> None:
    """A fixture's block can outlive the block a test opened after it; the later close must not
    bring back the earlier adapter, or every following test runs on a fake."""
    binding: Binding[str] = Binding("text")
    binding.bind("real")
    outer, inner = binding.use("outer"), binding.use("inner")
    outer.__enter__()
    inner.__enter__()
    outer.__exit__(None, None, None)
    assert binding.current() == "inner"
    inner.__exit__(None, None, None)
    assert binding.current() == "real"


def test_the_object_callers_import_refuses_an_assignment() -> None:
    """``monkeypatch.setattr`` on it would leave the real adapter's method stuck on the proxy."""
    with pytest.raises(AttributeError, match="swap the adapter"):
        process.no_trace = lambda: True  # type: ignore[method-assign]


def test_the_object_callers_import_forwards_to_the_adapter_of_the_moment() -> None:
    first, second = FakeProcess(env={"DOCKET_NO_TRACE": "1"}), FakeProcess()
    with process_port.use(first):
        assert process.no_trace() is True
        with process_port.use(second):
            assert process.no_trace() is False
        assert process.no_trace() is True
