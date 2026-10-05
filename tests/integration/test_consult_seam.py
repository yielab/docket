"""``consult`` over the real ``docket harness run --contract 1.1`` subprocess.

Two cards exchange the question here: the consult tool builds a ``QuestionV11`` and the
harness answer router maps a ``questionId`` line back to the waiting call. Neither card's own
suite crosses both halves, so this one drives the real process, answers on stdin and validates
every stdout line against the **committed** harness v1.1 schema and the question payload against
the **committed** operator-v1.1 question schema.
"""

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
    _real_docket_home_is_untouched,  # noqa: F401 - module-scoped guard, re-used here
    _tool_call_response,
    llm_server,  # noqa: F401 - fixture, re-used here
)

SUBJECT = "docket.cli._harness_answers"

_HARNESS = REPO_ROOT / "docs" / "contracts" / "harness-v1.1" / "schema.json"
_QUESTION = REPO_ROOT / "docs" / "contracts" / "operator-v1.1" / "question.schema.json"

_CONSULT = {
    "kind": "decision",
    "message": "Which store should the cache use?",
    "options": [
        {"id": "redis", "label": "Redis", "description": "fast", "risks": ["ops cost"]},
        {"id": "sqlite", "label": "SQLite", "description": "simple"},
    ],
    "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
}


def _harness(definition: str) -> Draft202012Validator:
    document = json.loads(_HARNESS.read_text(encoding="utf-8"))
    return Draft202012Validator({**document, "$ref": f"#/definitions/{definition}"})


def test_consult_answered_by_question_id_reaches_the_model_and_every_line_validates(
    tmp_path: Path,
    llm_server: Any,  # noqa: F811
) -> None:
    server = llm_server([_tool_call_response("consult", _CONSULT), _final_response("done")])
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = _child_env(tmp_path / "home", server.base_url)
    stderr = tmp_path / "stderr.txt"
    args = [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "decide",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        "--answers",
        "stdin",
    ]

    run = _AnsweredRun(args, env, stderr)
    asked = run.wait_for_event("question_asked")
    payload = asked["event"]["payload"]
    answer = {
        "questionId": payload["questionId"],
        "action": "accept",
        "content": {"optionId": "redis"},
    }
    run.write_raw(json.dumps({"v": "1.1.0", "token": asked["token"], "answer": answer}))
    run.close_stdin()
    returncode, lines = run.finish()

    assert returncode == 0, stderr.read_text(encoding="utf-8")
    event_schema, result_schema = _harness("HarnessEvent"), _harness("HarnessResult")
    for line in lines[:-1]:
        event_schema.validate(line)
    result_schema.validate(lines[-1])
    assert lines[-1]["status"] == "ok"

    document = json.loads(_QUESTION.read_text(encoding="utf-8"))
    Draft202012Validator(document).validate(payload["question"])
    assert payload["question"]["kind"] == "decision"
    assert payload["question"]["taskId"] == asked["token"]
    assert not payload["question"]["taskId"].startswith("agent:")
    assert [o["id"] for o in payload["question"]["options"]] == ["redis", "sqlite"]

    # The chosen option, not the recommended one, is what the model's next request carries.
    assert '\\"optionId\\": \\"redis\\"' in json.dumps(server.requests[-1]["messages"])
