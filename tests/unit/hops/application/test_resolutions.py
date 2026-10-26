"""``hops.application.resolutions`` -- the route an answer to an ``input`` step follows and the
synthetic hop that records it. Applying a resolution to a claimed task is
``tests/integration/hops/test_claim_applies_resolution.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from docket.hops.application import resolutions as _resolutions

SUBJECT = "docket.hops.application.resolutions"

_INDEX = {"lead": 0, "ask": 1, "implementer": 2}


def _route(on: dict[str, Any] | None, label: str, counts: dict[tuple[str, str], int] | None = None):
    return _resolutions.resolve_route(on, label, counts or {}, _INDEX, "ask", 1)


class TestResolveRoute:
    def test_no_route_for_the_label_is_an_ordinary_advance(self) -> None:
        assert _route(None, "answered") == (None, "")
        assert _route({"declined": "stop"}, "answered") == (None, "")

    @pytest.mark.parametrize(
        ("target", "terminal"), [("stop", "done"), ("fail", "failed"), ("nowhere", "failed")]
    )
    def test_a_terminal_or_unknown_target_ends_the_task(self, target: str, terminal: str) -> None:
        assert _route({"answered": target}, "answered") == (None, terminal)

    def test_a_forward_step_is_the_next_step(self) -> None:
        assert _route({"answered": "implementer"}, "answered") == ("implementer", "")

    def test_a_backward_route_is_capped_at_one_cycle_by_default(self) -> None:
        on = {"declined": {"goto": "lead"}}

        assert _route(on, "declined") == ("lead", "")
        assert _route(on, "declined", {("ask", "declined"): 1}) == (None, "failed")

    def test_a_backward_route_honours_its_own_max(self) -> None:
        on = {"declined": {"goto": "lead", "max": 2}}

        assert _route(on, "declined", {("ask", "declined"): 1}) == ("lead", "")
        assert _route(on, "declined", {("ask", "declined"): 2}) == (None, "failed")


class TestRoutedHop:
    def test_it_is_an_operator_hop_keyed_by_the_outcome_label(self) -> None:
        hop = _resolutions.routed_hop("ask", "q-1", "declined", "lead")

        assert (hop.role, hop.member_id, hop.step_id, hop.next_step) == (
            "operator",
            "operator",
            "ask",
            "lead",
        )
        assert hop.ok and hop.output == "answered: q-1"
        assert hop.artifact is not None and hop.artifact.verdict == "declined"
