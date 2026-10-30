"""The workflow smoke: the private oracle, live approval and the full run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from tests.support.smoke_script import (
    _smoke,
)

SUBJECT = "docket.__main__"
ESCALATION = "esc-0123456789ab"


def _write_private_oracle_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    world = tmp_path / "world"
    home = world / ".docket"
    codebase = world / "codebase"
    worktree = (
        home / "state" / "workspaces" / "projects" / "smoke-implementer" / "tasks" / "task-fixture"
    )
    codebase.mkdir(parents=True)
    worktree.mkdir(parents=True)
    meta_path = (
        home / "state" / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    )
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps({"codebase": str(codebase)}),
        encoding="utf-8",
    )
    task_list = home / "state" / "workspaces" / "projects" / "smoke-lead" / "TASK_LIST.json"
    task_list.parent.mkdir(parents=True, exist_ok=True)
    task_list.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "task-fixture",
                        "worktree": {
                            "dir": str(worktree),
                            "branch": "docket/smoke/task-fixture",
                            "baseCommit": "0" * 40,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    session_path = home / "state" / "sessions" / "safe" / "session.json"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        json.dumps(
            {
                "sessionKey": "agent:smoke-implementer:default",
                "created": "2026-08-25T00:00:00Z",
                "updated": "2026-08-25T00:00:01Z",
                "messages": [
                    {
                        "role": "assistant",
                        "toolCalls": [
                            {
                                "id": "safe-call",
                                "name": "read",
                                "arguments": json.dumps({"path": "src/checkout.py"}),
                            }
                        ],
                    }
                ],
                "usage": {"inputTokens": 1, "outputTokens": 1},
            }
        ),
        encoding="utf-8",
    )
    trace_path = home / "state" / "traces" / "smoke" / "agent:smoke:dispatch.jsonl"
    trace_path.parent.mkdir(parents=True)
    return home, trace_path, worktree


@pytest.mark.parametrize("absolute", [False, True])
def test_private_oracle_uses_durable_trace_after_session_compaction(
    tmp_path: Path, absolute: bool
) -> None:
    home, trace_path, _ = _write_private_oracle_fixture(tmp_path)
    target = str(tmp_path / "outside" / "MEMORY.md") if absolute else "memory/2026-08-25.md"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-25T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "implementer",
                "payload": {
                    "tool": "read",
                    "callId": "private-call",
                    "arguments": json.dumps({"path": target, "content": "PRIVATE_FACT_SENTINEL"}),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(_smoke.SmokeFailure) as exc_info:
        _smoke._verify_private_tool_boundary(home)

    error = str(exc_info.value)
    assert "source=trace" in error
    assert "role=implementer" in error
    assert "tool=read" in error
    assert "callId=private-call" in error
    assert "verdict=confirmed_private" in error
    assert "marker=memory" in error if not absolute else "marker=memory.md" in error
    assert "PRIVATE_FACT_SENTINEL" not in error


def test_private_oracle_checks_retained_session_calls(tmp_path: Path) -> None:
    home, trace_path, _ = _write_private_oracle_fixture(tmp_path)
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-25T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "lead",
                "payload": {"hop": "plan", "agent": "smoke-lead"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    session_path = home / "state" / "sessions" / "safe" / "session.json"
    record = json.loads(session_path.read_text(encoding="utf-8"))
    record["messages"][0]["toolCalls"][0] = {
        "id": "retained-private-call",
        "name": "glob",
        "arguments": json.dumps({"path": ".", "pattern": "memory/*"}),
    }
    session_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(_smoke.SmokeFailure, match="source=session"):
        _smoke._verify_private_tool_boundary(home)


def test_private_oracle_rejects_missing_known_tool_arguments(tmp_path: Path) -> None:
    home, trace_path, _ = _write_private_oracle_fixture(tmp_path)
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-25T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "reviewer",
                "payload": {"tool": "read", "callId": "malformed-call"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        _smoke.SmokeFailure,
        match="verdict=opaque marker=malformed-arguments",
    ):
        _smoke._verify_private_tool_boundary(home)


def test_allowed_roots_reject_broadened_task_worktree_record(tmp_path: Path) -> None:
    home, _, _ = _write_private_oracle_fixture(tmp_path)
    task_path = home / "state" / "workspaces" / "projects" / "smoke-lead" / "TASK_LIST.json"
    document = json.loads(task_path.read_text(encoding="utf-8"))
    document["tasks"][0]["worktree"]["dir"] = str(home)
    task_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(_smoke.SmokeFailure, match="isolated worktree"):
        _smoke._smoke_allowed_project_roots(home)


def test_live_approval_classifies_raw_trace_arguments_not_wrapping_prose(tmp_path: Path) -> None:
    home, trace_path, worktree = _write_private_oracle_fixture(tmp_path)
    call_id = "bash-validation"
    raw_arguments = json.dumps(
        {"command": (f"cd {worktree} && PYTHONPATH=src python -m unittest discover -s tests -v")}
    )
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-25T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "implementer",
                "payload": {"tool": "bash", "callId": call_id, "arguments": raw_arguments},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    approval = {
        "project": "smoke-implementer",
        "role": "implementer",
        "action": (
            "tool call 'bash': 'cd' is not on the curated allowlist; "
            f'call=bash command="cd {worktree} && python -m unittest"'
        ),
        "context": {"tool": "bash", "callId": call_id},
    }

    resolved, verdict = _smoke._approval_tool_verdict(
        home,
        approval,
        _smoke._smoke_allowed_project_roots(home),
    )
    assert (resolved, verdict.marker) == (True, None)


def test_live_approval_uses_latest_matching_trace_when_call_ids_collide(tmp_path: Path) -> None:
    home, trace_path, worktree = _write_private_oracle_fixture(tmp_path)
    call_id = "call_1"
    common = {
        "project": "smoke",
        "session_id": "agent:smoke:task-fixture",
        "event_type": "tool_call",
        "agent_role": "implementer",
    }
    records = [
        {
            **common,
            "ts": "2026-08-25T00:00:00Z",
            "payload": {
                "tool": "bash",
                "callId": call_id,
                "arguments": json.dumps({"command": f"cd {worktree} && python -m unittest"}),
            },
        },
        {
            **common,
            "ts": "2020-01-01T00:00:00Z",
            "payload": {
                "tool": "bash",
                "callId": call_id,
                "arguments": json.dumps({"command": "cat ../../smoke-lead/MEMORY.md"}),
            },
        },
        {
            **common,
            "ts": "2026-08-25T00:00:02Z",
            "payload": {
                "tool": "read",
                "callId": call_id,
                "arguments": json.dumps({"path": "src/checkout.py"}),
            },
        },
        {
            **common,
            "ts": "2026-08-25T00:00:03Z",
            "agent_role": "reviewer",
            "payload": {
                "tool": "bash",
                "callId": call_id,
                "arguments": json.dumps({"command": "python -m unittest"}),
            },
        },
    ]
    trace_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    approval = {
        "project": "smoke-implementer",
        "role": "implementer",
        "context": {"tool": "bash", "callId": call_id},
    }

    resolved, verdict = _smoke._approval_tool_verdict(
        home,
        approval,
        _smoke._smoke_allowed_project_roots(home),
    )
    assert (resolved, verdict.marker) == (True, ".docket")


@pytest.mark.parametrize(
    ("command", "kind", "marker"),
    [
        ("cat ../../smoke-lead/MEMORY.md", "confirmed_private", ".docket"),
        ("$UNKNOWN_COMMAND", "opaque", "malformed-arguments"),
    ],
)
def test_live_approval_disqualification_cancels_denies_and_aborts_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    kind: str,
    marker: str,
) -> None:
    home, trace_path, _ = _write_private_oracle_fixture(tmp_path)
    call_id = "private-bash"
    private_value = "PRIVATE_FACT_MUST_NOT_LEAK"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-26T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "implementer",
                "payload": {
                    "tool": "bash",
                    "callId": call_id,
                    "arguments": json.dumps({"command": f"{command} # {private_value}"}),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    approvals = home / "state" / "approvals"
    approvals.mkdir()
    (approvals / "approval-private.json").write_text(
        json.dumps(
            {
                "token": "approval-private",
                "escalation": ESCALATION,
                "project": "smoke-implementer",
                "role": "implementer",
                "state": "pending",
                "context": {"tool": "bash", "callId": call_id},
            }
        ),
        encoding="utf-8",
    )
    (home / "state" / "docket-runs.json").write_text(
        json.dumps({"runs": [{"id": "run-live", "project": "smoke", "state": "running"}]}),
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []

    def fake_run_cli(
        repo: Path,
        env: dict[str, str],
        *args: str,
        process_timeout: float | None = 45,
        abort_event: threading.Event | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del repo, env, process_timeout, abort_event
        calls.append(args)
        listing = json.dumps({"escalations": [{"id": ESCALATION, "task": "task-fixture"}]})
        return subprocess.CompletedProcess(args, 0, listing if args[0] == "inbox" else "", "")

    monkeypatch.setattr(_smoke, "_run_cli", fake_run_cli)

    with (
        pytest.raises(_smoke.SmokeFailure) as exc_info,
        _smoke._approve_live_tool_calls(tmp_path, {"DOCKET_HOME": str(home)}, home) as state,
    ):
        assert state.abort.wait(2)

    assert [c for c in calls if c[0] != "inbox"] == [
        ("task", "cancel", "run-live"),
        ("task", "answer", ESCALATION, "--option", "deny", "--pod", "smoke"),
    ]
    error = str(exc_info.value)
    assert "source=approval" in error
    assert "role=implementer" in error
    assert "tool=bash" in error
    assert f"callId={call_id}" in error
    assert f"verdict={kind}" in error
    assert f"marker={marker}" in error
    assert private_value not in error


def test_live_approval_grants_only_typed_allowed_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, trace_path, worktree = _write_private_oracle_fixture(tmp_path)
    call_id = "allowed-bash"
    trace_path.write_text(
        json.dumps(
            {
                "ts": "2026-08-26T00:00:00Z",
                "project": "smoke",
                "session_id": "agent:smoke:task-fixture",
                "event_type": "tool_call",
                "agent_role": "implementer",
                "payload": {
                    "tool": "bash",
                    "callId": call_id,
                    "arguments": json.dumps(
                        {
                            "command": (
                                f"cd {worktree} && PYTHONPATH=src "
                                "python -m unittest discover -s tests -v"
                            )
                        }
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    approvals = home / "state" / "approvals"
    approvals.mkdir()
    (approvals / "approval-allowed.json").write_text(
        json.dumps(
            {
                "token": "approval-allowed",
                "escalation": ESCALATION,
                "project": "smoke-implementer",
                "role": "implementer",
                "state": "pending",
                "context": {"tool": "bash", "callId": call_id},
            }
        ),
        encoding="utf-8",
    )
    (home / "state" / "docket-runs.json").write_text(
        json.dumps({"runs": [{"id": "run-live", "project": "smoke", "state": "running"}]}),
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []

    def fake_run_cli(
        repo: Path,
        env: dict[str, str],
        *args: str,
        process_timeout: float | None = 45,
        abort_event: threading.Event | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del repo, env, process_timeout, abort_event
        calls.append(args)
        listing = json.dumps({"escalations": [{"id": ESCALATION, "task": "task-fixture"}]})
        return subprocess.CompletedProcess(args, 0, listing if args[0] == "inbox" else "", "")

    monkeypatch.setattr(_smoke, "_run_cli", fake_run_cli)

    with _smoke._approve_live_tool_calls(tmp_path, {}, home) as state:
        for _ in range(20):
            if state.granted:
                break
            threading.Event().wait(0.05)
        assert state.granted == ["approval-allowed"]
        assert state.abort.is_set() is False

    assert [c for c in calls if c[0] != "inbox"] == [
        ("task", "answer", ESCALATION, "--option", "approve_once", "--pod", "smoke")
    ]


def test_run_cli_does_not_start_after_canary_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abort = threading.Event()
    abort.set()

    def unexpected_popen(*args: object, **kwargs: object) -> object:
        raise AssertionError("a disqualified canary started another transport")

    monkeypatch.setattr(subprocess, "Popen", unexpected_popen)

    with pytest.raises(_smoke.SmokeFailure, match="disqualification"):
        _smoke._run_cli(tmp_path, {}, "run", "--pod", "smoke", abort_event=abort)


def test_run_cli_terminates_in_flight_process_on_canary_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abort = threading.Event()

    class BlockingProcess:
        returncode = -15

        def __init__(self) -> None:
            self.terminated = False

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            if not self.terminated:
                abort.set()
                raise subprocess.TimeoutExpired("docket", timeout)
            return "durable output", ""

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

    process = BlockingProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(_smoke.SmokeFailure, match="stopped after canary disqualification"):
        _smoke._run_cli(tmp_path, {}, "run", "--pod", "smoke", abort_event=abort)

    assert process.terminated is True


@pytest.mark.skipif(
    os.environ.get("DOCKET_RUN_LIVE_SMOKE") != "1",
    reason="set DOCKET_RUN_LIVE_SMOKE=1 to exercise the operator's local model",
)
def test_full_workflow_against_real_local_model(tmp_path: Path) -> None:
    """Opt-in memory-maintenance evidence; never substitutes scripted inference."""
    repo = Path(__file__).resolve().parents[4]
    world = tmp_path / "live-smoke-world"
    endpoint = os.environ.get("DOCKET_LIVE_SMOKE_ENDPOINT", "http://127.0.0.1:8081/v1")
    command = [
        sys.executable,
        "scripts/smoke_workflow.py",
        "--live-model",
        "--scenario",
        "memory-maintenance",
        "--endpoint",
        endpoint,
        "--workdir",
        str(world),
    ]
    model = os.environ.get("DOCKET_LIVE_SMOKE_MODEL", "").strip()
    if model:
        command.extend(["--model", model])

    result = subprocess.run(
        command,
        cwd=repo,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Real model endpoint:" in result.stdout
    assert "pre-existing regressions fail for the intended checkout defects" in result.stdout
    assert "realistic checkout fixture committed before worktree provisioning" in result.stdout
    assert "operator MEMORY.md seeded with the current checkout decisions" in result.stdout
    assert "current durable decisions crossed the Lead handoff" in result.stdout
    assert "hidden checkout acceptance passed" in result.stdout
    assert "waiting_approval -> granted -> resumed" in result.stdout
    assert "SMOKE PASS" in result.stdout
    task_list = json.loads(
        (
            world
            / ".docket"
            / "state"
            / "workspaces"
            / "projects"
            / "smoke-lead"
            / "TASK_LIST.json"
        ).read_text()
    )
    assert Path(task_list["tasks"][0]["worktree"]["dir"], "src", "checkout.py").is_file()
    assert (
        "cobalt-7"
        in (
            world / ".docket" / "state" / "workspaces" / "projects" / "smoke-lead" / "MEMORY.md"
        ).read_text()
    )
