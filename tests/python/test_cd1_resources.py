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
from docket.edges.adapters import openclaw as _oc

# ── hermetic helpers ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "PORT_ALLOC_FILE", oc_dir / "port-allocations.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    def _unregister(agent_id: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw["agents"]["list"] = [a for a in raw["agents"]["list"] if a["id"] != agent_id]
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)
    monkeypatch.setattr(_oc, "unregister_agent_cli", _unregister)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    return oc_dir


def _meta(oc_dir: Path, member_id: str) -> dict:  # type: ignore[type-arg]
    p = oc_dir / "workspaces" / "projects" / member_id / ".docket-meta.json"
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
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        meta = _meta(oc_dir, "demo-implementer")
        assert meta["portRangeStart"] == _res.PORT_BASE
        assert meta["portRangeCount"] == _res.PORT_RANGE_SIZE
        assert "scratchDir" in meta
        assert meta["scratchDir"]  # non-empty

    def test_lead_does_not_get_port_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(oc_dir, "demo-lead")
        assert "portRangeStart" not in meta
        assert "scratchDir" not in meta

    def test_implementer_tools_md_contains_port_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        tools_path = oc_dir / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md"
        assert tools_path.exists(), "TOOLS.md should be written for the implementer"
        content = tools_path.read_text()
        assert "DOCKET_PORT_BASE" in content
        assert "DOCKET_SCRATCH_DIR" in content
        assert str(_res.PORT_BASE) in content

    def test_lead_has_no_tools_md(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        tools_path = oc_dir / "workspaces" / "projects" / "demo-lead" / "TOOLS.md"
        assert not tools_path.exists()

    def test_two_pods_get_disjoint_port_ranges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES)
        _pod.build_pod("beta", _pod.pod.DEFAULT_POD_ROLES)
        meta_a = _meta(oc_dir, "alpha-implementer")
        meta_b = _meta(oc_dir, "beta-implementer")
        start_a = meta_a["portRangeStart"]
        count_a = meta_a["portRangeCount"]
        start_b = meta_b["portRangeStart"]
        count_b = meta_b["portRangeCount"]
        range_a = set(range(start_a, start_a + count_a))
        range_b = set(range(start_b, start_b + count_b))
        assert not (range_a & range_b), "port ranges overlap between pods"

    def test_scratch_dir_is_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(oc_dir, "demo-implementer")
        scratch = Path(meta["scratchDir"])
        assert scratch.is_dir(), "scratch dir must exist after provisioning"

    def test_two_pods_get_distinct_scratch_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES)
        _pod.build_pod("beta", _pod.pod.DEFAULT_POD_ROLES)
        scratch_a = _meta(oc_dir, "alpha-implementer")["scratchDir"]
        scratch_b = _meta(oc_dir, "beta-implementer")["scratchDir"]
        assert scratch_a != scratch_b

    def test_pod_delete_frees_port_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        # Free the port range by simulating pod teardown.
        _pod.free_pod_resources("demo")
        # Re-provisioning the same project should get PORT_BASE (reused slot).
        _pod.build_pod("demo2", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(oc_dir, "demo2-implementer")
        assert meta["portRangeStart"] == _res.PORT_BASE

    def test_pod_delete_removes_scratch_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        meta = _meta(oc_dir, "demo-implementer")
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
