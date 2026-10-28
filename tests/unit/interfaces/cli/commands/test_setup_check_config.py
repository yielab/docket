"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.home import point_config_at as _point_config_at
from tests.support.pods import build_pod

from docket.interfaces.cli.commands import setup_check_config as _setup_check_config
from docket.kernel.home import current_home

SUBJECT = "docket.interfaces.cli.commands.setup_check_config"


class TestPodConfigOverlays:
    """A malformed pod-scoped role overlay or policy file is named with the pod, not
    silently skipped -- the pod-scoped counterpart of `TestArchetypeOverlay`/
    `TestGuardrailPolicies`, which only ever look at the global files."""

    @contextmanager
    def _build_pod(
        self,
        tmp_path: Path,
    ) -> Iterator[Path]:
        from docket.interfaces.cli.commands import pod as _pod

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with _point_config_at(home):
            build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
            yield home

    def test_no_pods_is_healthy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _point_config_at(tmp_path / ".docket"):
            assert _setup_check_config._check_pod_config_overlays() == 0

    def test_pod_with_no_overlay_is_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._build_pod(tmp_path):
            assert _setup_check_config._check_pod_config_overlays() == 0

    def test_broken_pod_role_overlay_is_named_by_pod(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._build_pod(tmp_path):
            broken = current_home().pod_config_dir("demo") / "roles" / "broken-role.yaml"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("kind: role\nname: broken-role\nmodel: huge\n")
            issues = _setup_check_config._check_pod_config_overlays()
            out = capsys.readouterr().out
            assert issues == 1
            assert "demo" in out
            assert "broken-role" in out

    def test_broken_pod_policy_file_is_named_by_pod(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._build_pod(tmp_path):
            pod_policies = current_home().pod_config_dir("demo") / "policies"
            pod_policies.mkdir(parents=True, exist_ok=True)
            (pod_policies / "zz-broken.json").write_text('{"id": "zz", not json')
            issues = _setup_check_config._check_pod_config_overlays()
            out = capsys.readouterr().out
            assert issues == 1
            assert "demo" in out
            assert "zz-broken.json" in out


class TestPodSyncCheck:
    """`_check_pod_sync` -- the pod-member counterpart of `_check_template_version`,
    which explicitly skips pod members (they use their own template scheme)."""

    @contextmanager
    def _build_pod(
        self,
        tmp_path: Path,
    ) -> Iterator[Path]:
        from docket.interfaces.cli.commands import pod as _pod

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with _point_config_at(home):
            build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
            yield home

    def test_in_sync_pod_reports_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._build_pod(tmp_path):
            issues = _setup_check_config._check_pod_sync(["demo-lead", "demo-implementer"])
            out = capsys.readouterr().out
            assert issues == 0
            assert "✗" not in out
            assert "in sync" in out

    def test_stale_pod_member_is_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._build_pod(tmp_path) as home:
            (home / "workspaces" / "projects" / "demo-lead" / "SOUL.md").write_text(
                "STALE-HAND-EDITED-SOUL\n"
            )
            issues = _setup_check_config._check_pod_sync(["demo-lead", "demo-implementer"])
            out = capsys.readouterr().out
            assert "✗" in out
            assert "demo-lead" in out
            assert "docket pod update" in out
            # Advisory only, same as `_check_template_version`.
            assert issues == 0

    def test_non_pod_agents_are_skipped(self) -> None:
        assert _setup_check_config._check_pod_sync([]) == 0
