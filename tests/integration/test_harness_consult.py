"""The ``consult`` tool through a real ``docket harness run`` process: a question on the stream,
an answer line on stdin, and the blocked v1.1 result under ``refuse``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from tests.integration.test_harness_cli import (
    REPO_ROOT,
    _AnsweredRun,
    _child_env,
    _final_response,
    _parse_ndjson,
    _real_docket_home_is_untouched,  # noqa: F401 - module-scoped guard, re-used here
    _tool_call_response,
    llm_server,  # noqa: F401 - fixture, re-used here
)

SUBJECT = "docket.cli._harness"

SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "harness-v1.1" / "schema.json"

_CONSULT = {
    "kind": "decision",
    "message": "Which store should the cache use?",
    "options": [
        {"id": "redis", "label": "Redis", "description": "fast", "risks": ["ops cost"]},
        {"id": "sqlite", "label": "SQLite", "description": "simple"},
    ],
    "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
}


def _args(workspace: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "decide",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        *extra,
    ]


def _result_validator() -> Draft202012Validator:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator({**document, "$ref": "#/definitions/HarnessResult"})


class TestConsultOnStdin:
    def test_an_answer_line_delivers_the_chosen_option_to_the_model(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811
    ) -> None:
        server = llm_server([_tool_call_response("consult", _CONSULT), _final_response("done")])
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", server.base_url)

        run = _AnsweredRun(_args(workspace, "--answers", "stdin"), env, tmp_path / "stderr.txt")
        asked = run.wait_for_event("question_asked")
        payload = asked["event"]["payload"]
        assert payload["question"]["id"] == payload["questionId"]
        answer = {
            "questionId": payload["questionId"],
            "action": "accept",
            "content": {"optionId": "redis"},
        }
        run.write_raw(json.dumps({"v": "1.1.0", "token": asked["token"], "answer": answer}))
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0, (tmp_path / "stderr.txt").read_text(encoding="utf-8")
        assert lines[-1]["status"] == "ok"
        assert '\\"optionId\\": \\"redis\\"' in json.dumps(server.requests[-1]["messages"])

    def test_an_unanswered_consult_times_out_and_the_model_decides(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811
    ) -> None:
        server = llm_server([_tool_call_response("consult", _CONSULT), _final_response("done")])
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", server.base_url)

        run = _AnsweredRun(
            _args(workspace, "--answers", "stdin", "--answer-timeout", "1"),
            env,
            tmp_path / "stderr.txt",
        )
        run.wait_for_event("question_asked")
        run.close_stdin()
        returncode, lines = run.finish()

        assert returncode == 0
        assert lines[-1]["status"] == "ok"
        assert "no answer; decide yourself" in json.dumps(server.requests[-1]["messages"])


class TestConsultUnderRefuse:
    def test_the_turn_ends_blocked_with_the_question_in_the_v11_result(
        self,
        tmp_path: Path,
        llm_server: Any,  # noqa: F811
    ) -> None:
        import subprocess
        import sys

        server = llm_server([_tool_call_response("consult", _CONSULT), _final_response("done")])
        workspace = tmp_path / "ws"
        workspace.mkdir()
        env = _child_env(tmp_path / "home", server.base_url)

        proc = subprocess.run(
            [sys.executable, "-m", "docket", "harness", *_args(workspace)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert proc.returncode == 1, proc.stderr
        lines = _parse_ndjson(proc.stdout)
        result = lines[-1]
        _result_validator().validate(result)
        assert result["status"] == "blocked"
        assert result["blocked"]["tool"] == "consult"
        assert result["question"]["kind"] == "decision"
        assert result["question"]["recommendation"]["optionId"] == "sqlite"
        assert len(server.requests) == 1
