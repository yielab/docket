"""Audit v2 — coverage expansion, tamper-evidence chain, kill-switch removal.

Covers:
  - New audit_log() call sites (keys.*, profile.*, scope.*, agent.add/delete,
    persona.*) each write exactly one line with the right dotted-verb action
    and no secret values (pod.add/pod.remove coverage lives in
    test_pod_provisioning.py, which already has the pod-daemon fixtures).
  - The hash chain (seq + prev_hash, GENESIS_HASH): verifies clean on a fresh
    log, detects a hand-tampered middle line at the point the chain actually
    breaks, tolerates pre-chain legacy lines and malformed JSON without
    crashing the viewer or verifier, and documents (rather than bridges) a
    rotation boundary.
  - `docket audit verify` (cli/_audit.py's run_audit_verify).

Every fixture repoints ``_cfg.AUDIT_LOG`` explicitly — the conftest-wide
``_isolate_audit_log`` autouse fixture is a safety net, not a substitute for
tests that need to actually inspect what got written.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket import cli
from docket.cli import _audit as audit_cli
from docket.cli import _keys as keys_cli
from docket.cli._agents import run_delete, run_init
from docket.core import audit as _audit

# ── shared helpers ───────────────────────────────────────────────────────────


def _entries(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e["action"] == action]


def _seed_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aid: str = "demo") -> Path:
    """A minimal, non-pod project agent: workspace + meta + fleet.json entry."""
    home = tmp_path / ".docket"
    ws = home / "workspaces" / "projects" / aid
    ws.mkdir(parents=True)
    meta = {
        "kind": "project",
        "name": "Demo",
        "role": "repo",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": f"agent:{aid}:default",
        "projectKey": "default",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    (home / "fleet.json").write_text(
        json.dumps(
            {
                "agents": [{"id": aid, "model": "anthropic/claude-sonnet-4-6"}],
                "bindings": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)
    return home


def _concurrent_audit_writer(
    start: multiprocessing.synchronize.Barrier,
    results: multiprocessing.queues.Queue[tuple[str, str]],
    action: str,
) -> None:
    """Write one distinct event after every forked worker is ready."""
    start.wait(timeout=15)
    result = _audit.audit_log(action, action)
    # Pre-C6 returns None, which is deliberate RED evidence rather than a
    # worker crash that would hide the concurrent-chain oracle.
    results.put((action, getattr(result, "status", "legacy-none")))


def _hold_audit_lock(
    ready: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
    lock_path: str,
) -> None:
    from filelock import FileLock

    with FileLock(lock_path):
        ready.set()
        release.wait(timeout=15)


@pytest.fixture()
def audit_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bare DOCKET_HOME for exercising core/audit.py directly."""
    d = tmp_path / ".docket"
    d.mkdir()
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    return d


# ── hash chain: core/audit.py ───────────────────────────────────────────────


class TestChainWriting:
    def test_first_entry_is_seq_1_with_genesis_prev_hash(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        entries = _audit.read_audit()
        assert entries[0]["seq"] == 1
        assert entries[0]["prev_hash"] == _audit.GENESIS_HASH

    def test_second_entry_chains_to_the_first(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        entries = _audit.read_audit()
        assert entries[1]["seq"] == 2
        assert entries[1]["prev_hash"] == _audit._hash_entry(entries[0])

    def test_timestamps_are_millisecond_resolution(self, audit_home: Path) -> None:
        _audit.audit_log("keys.add", "A")
        ts = _audit.read_audit()[0]["ts"]
        # YYYY-MM-DDTHH:MM:SS.mmmZ
        assert ts.endswith("Z")
        assert "." in ts
        millis = ts.split(".")[1].rstrip("Z")
        assert len(millis) == 3
        assert millis.isdigit()


class TestAtomicAuditTransition:
    """W26-C6's process-level race and failure/recovery contract."""

    _WRITERS = 32

    def _write_concurrently(
        self, monkeypatch: pytest.MonkeyPatch, prefix: str = "concurrent"
    ) -> list[tuple[str, str]]:
        # ``fork`` retains the monkeypatched config and delayed real head read.
        # The start barrier makes all 32 processes contend; the post-head delay
        # makes the pre-C6 unlocked implementation derive duplicate heads.
        if "fork" not in multiprocessing.get_all_start_methods():
            pytest.skip("audit inter-process lock test requires POSIX fork")
        context = multiprocessing.get_context("fork")
        original_head = _audit._chain_head

        def delayed_head(logf: Path) -> tuple[int, str]:
            head = original_head(logf)
            time.sleep(0.025)
            return head

        monkeypatch.setattr(_audit, "_chain_head", delayed_head)
        start = context.Barrier(self._WRITERS + 1)
        results: multiprocessing.queues.Queue[tuple[str, str]] = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_audit_writer,
                args=(start, results, f"{prefix}.{i:02d}"),
            )
            for i in range(self._WRITERS)
        ]
        for process in processes:
            process.start()
        start.wait(timeout=15)
        received = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        return received

    def test_32_process_writers_below_rotation_are_one_contiguous_chain(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1_000_000, raising=True)

        received = self._write_concurrently(monkeypatch)

        assert {status for _, status in received} == {"written"}
        entries = _audit.read_audit()
        assert {entry["action"] for entry in entries} == {action for action, _ in received}
        assert [entry["seq"] for entry in entries] == list(range(1, self._WRITERS + 1))
        assert _audit.verify_chain().break_at is None

    def test_32_process_writers_across_one_rotation_remain_contiguous(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The seed forces the first contender to rotate, while the new current
        # generation remains comfortably below the cap for every 32 events.
        limit = 20_000
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", limit, raising=True)
        (audit_home / "audit.log").write_text("x" * limit, encoding="utf-8")

        received = self._write_concurrently(monkeypatch, "rotated")

        assert {status for _, status in received} == {"written"}
        entries = _audit.read_audit()
        assert {entry["action"] for entry in entries} == {action for action, _ in received}
        assert [entry["seq"] for entry in entries] == list(range(1, self._WRITERS + 1))
        assert (audit_home / "audit.log.1").exists()
        assert _audit.verify_chain().break_at is None

    def test_lock_timeout_is_failed_without_recording_an_event(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if "fork" not in multiprocessing.get_all_start_methods():
            pytest.skip("audit inter-process lock test requires POSIX fork")
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        holder = context.Process(
            target=_hold_audit_lock,
            args=(ready, release, str(_audit._audit_lock_path(_cfg.AUDIT_LOG))),
        )
        holder.start()
        assert ready.wait(timeout=15)
        monkeypatch.setattr(_audit, "_AUDIT_LOCK_TIMEOUT", 0, raising=False)

        result = _audit.audit_log("keys.add", "LOCKED")

        release.set()
        holder.join(timeout=15)
        assert holder.exitcode == 0
        assert result.status == "failed"
        assert _audit.read_audit() == []

    def test_append_failure_before_write_returns_failed_without_a_partial_line(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_open = Path.open

        def fail_append(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
            if self == audit_home / "audit.log" and mode == "a+":
                raise OSError("injected pre-write failure")
            return real_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_append, raising=True)
        result = _audit.audit_log("keys.add", "NO_EVENT")

        assert result.status == "failed"
        assert _audit.read_audit() == []

    def test_append_failure_after_rotation_recovers_from_the_backup_head(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        assert _audit.audit_log("keys.add", "FIRST").status == "written"
        real_open = Path.open
        failed_once = False

        def fail_once(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
            nonlocal failed_once
            if self == audit_home / "audit.log" and mode == "a+" and not failed_once:
                failed_once = True
                raise OSError("injected post-rotation append failure")
            return real_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_once, raising=True)
        assert _audit.audit_log("keys.add", "FAILED").status == "failed"
        assert not (audit_home / "audit.log").exists()
        backup_entries = [
            json.loads(line) for line in (audit_home / "audit.log.1").read_text().splitlines()
        ]
        assert [entry["detail"] for entry in backup_entries] == ["FIRST"]

        assert _audit.audit_log("keys.add", "RECOVERED").status == "written"
        entries = _audit.read_audit()
        assert [(entry["seq"], entry["detail"]) for entry in entries] == [(2, "RECOVERED")]
        assert entries[0]["prev_hash"] == _audit._hash_entry(backup_entries[0])
        assert _audit.verify_chain().break_at is None

    def test_success_restores_owner_only_permissions(self, audit_home: Path) -> None:
        result = _audit.audit_log("keys.add", "PERMISSIONS")

        assert result.status == "written"
        assert os.stat(audit_home / "audit.log").st_mode & 0o777 == 0o600


class TestAuditLogNeverRaises:
    """audit_log()'s never-fail contract (module docstring) must survive
    whatever this card added -- a rotation-continuation lookup is still
    just another best-effort step inside the same try/except."""

    def test_unwritable_parent_directory_does_not_raise(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(self: Path, *a: object, **kw: object) -> None:
            raise OSError("simulated: cannot create parent directory")

        monkeypatch.setattr(Path, "mkdir", _boom, raising=True)
        _audit.audit_log("keys.add", "SHOULD_NOT_RAISE")  # must not raise
        assert not (audit_home / "audit.log").exists()

    def test_unwritable_log_file_does_not_raise(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_open = Path.open

        def _boom_on_log(self: Path, *a: object, **kw: object) -> object:
            if self.name == "audit.log":
                raise OSError("simulated: cannot open audit.log for append")
            return real_open(self, *a, **kw)

        monkeypatch.setattr(Path, "open", _boom_on_log, raising=True)
        _audit.audit_log("keys.add", "SHOULD_NOT_RAISE")  # must not raise
        assert not (audit_home / "audit.log").exists()

    def test_unwritable_backup_during_rotation_does_not_raise(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _rotate_if_needed's os.replace can itself fail (e.g. a read-only
        # parent) -- must degrade to "no rotation happened" (None), not raise.
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")

        def _boom(*a: object, **kw: object) -> None:
            raise OSError("simulated: cannot rename during rotation")

        monkeypatch.setattr("os.replace", _boom, raising=True)
        _audit.audit_log("keys.add", "SECOND")  # must not raise despite rotation failing
        # The write itself still succeeded (best-effort covers rotation only).
        entries = _audit.read_audit()
        assert entries[-1]["detail"] == "SECOND"


class TestChainVerify:
    def test_missing_log_reports_nothing_to_verify(self, audit_home: Path) -> None:
        result = _audit.verify_chain()
        assert result.exists is False
        assert result.break_at is None

    def test_fresh_log_verifies_clean(self, audit_home: Path) -> None:
        for i in range(5):
            _audit.audit_log("keys.add", f"KEY_{i}")
        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.chained == 5
        assert result.legacy == 0
        assert result.total_lines == 5

    def test_tampered_middle_line_detected_at_right_position(self, audit_home: Path) -> None:
        for i in range(5):
            _audit.audit_log("keys.add", f"KEY_{i}")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()

        # Tamper the 3rd line's payload (seq=3) without touching its prev_hash.
        tampered = json.loads(lines[2])
        tampered["detail"] = "TAMPERED"
        lines[2] = json.dumps(tampered)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = _audit.verify_chain()
        assert result.break_at is not None
        # Line 3's own prev_hash (pointing at line 2) is untouched, so the
        # mismatch only becomes provable at line 4, whose stored prev_hash no
        # longer matches the (now-tampered) line 3's recomputed hash.
        assert result.break_at.line == 4
        assert "prev_hash mismatch" in result.break_at.reason
        # Everything before the break was still counted as chained.
        assert result.chained == 3
        # total_lines still reports the full file length even though
        # counting stopped at the break.
        assert result.total_lines == 5

    def test_malformed_json_line_reported_not_crashed(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        logf.write_text("{not valid json\n", encoding="utf-8")
        result = _audit.verify_chain()
        assert result.break_at is not None
        assert result.break_at.line == 1
        assert "malformed" in result.break_at.reason
        assert result.total_lines == 1

    def test_legacy_unchained_line_is_not_tampering(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        legacy = {
            "ts": "2026-06-01T00:00:00Z",
            "user": "alice",
            "pid": 1,
            "action": "gates.enable",
            "detail": "",
        }
        logf.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        logf.chmod(0o600)

        _audit.audit_log("keys.add", "AFTER_LEGACY")

        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.legacy == 1
        assert result.chained == 1
        # The chain restarts fresh right after the legacy line.
        entries = _audit.read_audit()
        assert entries[1]["seq"] == 1
        assert entries[1]["prev_hash"] == _audit.GENESIS_HASH

    def test_legacy_lines_dont_crash_the_viewer(self, audit_home: Path) -> None:
        logf = audit_home / "audit.log"
        logf.write_text(
            '{"ts": "x", "user": "a", "pid": 1, "action": "gates.enable", "detail": ""}\n',
            encoding="utf-8",
        )
        rc = audit_cli.run_audit()
        assert rc == 0

    def test_single_rotation_continues_the_chain_and_verifies_clean(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W18-1: a single rotation no longer restarts the chain at seq=1.

        The new current file's first entry carries the rotated generation's
        final seq+1 and its hash as prev_hash -- a continuation claim -- and
        `verify_chain` checks that claim against the backup it just wrote,
        reporting it clean with `continued_from_seq` set rather than a fresh
        (indistinguishable-from-genesis) restart.
        """
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")
        _audit.audit_log("keys.add", "SECOND")

        assert (audit_home / "audit.log.1").exists()
        entries = _audit.read_audit()
        assert entries[0]["seq"] == 2  # continues from the rotated "FIRST", not 1
        assert entries[0]["prev_hash"] != _audit.GENESIS_HASH

        result = _audit.verify_chain()
        assert result.rotated_backup is True
        assert result.break_at is None
        assert result.chained == 1  # only "SECOND" is in the current file
        assert result.total_lines == 1  # rotated-away "FIRST" isn't in this count either
        assert result.continued_from_seq == 1  # verified against audit.log.1's "FIRST"

    def test_rotation_over_a_legacy_tail_still_starts_a_fresh_genesis_chain(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backward compat: a legacy (pre-chain) last line has no seq/prev_hash
        to continue from, so rotating it away is still an honest restart at
        seq=1/GENESIS_HASH -- unchanged from pre-W18-1 behaviour."""
        logf = audit_home / "audit.log"
        legacy_line = json.dumps(
            {"ts": "2026-06-01T00:00:00Z", "user": "alice", "pid": 1, "action": "x", "detail": ""}
        )
        logf.write_text(legacy_line + "\n", encoding="utf-8")
        logf.chmod(0o600)
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)

        _audit.audit_log("keys.add", "AFTER_ROTATED_LEGACY")

        entries = _audit.read_audit()
        assert entries[0]["seq"] == 1
        assert entries[0]["prev_hash"] == _audit.GENESIS_HASH
        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.continued_from_seq is None


class TestRotationErasureDetection:
    """W18-1: the reproduced bug and its fix.

    Before this card, flooding a small AUDIT_LOG_MAX_BYTES with enough
    entries to rotate twice erased the security-relevant entries from BOTH
    the current file and the single-generation backup, and verify_chain()
    reported a clean chain restarting at seq=1 -- indistinguishable from a
    fresh install. The fix doesn't recover the deleted bytes (nothing can,
    short of keeping unbounded generations), but it makes the fact that
    history preceded the current file impossible to hide silently: seq no
    longer resets at a rotation, and if the one backup generation that would
    substantiate the continuation claim is itself missing or altered,
    verify_chain() now reports a break instead of "no break".
    """

    def _flood_past_two_rotations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 300, raising=True)
        _audit.audit_log("keys.add", "SECRET_ONE")
        _audit.audit_log("keys.remove", "SECRET_TWO")
        for i in range(200):
            _audit.audit_log("noise.tick", f"n{i}")

    def test_flooding_erases_the_entries_but_seq_no_longer_hides_it(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._flood_past_two_rotations(monkeypatch)

        # The bug's original symptom is still true: the secret-bearing lines
        # are genuinely gone from disk. Nothing about this card recovers them.
        all_text = (audit_home / "audit.log").read_text(encoding="utf-8") + (
            audit_home / "audit.log.1"
        ).read_text(encoding="utf-8")
        assert "SECRET_ONE" not in all_text
        assert "SECRET_TWO" not in all_text

        # But unlike before, verify_chain no longer claims a fresh seq=1
        # chain -- the true, much larger seq is visible, evidencing that a
        # long history preceded this file even though most of it rotated
        # away legitimately (not tampering: the single retained backup
        # verifies the one hop we can still substantiate).
        entries = _audit.read_audit()
        assert entries[0]["seq"] > 2
        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.continued_from_seq is not None

    def test_deleting_the_backup_after_flooding_is_now_detected(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The concrete guard: erasing the one remaining link (audit.log.1)
        turns a verifiable continuation into an unverifiable one, and that
        IS reported as a break -- this is the new, previously-missing
        detection the card exists to add."""
        self._flood_past_two_rotations(monkeypatch)
        assert _audit.verify_chain().break_at is None  # sanity: clean before erasure

        (audit_home / "audit.log.1").unlink()

        result = _audit.verify_chain()
        assert result.break_at is not None
        assert result.break_at.line == 1
        assert "audit.log.1 is missing" in result.break_at.reason
        assert result.rotated_backup is False
        assert result.continued_from_seq is None

    def test_altering_the_backups_tail_after_rotation_is_detected(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting the backup isn't the only way to hide history -- hand-
        editing its last line so it no longer matches the current file's
        continuation claim must be caught the same way."""
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")
        _audit.audit_log("keys.add", "SECOND")
        assert _audit.verify_chain().break_at is None  # sanity: clean before tamper

        backup = audit_home / "audit.log.1"
        tampered = json.loads(backup.read_text(encoding="utf-8").strip())
        tampered["detail"] = "TAMPERED"
        backup.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

        result = _audit.verify_chain()
        assert result.break_at is not None
        assert result.break_at.line == 1
        assert "does not match" in result.break_at.reason


class TestPreexistingLogBackwardCompat:
    """W18-1: a log written entirely by the pre-continuation code (or one
    whose rotation predates this card) must not be reported as tampering
    just because it now sits next to a backup it never claimed."""

    def test_preexisting_current_file_with_unrelated_backup_verifies_clean(
        self, audit_home: Path
    ) -> None:
        # Simulates: the pre-W18-1 code rotated once, writing a current file
        # that (as it always did) restarts at seq=1/GENESIS_HASH with no
        # knowledge of, or claim on, the backup sitting next to it.
        backup = audit_home / "audit.log.1"
        backup.write_text(
            json.dumps(
                {
                    "seq": 1,
                    "ts": "2026-06-01T00:00:00.000Z",
                    "user": "alice",
                    "pid": 1,
                    "action": "keys.add",
                    "detail": "OLD_BEFORE_ROTATION",
                    "prev_hash": _audit.GENESIS_HASH,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        backup.chmod(0o600)

        _audit.audit_log("keys.add", "AFTER_OLD_ROTATION")

        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.continued_from_seq is None  # no claim was ever made
        assert result.rotated_backup is True


class TestAuditVerifyCommand:
    def test_verify_missing_log(self, audit_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = audit_cli.run_audit_verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "Nothing to verify" in out

    def test_verify_clean_log(self, audit_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _audit.audit_log("keys.add", "A")
        rc = audit_cli.run_audit_verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "verified clean" in out

    def test_json_view_uses_the_locked_core_raw_snapshot(
        self, audit_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Raw JSONL is a scripting contract, so route it through the core
        # reader without normalising whitespace or opening the file in CLI.
        raw = '{ "action": "legacy", "detail": "A" }\n'
        (audit_home / "audit.log").write_text(raw, encoding="utf-8")

        rc = audit_cli.run_audit(json_out=True)

        assert rc == 0
        assert capsys.readouterr().out == raw

    def test_verify_tampered_log_fails_with_line_number(
        self, audit_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[0])
        e["detail"] = "TAMPERED"
        lines[0] = json.dumps(e)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = audit_cli.run_audit_verify()
        captured = capsys.readouterr()
        assert rc == 1
        assert "line 2" in captured.err

    def test_verify_tampered_log_reports_total_lines(
        self, audit_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # VerifyResult.total_lines is rendered in the one place it adds
        # information chained+legacy can't (how much of the file lies beyond
        # the detected break, since counting stops there).
        _audit.audit_log("keys.add", "A")
        _audit.audit_log("keys.add", "B")
        _audit.audit_log("keys.add", "C")
        logf = audit_home / "audit.log"
        lines = logf.read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[0])
        e["detail"] = "TAMPERED"
        lines[0] = json.dumps(e)
        logf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = audit_cli.run_audit_verify()
        captured = capsys.readouterr()
        assert rc == 1
        assert "line 2 of 3" in captured.err

    def test_verify_reports_a_verified_rotation_continuation(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")
        _audit.audit_log("keys.add", "SECOND")

        rc = audit_cli.run_audit_verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "verified clean" in out
        assert "continues from a rotated generation" in out

    def test_verify_reports_erasure_of_the_rotated_backup_as_a_failure(
        self, audit_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # W18-1's headline case: before this card, deleting audit.log.1
        # after a rotation left `docket audit verify` reporting a clean
        # chain (exit 0). It must now fail loudly (exit 1).
        monkeypatch.setattr(_cfg, "AUDIT_LOG_MAX_BYTES", 1, raising=True)
        _audit.audit_log("keys.add", "FIRST")
        _audit.audit_log("keys.add", "SECOND")
        (audit_home / "audit.log.1").unlink()

        rc = audit_cli.run_audit_verify()
        captured = capsys.readouterr()
        assert rc == 1
        assert "audit.log.1 is missing" in captured.err


# ── new call-site coverage ───────────────────────────────────────────────────


class TestKeysAudit:
    @pytest.fixture()
    def keys_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        d = tmp_path / ".docket"
        d.mkdir()
        monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
        monkeypatch.setattr(
            keys_cli._getpass, "getpass", lambda *a, **k: "sk-ant-testvalue00000000000000"
        )
        return d

    def test_keys_add_writes_one_entry_no_secret_value(self, keys_home: Path) -> None:
        rc = keys_cli._keys_add("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.add")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"
        assert "sk-ant-testvalue" not in json.dumps(entries)

    def test_keys_rotate_writes_one_entry_no_secret_value(self, keys_home: Path) -> None:
        keys_cli._keys_add("ANTHROPIC_API_KEY")
        rc = keys_cli._keys_rotate("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.rotate")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"
        assert "sk-ant-testvalue" not in json.dumps(entries)

    def test_keys_remove_writes_one_entry(self, keys_home: Path) -> None:
        keys_cli._keys_add("ANTHROPIC_API_KEY")
        rc = keys_cli._keys_remove("ANTHROPIC_API_KEY")
        assert rc == 0
        entries = _entries("keys.remove")
        assert len(entries) == 1
        assert entries[0]["detail"] == "ANTHROPIC_API_KEY"


class TestScopeAudit:
    def test_scope_set_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_scope("demo", "set", "beta")
        entries = _entries("scope.set")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=beta"

    def test_scope_reset_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_scope("demo", "reset", None)
        entries = _entries("scope.reset")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"


class TestProfileAudit:
    def test_profile_budget_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_profile("demo", None, budget="5")
        entries = _entries("profile.budget")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=$5"

    def test_profile_model_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_profile("demo", "anthropic/claude-haiku-4-5", budget=None)
        entries = _entries("profile.model")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=anthropic/claude-haiku-4-5 (pinned)"


class TestPersonaAudit:
    def test_persona_set_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_persona("demo", "set", "Orion 🔭")
        entries = _entries("persona.set")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo=Orion 🔭"

    def test_persona_clear_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        cli.cmd_persona("demo", "set", "Orion 🔭")
        cli.cmd_persona("demo", "clear", None)
        entries = _entries("persona.clear")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"


class TestAgentAddDeleteAudit:
    def test_agent_add_declarative_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
        monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
        monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
        monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
        monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
        monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                {
                    "id": "declaredagent",
                    "name": "Declared",
                    "codebase": "",
                    "stack": "",
                    "model": "",
                    "description": "",
                }
            )
        )

        rc = run_init(["--from", str(spec_file)])
        assert rc == 0

        entries = _entries("agent.add")
        assert len(entries) == 1
        assert entries[0]["detail"].startswith("declaredagent model=")
        assert entries[0]["detail"].endswith("source=declarative")

    def test_agent_delete_writes_one_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_agent(tmp_path, monkeypatch)
        responses = iter(["n", "demo"])  # keep workspace, confirm id
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(responses))

        rc = run_delete("demo")
        assert rc == 0

        entries = _entries("agent.delete")
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo"
