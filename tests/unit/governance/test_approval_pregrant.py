"""The gated tool registry, its chokepoint, and the built-in tools (`agent/tools/registry.py`).

Pins the argument-aware command classifier (`git push origin production`
reads as a deploy, not a benign `git`), that a source-tree walk finds
exactly one path to tool execution through `dispatch_tool`, and that
containment holds at the handler as well as at the chokepoint.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _approval_pregrant
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.governance.approval_pregrant"


@pytest.fixture(autouse=True)
def _isolate_gates(tmp_path: Path) -> Iterator[None]:
    """Isolate `governance/policy.py` and `governance/approval.py`'s real stores from a
    developer's ``~/.docket``, and set the approval timeout to 0 so a gated
    call nothing grants resolves immediately (fail-closed to denied)."""
    with use_home(
        dataclasses.replace(
            current_home(),
            policies_dir_override=tmp_path / "_policies",
            approvals_dir_override=tmp_path / "_approvals",
            tool_approval_timeout=0,
        )
    ):
        yield


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def approvals_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "approvals"
    d.mkdir()
    with use_home(dataclasses.replace(current_home(), approvals_dir_override=d)):
        yield d


class TestPreGrants:
    def test_create_pregrant_is_born_granted(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj", "implementer", "bash", "deadbeef", channel="cli", actor="ops"
        )
        record = _approval.approval_get(token)
        assert record["state"] == "granted"
        assert record["context"] == {
            "kind": "pregrant",
            "tool": "bash",
            "argsDigest": "deadbeef",
        }

    def test_create_pregrant_rejects_an_unknown_channel(self, approvals_dir: Path) -> None:
        with pytest.raises(_approval.ApprovalError):
            _approval_pregrant.create_pregrant(
                "proj", "implementer", "bash", "deadbeef", channel="carrier-pigeon"
            )

    def test_consume_pregrant_spends_it_exactly_once(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj", "implementer", "bash", "deadbeef", channel="cli"
        )
        assert _approval_pregrant.consume_pregrant(token) is True
        assert _approval.approval_get(token)["consumedAt"]
        assert _approval_pregrant.consume_pregrant(token) is False

    def test_consume_pregrant_refuses_an_unknown_token(self, approvals_dir: Path) -> None:
        assert _approval_pregrant.consume_pregrant("apr-does-not-exist") is False

    def test_consume_pregrant_refuses_one_past_its_expiry(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj",
            "implementer",
            "bash",
            "deadbeef",
            channel="cli",
            expires_at="2000-01-01T00:00:00Z",
        )
        assert _approval_pregrant.consume_pregrant(token) is False
        assert "consumedAt" not in _approval.approval_get(token)

    def test_sweep_prunes_an_unconsumed_pregrant_past_its_expiry(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj",
            "implementer",
            "bash",
            "deadbeef",
            channel="cli",
            expires_at="2000-01-01T00:00:00Z",
        )
        swept = _approval.approval_sweep_expired()
        assert swept == 1
        assert _approval.approval_get(token)["state"] == "denied"
        assert _approval_pregrant.consume_pregrant(token) is False

    def test_sweep_leaves_an_unexpired_pregrant_alone(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj", "implementer", "bash", "deadbeef", channel="cli"
        )
        swept = _approval.approval_sweep_expired()
        assert swept == 0
        assert _approval.approval_get(token)["state"] == "granted"

    def test_sweep_leaves_an_already_consumed_pregrant_alone(self, approvals_dir: Path) -> None:
        token = _approval_pregrant.create_pregrant(
            "proj", "implementer", "bash", "deadbeef", channel="cli"
        )
        assert _approval_pregrant.consume_pregrant(token) is True
        swept = _approval.approval_sweep_expired()
        assert swept == 0
        assert _approval.approval_get(token)["state"] == "granted"
