"""The replay bench's --repeats report: calls that repeat per step, files the Lead had read."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SUBJECT = "docket.pipeline.domain.plan"

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "maint" / "context_replay.py"
FIXTURES = REPO / "tests" / "fixtures" / "context-replay" / "v1"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_context_replay_repeats", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BENCH = _load()


def _step_files(
    directory: Path, name: str, role: str, task: str, calls: list[tuple[str, dict, str]]
) -> None:
    """One recorded step: each call is (tool, arguments, result)."""
    messages: list[dict] = [{"role": "user", "content": "go"}]
    for index, (tool, arguments, result) in enumerate(calls):
        call_id = f"{name}-{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [{"id": call_id, "name": tool, "arguments": json.dumps(arguments)}],
            }
        )
        messages.append({"role": "tool", "toolCallId": call_id, "name": tool, "content": result})
    messages.append({"role": "assistant", "content": "done", "toolCalls": []})
    (directory / f"{name}.session.json").write_text(json.dumps({"messages": messages}))
    call = {
        "agent_role": role,
        "task_id": task,
        "payload": {"inputTokens": 10, "outputTokens": 1, "iteration": 1},
    }
    (directory / f"{name}.llm_calls.jsonl").write_text(json.dumps(call) + "\n")


def test_the_fixture_implementer_has_one_repeated_read(capsys: pytest.CaptureFixture[str]) -> None:
    assert BENCH.main([str(FIXTURES), "--repeats", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    steps = {s["step"]: s for s in report["steps"]}
    repeated = [r for r in steps["implementer-b"]["repeats"] if r["tool"] == "read"]
    assert len(repeated) == 1 and repeated[0]["count"] == 2
    # The second read of that file returned 5,373 bytes; four bytes make one estimated token.
    assert steps["implementer-b"]["repeatedCalls"] == 1
    assert steps["implementer-b"]["rereadFiles"] == 1
    assert steps["implementer-b"]["bytes"] == 5373
    assert steps["implementer-b"]["estTokens"] == 5373 // 4
    assert [s["repeatedCalls"] for n, s in sorted(steps.items()) if n != "implementer-b"] == [
        0,
        0,
        0,
    ]


def test_the_table_is_printed_and_not_empty(capsys: pytest.CaptureFixture[str]) -> None:
    assert BENCH.main([str(FIXTURES), "--repeats"]) == 0
    out = capsys.readouterr().out
    assert "implementer-b" in out and "5,373" in out
    assert out.count("\n") > 4


def test_repeats_match_on_canonical_arguments_not_on_spelling(tmp_path: Path) -> None:
    _step_files(
        tmp_path,
        "impl",
        "implementer",
        "t1",
        [
            ("read", {"path": "/wt/t1/a.py", "limit": 10}, "x" * 100),
            ("read", {"limit": 10, "path": "/wt/t1/a.py"}, "x" * 100),
            ("read", {"limit": 20, "path": "/wt/t1/a.py"}, "y" * 50),
            ("grep", {"pattern": "foo", "path": "/wt/t1"}, "z" * 7),
            ("grep", {"pattern": "foo", "path": "/wt/t1"}, "z" * 7),
            ("bash", {"command": "ls"}, "q"),
            ("bash", {"command": "ls"}, "q"),
        ],
    )

    (step,) = BENCH.repeats_report(BENCH.load_steps(tmp_path))["steps"]

    assert step["repeatedCalls"] == 2
    assert {(r["tool"], r["count"]) for r in step["repeats"]} == {("read", 2), ("grep", 2)}
    assert step["bytes"] == 100 + 7


def test_files_the_implementer_read_that_the_lead_had_read(tmp_path: Path) -> None:
    root = "/srv/main/repo"
    _step_files(
        tmp_path,
        "lead",
        "lead",
        "t1",
        [
            ("read", {"path": f"{root}/src/a.py"}, "a" * 40),
            ("read", {"path": f"{root}/src/b.py"}, "b" * 30),
        ],
    )
    _step_files(
        tmp_path,
        "impl",
        "implementer",
        "t1",
        [
            ("read", {"path": "/wt/t1/src/a.py"}, "a" * 40),
            ("read", {"path": "/wt/t1/src/c.py"}, "c" * 20),
        ],
    )

    report = BENCH.repeats_report(BENCH.load_steps(tmp_path))

    (task,) = report["tasks"]
    assert task["task"] == "t1"
    assert task["overlap"] == ["src/a.py"]
    assert task["bytes"] == 40


def test_a_shared_file_the_implementer_then_edits_is_not_avoidable(tmp_path: Path) -> None:
    _step_files(
        tmp_path,
        "lead",
        "lead",
        "t1",
        [("read", {"path": "src/a.py"}, "a" * 40), ("read", {"path": "tests/t.py"}, "t" * 30)],
    )
    _step_files(
        tmp_path,
        "impl",
        "implementer",
        "t1",
        [
            ("read", {"path": "src/a.py"}, "a" * 40),
            ("read", {"path": "tests/t.py"}, "t" * 30),
            ("edit", {"path": "src/a.py", "old_string": "a", "new_string": "b"}, "ok"),
        ],
    )

    (task,) = BENCH.repeats_report(BENCH.load_steps(tmp_path))["tasks"]

    assert task["overlap"] == ["src/a.py", "tests/t.py"]
    assert task["avoidable"] == ["tests/t.py"]
    assert task["avoidableBytes"] == 30
