"""A hop's read-only roots: the pod's machine grants plus the install entries its root links into."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.hops.application import isolation_posture as _isolation_posture
from docket.hops.workspace import prepare as _prepare
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.hops.application.isolation_posture"


def test_a_hop_reads_its_pods_grants_and_the_entries_its_root_links_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grant, entry = tmp_path / "node", tmp_path / "entry"
    monkeypatch.setattr(_pod_settings, "effective_read_only", lambda project: (grant,))
    monkeypatch.setattr(_prepare, "linked_entries", lambda root: (entry,))
    assert _isolation_posture._hop_read_only("demo", tmp_path) == (grant, entry)


def test_a_root_that_links_nowhere_adds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_pod_settings, "effective_read_only", lambda project: ())
    assert _isolation_posture._hop_read_only("demo", tmp_path) == ()
