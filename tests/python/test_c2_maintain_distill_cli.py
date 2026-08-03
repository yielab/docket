"""ROADMAP Phase 17 C-2: `docket maintain` distillation wiring.

Covers `cli/_agents.py`'s side of the card -- `docket maintain <id> distill`,
and `clean`/`reset` gaining a `--distill-first` default (with
`--no-distill-first` as the explicit opt-out) so neither command bare-deletes
undistilled memory. Calls `run_maintain` directly (the same pattern
test_w7_provisioning.py uses for `run_add`) with `sys.stdin.isatty`/
`builtins.input` monkeypatched for the confirm prompt, and
`edges.adapters.docket_runtime.default_driver` monkeypatched to return
`tests/python/fakes.py`'s `FakeDriver` -- no live daemon, no `openclaw`
binary, anywhere in this file. (Phase 19 P19-7a repointed `cli/_agents.py`'s
`_run_distillation` at `docket_runtime.default_driver`, not the ACL's; this
file's monkeypatch target moved with it.)

A hermetic no-fake, no-daemon proof (the real `OpenClawDriver` failing
because `openclaw` isn't on PATH) lives in test_m4_final.py's
`TestCmdMaintain` class, alongside the rest of `docket maintain`'s
subprocess-level coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _agents
from docket.core import memory as _mem
from docket.edges.adapters import docket_runtime as _dr

from .fakes import FakeDriver

# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str = "demo") -> Path:
    oc_dir = tmp_path / ".openclaw"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    ws = _cfg.PROJECTS_DIR / agent_id
    (ws / "memory").mkdir(parents=True)
    meta = {
        "schemaVersion": 1,
        "kind": "project",
        "name": "Demo Agent",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": f"agent:{agent_id}:default",
        "projectKey": "default",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ws / "HEARTBEAT.md").write_text(_mem.heartbeat_seed("Demo Agent"), encoding="utf-8")
    return ws


def _confirm_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_agents.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "y")


def _use_fake_driver(monkeypatch: pytest.MonkeyPatch, fake: FakeDriver) -> None:
    monkeypatch.setattr(_dr, "default_driver", lambda: fake)


# ── docket maintain <id> distill ────────────────────────────────────────────


class TestMaintainDistillCommand:
    def test_success_archives_logs_and_updates_memory_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)

        rc = _agents.run_maintain("demo", "distill")

        assert rc == 0
        assert not log.exists()
        assert (ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).is_dir()
        assert "Distilled" in (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert len(fake.calls) == 1

    def test_failure_leaves_logs_untouched_and_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver(fail_role="demo", error="boom", failure_kind="daemon_error")
        _use_fake_driver(monkeypatch, fake)

        rc = _agents.run_maintain("demo", "distill")

        assert rc == 1
        assert log.exists()
        assert not (ws / "MEMORY.md").exists()

    def test_failure_reports_the_failure_kind_to_the_operator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A blocked delete has to say *why* it was blocked.

        C-2's fail-closed contract turns a failed distillation into a refused
        deletion, so the operator's next move depends on the kind: `timeout`
        and `daemon_error` mean retry, `invalid_output` means the model
        returned something unusable and a retry will probably repeat it.
        `DistillResult.failure_kind` carried that classification from the
        driver since C-2 shipped, but nothing rendered it (CL-3 flagged it as
        populated-but-unread) -- so the operator saw only the raw error string.
        """
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "memory" / "2026-07-01.md").write_text("notes\n", encoding="utf-8")
        fake = FakeDriver(fail_role="demo", error="model returned prose", failure_kind="timeout")
        _use_fake_driver(monkeypatch, fake)

        rc = _agents.run_maintain("demo", "distill")

        assert rc == 1
        captured = capsys.readouterr()
        shown = captured.out + captured.err
        assert "timeout" in shown, "the failure kind must reach the operator"
        assert "nothing deleted" in shown

    def test_nothing_pending_is_a_clean_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_ws(tmp_path, monkeypatch)
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)

        rc = _agents.run_maintain("demo", "distill")

        assert rc == 0
        assert fake.calls == []

    def test_unknown_agent_is_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)

        rc = _agents.run_maintain("nonexistent", "distill")

        assert rc == 1


# ── docket maintain <id> clean --distill-first ──────────────────────────────


class TestMaintainCleanDistillFirst:
    def test_default_distills_before_deleting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "clean")

        assert rc == 0
        assert len(fake.calls) == 1  # distillation ran
        assert not log.exists()
        archived = list((ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).rglob("*.md"))
        assert len(archived) == 1  # moved, not bare-deleted

    def test_failed_distillation_blocks_the_delete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver(fail_role="demo", error="boom", failure_kind="daemon_error")
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "clean")

        assert rc == 1
        assert log.exists()  # never deleted -- fail closed

    def test_no_distill_first_skips_the_driver_and_deletes_directly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "clean", ["--no-distill-first"])

        assert rc == 0
        assert fake.calls == []  # never invoked
        assert not log.exists()
        assert not (ws / "memory" / _mem.DISTILLED_ARCHIVE_DIRNAME).exists()

    def test_non_interactive_still_cancels_before_any_distillation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)
        monkeypatch.setattr(_agents.sys.stdin, "isatty", lambda: False)

        rc = _agents.run_maintain("demo", "clean")

        assert rc == 0
        assert fake.calls == []
        assert log.exists()


# ── docket maintain <id> reset --distill-first ──────────────────────────────


class TestMaintainResetDistillFirst:
    def test_default_preserves_the_freshly_distilled_memory_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\n## Old\nkeep this\n", encoding="utf-8")
        (ws / "memory" / "2026-07-01.md").write_text("notes\n", encoding="utf-8")
        (ws / "HEARTBEAT.md").write_text(
            "# HEARTBEAT.md\n\n## Active Tasks\n- [ ] a real task\n", encoding="utf-8"
        )
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "reset")

        assert rc == 0
        mem_text = (ws / "MEMORY.md").read_text(encoding="utf-8")
        # Distillation just refreshed MEMORY.md -- reset must not wipe it
        # again in the same breath, or --distill-first preserves nothing.
        assert "keep this" in mem_text
        assert "Distilled" in mem_text
        # HEARTBEAT.md is still reset regardless.
        hb_text = (ws / "HEARTBEAT.md").read_text(encoding="utf-8")
        assert "a real task" not in hb_text
        assert "_none yet_" in hb_text

    def test_failed_distillation_blocks_the_whole_reset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\nkeep this\n", encoding="utf-8")
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        (ws / "HEARTBEAT.md").write_text(
            "# HEARTBEAT.md\n\n## Active Tasks\n- [ ] a real task\n", encoding="utf-8"
        )
        fake = FakeDriver(fail_role="demo", error="boom", failure_kind="daemon_error")
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "reset")

        assert rc == 1
        assert log.exists()
        assert "keep this" in (ws / "MEMORY.md").read_text(encoding="utf-8")
        assert "a real task" in (ws / "HEARTBEAT.md").read_text(encoding="utf-8")

    def test_no_distill_first_matches_pre_c2_behavior(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = _make_ws(tmp_path, monkeypatch)
        (ws / "MEMORY.md").write_text("# MEMORY.md\n\nkeep this\n", encoding="utf-8")
        log = ws / "memory" / "2026-07-01.md"
        log.write_text("notes\n", encoding="utf-8")
        fake = FakeDriver()
        _use_fake_driver(monkeypatch, fake)
        _confirm_yes(monkeypatch)

        rc = _agents.run_maintain("demo", "reset", ["--no-distill-first"])

        assert rc == 0
        assert fake.calls == []
        assert not log.exists()
        assert (ws / "MEMORY.md").read_text(
            encoding="utf-8"
        ) == "# MEMORY.md\n\n_Cleared by docket maintain reset._\n"
