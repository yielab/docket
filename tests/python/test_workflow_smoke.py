"""Executable whole-product smoke test.

The harness crosses the real CLI subprocess and loopback HTTP boundaries. Focused suites own the
failure matrix; this test owns one observable proof that the happy-path components compose.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from docket.core.pipeline import MechanicalGate, load_pipeline
from docket.edges.adapters import toolbox

_SMOKE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "smoke_workflow.py"
_SMOKE_SPEC = importlib.util.spec_from_file_location("docket_smoke_workflow", _SMOKE_PATH)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
_smoke = importlib.util.module_from_spec(_SMOKE_SPEC)
sys.modules[_SMOKE_SPEC.name] = _smoke
_SMOKE_SPEC.loader.exec_module(_smoke)


def test_basic_smoke_mechanical_gate_is_byte_exact(tmp_path: Path) -> None:
    _, codebase, _, pipeline_path = _smoke._write_inputs(tmp_path, _smoke._BASIC_SCENARIO)
    loaded = load_pipeline(pipeline_path.read_text(encoding="utf-8"))
    assert loaded.errors == [] and loaded.spec is not None
    gate = loaded.spec.steps[1].gate
    assert isinstance(gate, MechanicalGate) and gate.command is not None

    artifact = codebase / "smoke-artifact.txt"
    artifact.write_bytes(b"docket smoke ok")
    missing_lf = subprocess.run(gate.command, cwd=codebase, shell=True, check=False)
    artifact.write_bytes(b"docket smoke ok\n")
    exact = subprocess.run(gate.command, cwd=codebase, shell=True, check=False)
    artifact.write_bytes(b"docket smoke ok\n\n")
    extra_lf = subprocess.run(gate.command, cwd=codebase, shell=True, check=False)

    assert missing_lf.returncode != 0
    assert exact.returncode == 0
    assert extra_lf.returncode != 0
    assert "terminal LF" in _smoke._basic_task_description()


def test_memory_smoke_delegation_routes_private_context_only_through_typed_handoff() -> None:
    calls: list[tuple[str, ...]] = []

    def recorder(*args: str) -> None:
        calls.append(args)

    _smoke._delegate_smoke_task(recorder, _smoke._MEMORY_SCENARIO)

    description = (
        "Repair checkout calculation and receipt metadata per the Lead's current durable "
        "decisions. Each downstream role must use only the Lead's typed handoff. Never search or "
        "access Docket private control paths (MEMORY.md, HEARTBEAT.md, memory/, .docket) with "
        "project tools. Keep public APIs stable. Modify source only with edit/write. Only run "
        "exactly: PYTHONPATH=src python -m unittest discover -s tests -v. "
        "No alternatives, wrappers, inline code, or redirects. Never copy private logs."
    )
    assert calls == [("pod", "smoke", "delegate", description)]
    assert "Each downstream role must use only the Lead's typed handoff" in description
    assert "Never search or access Docket private control paths" in description
    assert "with project tools" in description
    assert "Modify source only with edit/write" in description
    assert "PYTHONPATH=src python -m unittest discover -s tests -v" in description
    assert "No alternatives, wrappers, inline code, or redirects" in description
    for private_path in ("MEMORY.md", "HEARTBEAT.md", "memory/", ".docket"):
        assert private_path in description
    normalized = _smoke._normalized_fact_text(description)
    for private_value in ("cobalt-7", "amber-2", "5_000", "10_000"):
        assert _smoke._normalized_fact_text(private_value) not in normalized


def test_memory_smoke_delegation_fits_the_public_cli_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import docket.config as _cfg
    from docket.cli import _pod, app
    from docket.core import dispatch as _dispatch

    home = tmp_path / ".docket"
    codebase = tmp_path / "codebase"
    (home / "workspaces" / "projects").mkdir(parents=True)
    codebase.mkdir()
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)
    _pod.build_pod(
        "smoke",
        ("lead", "implementer", "reviewer", "tester"),
        codebase=str(codebase),
    )
    results: list[object] = []

    def run_cli(*args: str) -> None:
        results.append(CliRunner().invoke(app, list(args)))

    _smoke._delegate_smoke_task(run_cli, _smoke._MEMORY_SCENARIO)

    assert len(results) == 1
    result = results[0]
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    tasks = _dispatch.read_tasks("smoke")
    assert len(tasks) == 1
    assert tasks[0]["description"] == _smoke._memory_task_description()
    assert len(tasks[0]["description"]) <= 500


def test_basic_smoke_delegation_remains_byte_identical() -> None:
    calls: list[tuple[str, ...]] = []

    def recorder(*args: str) -> None:
        calls.append(args)

    _smoke._delegate_smoke_task(recorder, _smoke._BASIC_SCENARIO)

    assert calls == [("pod", "smoke", "delegate", _smoke._basic_task_description())]


@pytest.mark.parametrize(
    ("tool", "arguments", "violating_marker"),
    [
        ("read", {"path": "memory/2026-08-25.md"}, "memory"),
        ("read", {"path": "../outside/MEMORY.md"}, "memory.md"),
        ("glob", {"path": ".", "pattern": "memory/*"}, "memory"),
        (
            "glob",
            {"path": ".", "pattern": "../.d*/workspaces/projects/smoke-lead/m*/*"},
            ".docket",
        ),
        ("bash", {"command": "cat memory/2026-08-25.md"}, "memory"),
        ("read", {"path": "src/memory_utils.py"}, None),
        ("read", {"path": ".git/config"}, None),
        ("glob", {"path": ".", "pattern": "**/*"}, None),
        (
            "grep",
            {"path": "src", "pattern": "MEMORY.md", "glob": "*.py"},
            None,
        ),
        (
            "grep",
            {
                "path": ".",
                "pattern": "needle",
                "glob": "../.d*/workspaces/projects/smoke-lead/m*/*",
            },
            ".docket",
        ),
        (
            "edit",
            {
                "path": "src/checkout.py",
                "old_string": "old",
                "new_string": "documentation mentions MEMORY.md and memory/",
            },
            None,
        ),
    ],
)
def test_private_project_tool_classifier_is_structured(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, str],
    violating_marker: str | None,
) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / ".docket" / "worktrees" / "implementer"
    codebase.mkdir()
    worktree.mkdir(parents=True)

    violation = _smoke._private_tool_violation(
        tool,
        json.dumps(arguments),
        (codebase, worktree),
    )

    assert violation == violating_marker


@pytest.mark.parametrize(
    ("tool", "arguments", "kind", "marker"),
    [
        ("read", {"path": "src/checkout.py"}, "allowed", None),
        ("read", {"path": ".docket/config"}, "confirmed_private", ".docket"),
        ("bash", {"command": "$UNKNOWN_COMMAND"}, "opaque", "malformed-arguments"),
    ],
)
def test_smoke_tool_verdict_distinguishes_allowed_private_and_opaque(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, str],
    kind: str,
    marker: str | None,
) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / "worktree"
    codebase.mkdir()
    worktree.mkdir()

    verdict = _smoke._tool_verdict(
        tool,
        json.dumps(arguments),
        (codebase, worktree),
        relative_project_root=worktree,
    )

    assert verdict.kind.value == kind
    assert verdict.marker == marker
    assert verdict.disqualifies is (kind != "allowed")


def test_private_project_tool_classifier_normalizes_allowed_worktree(tmp_path: Path) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / ".docket" / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    reviewer_workspace = worktree.parent.parent / "smoke-reviewer"
    (codebase / "src").mkdir(parents=True)
    (codebase / "safe.txt").write_text("SAFE_ROOT_CONTENT", encoding="utf-8")
    (worktree / "src").mkdir(parents=True)
    reviewer_workspace.mkdir()
    (worktree / "private-link").symlink_to(reviewer_workspace, target_is_directory=True)

    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": str(worktree / "src" / "checkout.py")}),
            (codebase, worktree),
        )
        is None
    )
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": str(tmp_path / "elsewhere" / "MEMORY.md")}),
            (codebase, worktree),
        )
        == "memory.md"
    )
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": str(worktree / ".docket" / "config")}),
            (codebase, worktree),
        )
        == ".docket"
    )
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": "memory/../src/checkout.py"}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        is None
    )
    assert (
        _smoke._private_tool_violation(
            "bash",
            json.dumps({"command": "sh -c 'cat ../../smoke-lead/m*/2026.md'"}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        == ".docket"
    )
    assert _smoke._relative_project_root("lead", (codebase, worktree)) == codebase
    for downstream in ("implementer", "reviewer", "tester", "smoke-reviewer"):
        assert _smoke._relative_project_root(downstream, (codebase, worktree)) == worktree
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": str(reviewer_workspace / "SOUL.md")}),
            (codebase, worktree),
        )
        == ".docket"
    )
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": "../../smoke-reviewer/SOUL.md"}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        == ".docket"
    )
    assert (
        _smoke._private_tool_violation(
            "read",
            json.dumps({"path": "private-link/SOUL.md"}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        == ".docket"
    )
    assert (
        _smoke._private_tool_violation("read", "not-json", (codebase, worktree))
        == "malformed-arguments"
    )
    root_contained_selector = "../**/*"
    globbed_safe = toolbox.glob_files((codebase,), root_contained_selector, path="src")
    grepped_safe = toolbox.grep_files(
        (codebase,),
        "SAFE_ROOT_CONTENT",
        path="src",
        glob=root_contained_selector,
    )
    assert globbed_safe.ok and "safe.txt" in globbed_safe.content
    assert grepped_safe.ok and "SAFE_ROOT_CONTENT" in grepped_safe.content
    assert (
        _smoke._private_tool_violation(
            "glob",
            json.dumps({"path": "src", "pattern": root_contained_selector}),
            (codebase, worktree),
            relative_project_root=codebase,
        )
        is None
    )
    assert (
        _smoke._private_tool_violation(
            "grep",
            json.dumps(
                {"path": "src", "pattern": "SAFE_ROOT_CONTENT", "glob": root_contained_selector}
            ),
            (codebase, worktree),
            relative_project_root=codebase,
        )
        is None
    )


def test_private_classifier_fails_closed_for_inline_interpreter_code(tmp_path: Path) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / ".docket" / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    reviewer_workspace = worktree.parent.parent / "smoke-reviewer"
    codebase.mkdir()
    worktree.mkdir(parents=True)
    reviewer_workspace.mkdir()
    (reviewer_workspace / "SOUL.md").write_text("PRIVATE_INLINE_SENTINEL", encoding="utf-8")
    command = (
        f"{shlex.quote(sys.executable)} -c \"print(open('../../smoke-reviewer/SOUL.md').read())\""
    )
    nested_shell_command = "bash --noprofile -c 'cat ../../smoke-reviewer/SOUL.md'"
    stdin_shell_command = "printf 'cat ../../smoke-reviewer/SOUL.md\\n' | sh"
    wrapped_stdin_shell_command = "printf 'cat ../../smoke-reviewer/SOUL.md\\n' | env sh"
    eval_command = "eval 'cat ../../smoke-reviewer/SOUL.md'"
    wrapped_eval_command = "command eval 'cat ../../smoke-reviewer/SOUL.md'"
    proc_cwd_command = "cat /proc/self/cwd/../../smoke-reviewer/SOUL.md"
    script_command = "sh leak.sh"
    attached_separator_command = "true;sh -c 'cat ../../smoke-reviewer/SOUL.md'"
    newline_command = "true\nsh -c 'cat ../../smoke-reviewer/SOUL.md'"
    uv_script_command = "uv run sh leak.sh"
    awk_script_command = "awk -f leak.awk"
    opaque_wrapper_commands = ("timeout 5 sh leak.sh", "nice sh leak.sh")
    (worktree / "leak.sh").write_text(
        "cat ../../smoke-reviewer/SOUL.md\n",
        encoding="utf-8",
    )
    (worktree / "leak.awk").write_text(
        'BEGIN { while ((getline line < "../../smoke-reviewer/SOUL.md") > 0) print line }\n',
        encoding="utf-8",
    )

    executed = toolbox.run_bash((worktree,), command, sandbox="off")
    nested_shell_executed = toolbox.run_bash((worktree,), nested_shell_command, sandbox="off")
    stdin_shell_executed = toolbox.run_bash((worktree,), stdin_shell_command, sandbox="off")
    wrapped_stdin_executed = toolbox.run_bash(
        (worktree,), wrapped_stdin_shell_command, sandbox="off"
    )
    eval_executed = toolbox.run_bash((worktree,), eval_command, sandbox="off")
    wrapped_eval_executed = toolbox.run_bash((worktree,), wrapped_eval_command, sandbox="off")
    proc_cwd_executed = toolbox.run_bash((worktree,), proc_cwd_command, sandbox="off")
    script_executed = toolbox.run_bash((worktree,), script_command, sandbox="off")
    attached_separator_executed = toolbox.run_bash(
        (worktree,), attached_separator_command, sandbox="off"
    )
    newline_executed = toolbox.run_bash((worktree,), newline_command, sandbox="off")
    violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    nested_shell_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": nested_shell_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    stdin_shell_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": stdin_shell_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    wrapped_stdin_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": wrapped_stdin_shell_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    eval_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": eval_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    wrapped_eval_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": wrapped_eval_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    proc_cwd_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": proc_cwd_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    script_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": script_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    attached_separator_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": attached_separator_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    newline_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": newline_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    uv_script_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": uv_script_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    awk_script_violation = _smoke._private_tool_violation(
        "bash",
        json.dumps({"command": awk_script_command}),
        (codebase, worktree),
        relative_project_root=worktree,
    )
    opaque_wrapper_violations = [
        _smoke._private_tool_violation(
            "bash",
            json.dumps({"command": wrapped_command}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        for wrapped_command in opaque_wrapper_commands
    ]

    assert executed.ok and "PRIVATE_INLINE_SENTINEL" in executed.content
    assert nested_shell_executed.ok and "PRIVATE_INLINE_SENTINEL" in nested_shell_executed.content
    assert stdin_shell_executed.ok and "PRIVATE_INLINE_SENTINEL" in stdin_shell_executed.content
    assert wrapped_stdin_executed.ok and "PRIVATE_INLINE_SENTINEL" in wrapped_stdin_executed.content
    assert eval_executed.ok and "PRIVATE_INLINE_SENTINEL" in eval_executed.content
    assert wrapped_eval_executed.ok and "PRIVATE_INLINE_SENTINEL" in wrapped_eval_executed.content
    assert proc_cwd_executed.ok and "PRIVATE_INLINE_SENTINEL" in proc_cwd_executed.content
    assert script_executed.ok and "PRIVATE_INLINE_SENTINEL" in script_executed.content
    assert attached_separator_executed.ok
    assert "PRIVATE_INLINE_SENTINEL" in attached_separator_executed.content
    assert newline_executed.ok and "PRIVATE_INLINE_SENTINEL" in newline_executed.content
    assert violation == "malformed-arguments"
    assert nested_shell_violation == ".docket"
    assert stdin_shell_violation == "malformed-arguments"
    assert wrapped_stdin_violation == "malformed-arguments"
    assert eval_violation == "malformed-arguments"
    assert wrapped_eval_violation == "malformed-arguments"
    assert proc_cwd_violation == "malformed-arguments"
    assert script_violation == "malformed-arguments"
    assert attached_separator_violation == ".docket"
    assert newline_violation == ".docket"
    assert uv_script_violation == "malformed-arguments"
    assert awk_script_violation == "malformed-arguments"
    assert opaque_wrapper_violations == ["malformed-arguments", "malformed-arguments"]


def test_private_classifier_allows_only_the_published_regression_entrypoint(
    tmp_path: Path,
) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / ".docket" / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    codebase.mkdir()
    worktree.mkdir(parents=True)
    allowed = "PYTHONPATH=src python -m unittest discover -s tests -v"
    alternate_module = "PYTHONPATH=src python -m unittest tests.test_private_probe -v"

    assert (
        _smoke._private_tool_violation(
            "bash",
            json.dumps({"command": allowed}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        is None
    )
    assert (
        _smoke._private_tool_violation(
            "bash",
            json.dumps({"command": alternate_module}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        == "malformed-arguments"
    )


def test_private_classifier_rejects_universal_selector_escape(tmp_path: Path) -> None:
    codebase = tmp_path / "codebase"
    worktree = tmp_path / ".docket" / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    private_log = tmp_path / ".docket" / "workspaces" / "projects" / "smoke-lead" / "memory"
    codebase.mkdir()
    worktree.mkdir(parents=True)
    private_log.mkdir(parents=True)
    (private_log / "2026-08-25.md").write_text("PRIVATE_GLOB_SENTINEL", encoding="utf-8")
    escaped_selector = "../*/workspaces/projects/smoke-lead/*/*"

    globbed = toolbox.glob_files((codebase,), escaped_selector)
    grepped = toolbox.grep_files(
        (codebase,),
        "PRIVATE_GLOB_SENTINEL",
        glob=escaped_selector,
    )
    glob_violation = _smoke._private_tool_violation(
        "glob",
        json.dumps({"path": ".", "pattern": escaped_selector}),
        (codebase, worktree),
        relative_project_root=codebase,
    )
    grep_violation = _smoke._private_tool_violation(
        "grep",
        json.dumps({"path": ".", "pattern": "PRIVATE_GLOB_SENTINEL", "glob": escaped_selector}),
        (codebase, worktree),
        relative_project_root=codebase,
    )

    assert globbed.ok and "2026-08-25.md" in globbed.content
    assert grepped.ok and "PRIVATE_GLOB_SENTINEL" in grepped.content
    assert glob_violation == ".docket"
    assert grep_violation == ".docket"
    assert (
        _smoke._private_tool_violation(
            "bash",
            json.dumps({"command": "cat $PRIVATE_ROOT/SOUL.md"}),
            (codebase, worktree),
            relative_project_root=worktree,
        )
        == "malformed-arguments"
    )


def _write_private_oracle_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    world = tmp_path / "world"
    home = world / ".docket"
    codebase = world / "codebase"
    worktree = home / "workspaces" / "projects" / "smoke-implementer" / "worktree"
    codebase.mkdir(parents=True)
    worktree.mkdir(parents=True)
    meta_path = home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps({"codebase": str(codebase), "worktreeDir": str(worktree)}),
        encoding="utf-8",
    )
    session_path = home / "sessions" / "safe" / "session.json"
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
    trace_path = home / "traces" / "smoke" / "agent:smoke:dispatch.jsonl"
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
    session_path = home / "sessions" / "safe" / "session.json"
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


def test_allowed_roots_reject_broadened_worktree_metadata(tmp_path: Path) -> None:
    home, _, _ = _write_private_oracle_fixture(tmp_path)
    meta_path = home / "workspaces" / "projects" / "smoke-implementer" / ".docket-meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["worktreeDir"] = str(home)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

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

    assert _smoke._approval_private_tool_violation(
        home,
        approval,
        _smoke._smoke_allowed_project_roots(home),
    ) == (True, None)


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

    assert _smoke._approval_private_tool_violation(
        home,
        approval,
        _smoke._smoke_allowed_project_roots(home),
    ) == (True, ".docket")


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
    approvals = home / "approvals"
    approvals.mkdir()
    (approvals / "approval-private.json").write_text(
        json.dumps(
            {
                "token": "approval-private",
                "project": "smoke-implementer",
                "role": "implementer",
                "state": "pending",
                "context": {"tool": "bash", "callId": call_id},
            }
        ),
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
        if args == ("runs", "list", "--project", "smoke", "--json"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"runs": [{"id": "run-live", "state": "running"}]}), ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_smoke, "_run_cli", fake_run_cli)

    with (
        pytest.raises(_smoke.SmokeFailure) as exc_info,
        _smoke._approve_live_tool_calls(tmp_path, {}, home) as state,
    ):
        assert state.abort.wait(2)

    assert calls == [
        ("runs", "list", "--project", "smoke", "--json"),
        ("runs", "cancel", "run-live"),
        ("deny", "approval-private"),
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
    approvals = home / "approvals"
    approvals.mkdir()
    (approvals / "approval-allowed.json").write_text(
        json.dumps(
            {
                "token": "approval-allowed",
                "project": "smoke-implementer",
                "role": "implementer",
                "state": "pending",
                "context": {"tool": "bash", "callId": call_id},
            }
        ),
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
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_smoke, "_run_cli", fake_run_cli)

    with _smoke._approve_live_tool_calls(tmp_path, {}, home) as state:
        for _ in range(20):
            if state.granted:
                break
            threading.Event().wait(0.05)
        assert state.granted == ["approval-allowed"]
        assert state.abort.is_set() is False

    assert calls == [("approve", "approval-allowed")]


def test_run_cli_does_not_start_after_canary_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    abort = threading.Event()
    abort.set()

    def unexpected_popen(*args: object, **kwargs: object) -> object:
        raise AssertionError("a disqualified canary started another transport")

    monkeypatch.setattr(subprocess, "Popen", unexpected_popen)

    with pytest.raises(_smoke.SmokeFailure, match="disqualification"):
        _smoke._run_cli(tmp_path, {}, "pipeline", "run", "smoke", abort_event=abort)


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
        _smoke._run_cli(tmp_path, {}, "pipeline", "run", "smoke", abort_event=abort)

    assert process.terminated is True


def test_full_workflow_smoke_is_observable_and_preserves_state(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    world = tmp_path / "smoke-world"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/docket-uv-cache"

    result = subprocess.run(
        [sys.executable, "scripts/smoke_workflow.py", "--workdir", str(world)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "waiting_approval -> granted -> resumed" in result.stdout
    assert "tool call/result persisted atomically" in result.stdout
    assert "SMOKE PASS" in result.stdout
    assert (world / "codebase" / "smoke-artifact.txt").read_text() == "docket smoke ok\n"
    assert (
        world / ".docket" / "workspaces" / "projects" / "smoke-lead" / "TASK_LIST.json"
    ).is_file()


@pytest.mark.skipif(
    os.environ.get("DOCKET_RUN_LIVE_SMOKE") != "1",
    reason="set DOCKET_RUN_LIVE_SMOKE=1 to exercise the operator's local model",
)
def test_full_workflow_against_real_local_model(tmp_path: Path) -> None:
    """Opt-in memory-maintenance evidence; never substitutes scripted inference."""
    repo = Path(__file__).resolve().parents[2]
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
    assert "memory logs distilled and archived" in result.stdout
    assert "current durable decisions crossed the Lead handoff" in result.stdout
    assert "hidden checkout acceptance passed" in result.stdout
    assert "waiting_approval -> granted -> resumed" in result.stdout
    assert "SMOKE PASS" in result.stdout
    meta = json.loads(
        (
            world
            / ".docket"
            / "workspaces"
            / "projects"
            / "smoke-implementer"
            / ".docket-meta.json"
        ).read_text()
    )
    assert Path(meta["worktreeDir"], "src", "checkout.py").is_file()
    assert list(
        (
            world / ".docket" / "workspaces" / "projects" / "smoke-lead" / "memory" / ".distilled"
        ).glob("*/*.md")
    )
