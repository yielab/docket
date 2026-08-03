"""CD-1: pod runtime-resource isolation — pure logic + integration tests.

Two layers:
  * TestPortAllocation — pure logic tests for core/resources.py (no I/O).
  * TestPodResources   — hermetic integration tests: build_pod allocates
    resources, TOOLS.md is written, two pods get disjoint ranges, teardown
    reclaims the range and scratch dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import resources as _res

# ── hermetic helpers ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "PORT_ALLOC_FILE", home / "port-allocations.json", raising=True)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    return home


def _meta(home: Path, member_id: str) -> dict:  # type: ignore[type-arg]
    p = home / "workspaces" / "projects" / member_id / ".docket-meta.json"
    return json.loads(p.read_text())


# ── pure logic ───────────────────────────────────────────────────────────────


class TestPortAllocation:
    def test_empty_table_gets_port_base(self) -> None:
        start, count, updated = _res.allocate_pod_ports("demo", {})
        assert start == _res.PORT_BASE
        assert count == _res.PORT_RANGE_SIZE
        assert updated["allocations"]["demo"] == _res.PORT_BASE

    def test_second_pod_gets_non_overlapping_range(self) -> None:
        _, _, t1 = _res.allocate_pod_ports("a", {})
        start2, _, _ = _res.allocate_pod_ports("b", t1)
        assert start2 == _res.PORT_BASE + _res.PORT_RANGE_SIZE

    def test_three_pods_all_disjoint(self) -> None:
        _, _, t1 = _res.allocate_pod_ports("a", {})
        _, _, t2 = _res.allocate_pod_ports("b", t1)
        start3, count3, _ = _res.allocate_pod_ports("c", t2)
        assert start3 == _res.PORT_BASE + 2 * _res.PORT_RANGE_SIZE
        # Ranges must not overlap.
        ranges = [
            range(_res.PORT_BASE, _res.PORT_BASE + count3),
            range(_res.PORT_BASE + count3, _res.PORT_BASE + 2 * count3),
            range(start3, start3 + count3),
        ]
        for i, r1 in enumerate(ranges):
            for r2 in ranges[i + 1 :]:
                assert not (set(r1) & set(r2)), "port ranges overlap"

    def test_idempotent_same_project_returns_same_range(self) -> None:
        start1, _, t1 = _res.allocate_pod_ports("demo", {})
        start2, _, t2 = _res.allocate_pod_ports("demo", t1)
        assert start1 == start2
        assert t2 is t1  # table object unchanged

    def test_freed_range_is_reused(self) -> None:
        _, _, t1 = _res.allocate_pod_ports("a", {})
        _, _, t2 = _res.allocate_pod_ports("b", t1)
        # Free 'a'; a new pod should reuse the PORT_BASE slot.
        t3 = _res.free_pod_ports("a", t2)
        start_c, _, _ = _res.allocate_pod_ports("c", t3)
        assert start_c == _res.PORT_BASE

    def test_free_idempotent_on_unknown_project(self) -> None:
        table: dict[str, object] = {"allocations": {"x": 3000}}
        result = _res.free_pod_ports("nonexistent", table)
        assert result["allocations"] == {"x": 3000}

    def test_free_removes_only_the_named_project(self) -> None:
        _, _, t = _res.allocate_pod_ports("a", {})
        _, _, t = _res.allocate_pod_ports("b", t)
        t = _res.free_pod_ports("a", t)
        assert "a" not in t["allocations"]
        assert "b" in t["allocations"]


# ── integration ──────────────────────────────────────────────────────────────


class TestPodResources:
    def test_build_pod_allocates_resources_for_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        meta = _meta(home, "demo-implementer")
        assert meta["portRangeStart"] == _res.PORT_BASE
        assert meta["portRangeCount"] == _res.PORT_RANGE_SIZE
        assert "scratchDir" in meta
        assert meta["scratchDir"]  # non-empty

    def test_lead_does_not_get_port_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(home, "demo-lead")
        assert "portRangeStart" not in meta
        assert "scratchDir" not in meta

    def test_implementer_tools_md_contains_port_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        tools_path = home / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md"
        assert tools_path.exists(), "TOOLS.md should be written for the implementer"
        content = tools_path.read_text()
        assert "DOCKET_PORT_BASE" in content
        assert "DOCKET_SCRATCH_DIR" in content
        assert str(_res.PORT_BASE) in content

    def test_lead_has_no_tools_md(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        tools_path = home / "workspaces" / "projects" / "demo-lead" / "TOOLS.md"
        assert not tools_path.exists()

    def test_two_pods_get_disjoint_port_ranges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES)
        _pod.build_pod("beta", _pod.pod.DEFAULT_POD_ROLES)
        meta_a = _meta(home, "alpha-implementer")
        meta_b = _meta(home, "beta-implementer")
        start_a = meta_a["portRangeStart"]
        count_a = meta_a["portRangeCount"]
        start_b = meta_b["portRangeStart"]
        count_b = meta_b["portRangeCount"]
        range_a = set(range(start_a, start_a + count_a))
        range_b = set(range(start_b, start_b + count_b))
        assert not (range_a & range_b), "port ranges overlap between pods"

    def test_scratch_dir_is_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(home, "demo-implementer")
        scratch = Path(meta["scratchDir"])
        assert scratch.is_dir(), "scratch dir must exist after provisioning"

    def test_two_pods_get_distinct_scratch_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES)
        _pod.build_pod("beta", _pod.pod.DEFAULT_POD_ROLES)
        scratch_a = _meta(home, "alpha-implementer")["scratchDir"]
        scratch_b = _meta(home, "beta-implementer")["scratchDir"]
        assert scratch_a != scratch_b

    def test_pod_delete_frees_port_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        # Free the port range by simulating pod teardown.
        _pod.free_pod_resources("demo")
        # Re-provisioning the same project should get PORT_BASE (reused slot).
        _pod.build_pod("demo2", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(home, "demo2-implementer")
        assert meta["portRangeStart"] == _res.PORT_BASE

    def test_pod_delete_removes_scratch_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(home, "demo-implementer")
        scratch = Path(meta["scratchDir"])
        assert scratch.is_dir()
        _pod.free_pod_resources("demo")
        assert not scratch.exists(), "scratch dir must be removed on pod teardown"

    def test_free_pod_resources_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # Calling free on a pod that never existed is safe.
        _pod.free_pod_resources("nonexistent")
