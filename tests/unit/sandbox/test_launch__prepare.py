"""How ``dispatch_pod`` hands a claimed task to ``hops.workspace.prepare``: skips, the jail, the refusal."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.fakes import FakeJail

from docket.hops.application import isolation_posture as _isolation_posture
from docket.hops.gates import post_hop as _post_hop
from docket.hops.workspace import prepare as _prepare
from docket.kernel.ports import JailPolicy
from docket.tasks.application import queue as _queue

SUBJECT = "docket.sandbox.launch"


def test_the_install_opens_the_network_for_its_own_launch_only(
    monkeypatch: pytest.MonkeyPatch,
    fake_jail: FakeJail,
) -> None:
    pods_jail = JailPolicy(network=False)
    monkeypatch.setattr(
        _isolation_posture, "resolve_command_jail", lambda project, label: (pods_jail, None)
    )
    seen: list[JailPolicy] = []
    fake_jail.run_command = lambda *a, **k: seen.append(k["jail"]) or (0, "")
    _queue._run_prepare_command("demo", "npm ci", "/wt")
    assert [j.network for j in seen] == [True] and pods_jail.network is False


def test_a_gate_in_the_jail_reads_the_cache_entry_its_worktree_links_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_jail: FakeJail
) -> None:
    entry = tmp_path / "entry"
    monkeypatch.setattr(_prepare, "linked_entries", lambda root: (entry,))
    monkeypatch.setattr(
        _isolation_posture,
        "resolve_command_jail",
        lambda project, label: (JailPolicy(), None),
    )
    seen: list[JailPolicy] = []
    fake_jail.run_command = lambda *a, **k: seen.append(k["jail"]) or (0, "")
    _post_hop._run_in_envelope("demo", "verify", "npx eslint", str(tmp_path), 60)
    assert seen[0].read_only == (entry,)
