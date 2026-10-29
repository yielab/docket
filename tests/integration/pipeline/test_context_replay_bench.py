"""The context replay bench: baseline numbers, projection hook and the shape-preserving anonymizer."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

SUBJECT = "docket.pipeline.domain.plan"

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "maint" / "context_replay.py"
FIXTURES = REPO / "tests" / "fixtures" / "context-replay" / "v1"
REAL = Path(os.environ.get("CONTEXT_REPLAY_REAL_DIR", REPO / "internal-docs" / "context-replay"))

STEPS = ["critic", "implementer-a", "implementer-b", "researcher"]
COUNTED_OLD = {
    "critic": 101_292,
    "implementer-a": 101_248,
    "implementer-b": 84_340,
    "researcher": 82_383,
}


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_context_replay_bench", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BENCH = _load()


def _rows() -> dict[str, object]:
    return {row.name: row for row in BENCH.measure(BENCH.load_steps(FIXTURES))}


def test_fixture_directory_holds_the_four_generic_steps() -> None:
    names = sorted(p.name.removesuffix(".session.json") for p in FIXTURES.glob("*.session.json"))
    assert names == STEPS
    for name in STEPS:
        assert (FIXTURES / f"{name}.llm_calls.jsonl").is_file()


def test_baseline_reproduces_the_measured_counted_tokens() -> None:
    rows = _rows()
    assert {n: r.counted_old for n, r in rows.items()} == COUNTED_OLD
    assert sum(r.counted_old for r in rows.values()) == 369_263
    assert max(r.largest for r in rows.values()) == 25_806


def test_baseline_new_rule_subtracts_cache_reads() -> None:
    rows = _rows()
    assert {n: r.counted_new for n, r in rows.items()} == {
        "critic": 101_292,
        "implementer-a": 31_229,
        "implementer-b": 18_664,
        "researcher": 18_641,
    }
    assert rows["critic"].cached == 0


def test_baseline_budget_status_names_two_overruns_and_one_refused_next_call() -> None:
    status = {n: r.status_old for n, r in _rows().items()}
    assert status == {
        "critic": "OVER",
        "implementer-a": "OVER",
        "implementer-b": "REFUSED-NEXT",
        "researcher": "ok",
    }
    assert {r.status_new for r in _rows().values()} <= {"ok", "OVER"}


def test_critic_final_reply_is_reported_discarded_with_no_verdict() -> None:
    rows = _rows()
    assert rows["critic"].final == "discarded"
    assert rows["researcher"].final == "kept"
    assert all(r.verdict is None for r in rows.values())


def test_verdict_line_in_a_kept_final_reply_is_parsed() -> None:
    session = {
        "messages": [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "done\nAPPROVE\n", "toolCalls": []},
        ],
        "usage": {},
    }
    call = {"agent_role": "critic", "payload": {"inputTokens": 5, "outputTokens": 2}}
    step = BENCH.Step("s", session, [call])
    assert BENCH.measure([step])[0].verdict == "approve"


def test_cli_prints_the_table_and_total(capsys: pytest.CaptureFixture[str]) -> None:
    assert BENCH.main([str(FIXTURES)]) == 0
    out = capsys.readouterr().out
    assert "369,263" in out
    for name in STEPS:
        assert name in out


def test_baseline_policy_reprojects_to_the_measured_input() -> None:
    steps = BENCH.load_steps(FIXTURES)
    for step, row in zip(steps, BENCH.measure(steps), strict=True):
        proj = BENCH.project(step, BENCH.POLICIES["baseline"])
        assert proj.sent == pytest.approx(row.sent, abs=len(step.calls))


def test_a_shrinking_policy_projects_fewer_sent_tokens_and_is_labelled_estimate() -> None:
    def drop_tool_bodies(messages: list[dict]) -> list[dict]:
        return [
            {**m, "content": m["content"][:100]} if m["role"] == "tool" else m for m in messages
        ]

    steps = BENCH.load_steps(FIXTURES)
    base = BENCH.measure(steps)
    BENCH.POLICIES["shrink"] = drop_tool_bodies
    try:
        for step, row in zip(steps, base, strict=True):
            assert BENCH.project(step, BENCH.POLICIES["shrink"]).sent < row.sent
        text = BENCH.render_projection(steps, ["shrink"])
    finally:
        del BENCH.POLICIES["shrink"]
    assert "estimate" in text


def _synthetic_session() -> dict:
    root = "/srv/secretproject/tasks/abc123"
    return {
        "sessionKey": "agent:secretproject:abc123",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:01Z",
        "usage": {"inputTokens": 10, "outputTokens": 2, "cachedTokens": 4, "turns": 1},
        "messages": [
            {"role": "user", "content": "Plan the Zanzibar quarterly campaign, día uno"},
            {
                "role": "assistant",
                "content": "Looking at the Zanzibar files",
                "toolCalls": [
                    {
                        "id": "call_991",
                        "name": "read",
                        "arguments": json.dumps({"path": f"{root}/a.md", "offset": 3}),
                    }
                ],
                "toolCallId": "",
                "name": "",
            },
            {
                "role": "tool",
                "content": f"{root}/a.md\n{root}/b.md\nAPPROVE of Zanzibar",
                "toolCalls": [],
                "toolCallId": "call_991",
                "name": "read",
            },
            {
                "role": "assistant",
                "content": "The Zanzibar notes are fine.\nAPPROVE - Zanzibar\n",
                "toolCalls": [],
                "toolCallId": "",
                "name": "",
            },
        ],
    }


def _anon_one(tmp_path: Path, tag: str) -> tuple[dict, dict]:
    src = tmp_path / f"in-{tag}"
    src.mkdir()
    session = _synthetic_session()
    (src / "secretproject--critic--x.session.json").write_text(json.dumps(session))
    call = {
        "ts": "2026-01-01T00:00:00Z",
        "project": "secretproject",
        "session_id": "agent:secretproject:t",
        "agent_role": "critic",
        "event_type": "llm_call",
        "task_id": "t-1",
        "payload": {"model": "m", "inputTokens": 10, "outputTokens": 2, "cachedTokens": 4},
        "duration_ms": 5,
    }
    (src / "secretproject--critic--x.llm_calls.jsonl").write_text(json.dumps(call) + "\n")
    out = tmp_path / f"out-{tag}"
    BENCH.anonymize(src, out)
    got = json.loads((out / "critic.session.json").read_text())
    return session, got


def test_anonymizer_keeps_shape_and_drops_text(tmp_path: Path) -> None:
    before, after = _anon_one(tmp_path, "a")
    blob = json.dumps(after)
    for secret in ("Zanzibar", "secretproject", "abc123", "quarterly"):
        assert secret not in blob
    assert after["usage"] == before["usage"]
    assert [m["role"] for m in after["messages"]] == [m["role"] for m in before["messages"]]
    for old, new in zip(before["messages"], after["messages"], strict=True):
        assert len(new["content"].encode()) == len(old["content"].encode())
        assert new.get("name") == old.get("name")
    call = after["messages"][1]["toolCalls"][0]
    assert call["name"] == "read"
    assert sorted(json.loads(call["arguments"])) == ["offset", "path"]
    assert after["messages"][3]["content"].splitlines()[1].startswith("APPROVE")
    assert "APPROVE" not in after["messages"][2]["content"]


def test_anonymizer_is_deterministic_and_keeps_a_repeated_prefix(tmp_path: Path) -> None:
    _, first = _anon_one(tmp_path, "a")
    _, second = _anon_one(tmp_path, "b")
    assert first == second
    lines = first["messages"][2]["content"].splitlines()
    prefix_a = lines[0].rsplit("/", 1)[0]
    prefix_b = lines[1].rsplit("/", 1)[0]
    assert prefix_a == prefix_b and prefix_a.startswith("/")
    path_arg = json.loads(first["messages"][1]["toolCalls"][0]["arguments"])["path"]
    assert path_arg.rsplit("/", 1)[0] == prefix_a


def test_committed_fixtures_hold_only_filler_text() -> None:
    for name in STEPS:
        session = json.loads((FIXTURES / f"{name}.session.json").read_text())
        for message in session["messages"]:
            body = message["content"]
            for line in body.splitlines():
                if re.match(r"\s*(APPROVE|REJECT|REQUEST-CHANGES|PASS|FAIL)\b", line):
                    continue
                assert not re.search(r"[A-Z0-9]", line), (name, line[:80])
            for call in message.get("toolCalls", []):
                args = json.loads(call["arguments"])
                assert all(
                    not re.search(r"[A-Z0-9]", v) for v in args.values() if isinstance(v, str)
                )


@pytest.mark.skipif(not REAL.is_dir(), reason="the private measured sessions are not checked in")
def test_fixtures_reproduce_the_real_sessions_counted_totals() -> None:
    real = BENCH.measure(BENCH.load_steps(REAL))
    fake = BENCH.measure(BENCH.load_steps(FIXTURES))
    assert sorted(r.counted_old for r in real) == sorted(r.counted_old for r in fake)
    assert sum(r.counted_old for r in real) == 369_263


def test_the_tool_output_policy_sends_less_on_every_recorded_step() -> None:
    """Bounded tool output never makes a recorded step send more, and cuts the listing step most."""
    steps = BENCH.load_steps(FIXTURES)
    ratios = {}
    for step, row in zip(steps, BENCH.measure(steps), strict=True):
        ratios[step.name] = BENCH.project(step, BENCH.POLICIES["tool-output"]).sent / row.sent
    assert all(ratio < 1.0 for ratio in ratios.values()), ratios
    assert ratios["implementer-a"] < 0.5


def test_the_finalization_policy_shares_the_whole_last_request_only_when_it_trails() -> None:
    """The modelled finalization request reuses the previous request's bytes as a trailing message."""
    steps = BENCH.load_steps(FIXTURES)
    for step in steps:
        last, _final, before, after = BENCH.finalization_prefix(step)
        assert before == 0
        assert after == last
    assert "shared after" in BENCH.render_projection(steps, [BENCH.FINALIZATION_POLICY])


def test_the_tool_surface_policy_measures_the_real_registry_per_profile() -> None:
    """The local profile offers a hop fewer, smaller tool schemas than the hosted one, for each role."""
    for role in ("lead", "implementer", "reviewer", "tester"):
        hosted_names, hosted = BENCH.hop_tool_bytes(role, "full", "full")
        local_names, local = BENCH.hop_tool_bytes(role, "minimal", "compact")
        assert set(local_names) < set(hosted_names)
        assert local < hosted
    assert "handoff" in local_names and "bash" in local_names and "write" not in local_names
    assert "implementer" in BENCH.render_projection([], [BENCH.TOOL_SURFACE_POLICY])


def test_the_hop_message_policy_bounds_the_map_to_the_named_paths() -> None:
    """A brief naming one file sends fewer task-block bytes than the whole-tree map did."""
    old, new = BENCH.hop_task_block(
        "change the prompt", f"edit {BENCH._NAMED_PATH}", BENCH._repo_root()
    )

    assert len(new.encode()) < len(old.encode())
    assert BENCH._NAMED_PATH in new and "`glob`" in new
    assert BENCH._repo_root() not in new
    assert "names a file" in BENCH.render_projection(
        BENCH.load_steps(FIXTURES), [BENCH.HOP_MESSAGE_POLICY]
    )
