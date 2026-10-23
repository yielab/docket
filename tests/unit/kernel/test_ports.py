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


def test_the_object_callers_import_forwards_to_the_adapter_of_the_moment() -> None:
    first, second = FakeProcess(env={"DOCKET_NO_TRACE": "1"}), FakeProcess()
    with process_port.use(first):
        assert process.no_trace() is True
        with process_port.use(second):
            assert process.no_trace() is False
        assert process.no_trace() is True
