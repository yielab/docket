"""The harness-mode wire contract: generated schema and committed NDJSON fixtures."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

from docket.core import agent_loop as _agent_loop
from docket.core import harness
from docket.core.runtime_driver import TurnResult, UsageReport, UsageTotals
from docket.core.tools import ToolResult

SUBJECT = "docket.core.harness"

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "harness-v1" / "schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "harness-contract" / "v1"
SCHEMA_V11_PATH = REPO_ROOT / "docs" / "contracts" / "harness-v1.1" / "schema.json"
FIXTURES_V11_DIR = REPO_ROOT / "tests" / "fixtures" / "harness-contract" / "v1.1"


def _load_schema_script() -> types.ModuleType:
    script = REPO_ROOT / "scripts" / "harness_schema.py"
    spec = importlib.util.spec_from_file_location("_w30c3_harness_schema", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_schema_is_byte_identical_to_the_committed_file() -> None:
    module = _load_schema_script()
    assert module.render() == SCHEMA_PATH.read_text(encoding="utf-8")


def test_generated_schema_is_valid_json_covering_both_models() -> None:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(document["definitions"]) == {"HarnessEvent", "HarnessResult"}
    assert document["version"] == harness.HARNESS_CONTRACT_VERSION


@pytest.mark.parametrize("name", ["ok", "blocked", "cancelled", "refused"])
def test_every_fixture_line_validates_and_ends_on_a_result(name: str) -> None:
    lines = (FIXTURES_DIR / f"{name}.ndjson").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines[:-1]:
        harness.HarnessEvent.model_validate_json(line)
    harness.HarnessResult.model_validate_json(lines[-1])


# Unlike the two tests above, which validate through the Pydantic models directly, this
# drives the committed file itself as JSON Schema -- the artifact an external consumer
# actually pins against, which the Pydantic-only checks never exercise.
def _validator_for(definition: str) -> Draft202012Validator:
    """Build a validator against one `#/definitions/<name>` of the committed file."""
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = {**document, "$ref": f"#/definitions/{definition}"}
    return Draft202012Validator(schema)


@pytest.mark.parametrize("name", ["ok", "blocked", "cancelled", "refused"])
def test_every_fixture_line_validates_against_the_committed_json_schema(name: str) -> None:
    lines = (FIXTURES_DIR / f"{name}.ndjson").read_text(encoding="utf-8").splitlines()
    assert lines
    event_validator = _validator_for("HarnessEvent")
    result_validator = _validator_for("HarnessResult")
    for line in lines[:-1]:
        event_validator.validate(json.loads(line))
    result_validator.validate(json.loads(lines[-1]))


def test_an_invalid_status_fails_the_committed_json_schema() -> None:
    result_line = (FIXTURES_DIR / "ok.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(result_line)
    payload["status"] = "not-a-real-status"
    with pytest.raises(ValidationError):
        _validator_for("HarnessResult").validate(payload)


def test_an_unknown_version_fixture_fails_closed() -> None:
    result_line = (FIXTURES_DIR / "ok.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(result_line)
    payload["v"] = "0.9.0"
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessResult.model_validate(payload)


# ── Contract 1.1 ─────────────────────────────────────────────────────────────
#
# RED on the base: docs/contracts/harness-v1.1/schema.json does not exist yet,
# so this fails until the schema is generated and committed.


def test_generated_v11_schema_is_byte_identical_to_the_committed_file() -> None:
    module = _load_schema_script()
    assert module.render_v11() == SCHEMA_V11_PATH.read_text(encoding="utf-8")


def test_generated_v11_schema_is_valid_json_covering_the_v11_models() -> None:
    document = json.loads(SCHEMA_V11_PATH.read_text(encoding="utf-8"))
    assert set(document["definitions"]) == {"HarnessEvent", "HarnessResult", "AnswerLine"}
    assert document["version"] == harness.HARNESS_CONTRACT_V11


def _validator_for_v11(definition: str) -> Draft202012Validator:
    """Build a validator against one ``#/definitions/<name>`` of the v1.1 file."""
    document = json.loads(SCHEMA_V11_PATH.read_text(encoding="utf-8"))
    schema = {**document, "$ref": f"#/definitions/{definition}"}
    return Draft202012Validator(schema)


@pytest.mark.parametrize("name", ["ok-files", "asked-answered", "cancelled-process", "recipe-ok"])
def test_every_v11_result_fixture_line_validates_and_ends_on_a_result(name: str) -> None:
    lines = (FIXTURES_V11_DIR / f"{name}.ndjson").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines[:-1]:
        harness.HarnessEventV11.model_validate_json(line)
    harness.HarnessResultV11.model_validate_json(lines[-1])


@pytest.mark.parametrize("name", ["ok-files", "asked-answered", "cancelled-process", "recipe-ok"])
def test_every_v11_result_fixture_line_validates_against_the_committed_json_schema(
    name: str,
) -> None:
    lines = (FIXTURES_V11_DIR / f"{name}.ndjson").read_text(encoding="utf-8").splitlines()
    assert lines
    event_validator = _validator_for_v11("HarnessEvent")
    result_validator = _validator_for_v11("HarnessResult")
    for line in lines[:-1]:
        event_validator.validate(json.loads(line))
    result_validator.validate(json.loads(lines[-1]))


def test_ok_files_fixture_carries_a_non_empty_files_list() -> None:
    result_line = (
        (FIXTURES_V11_DIR / "ok-files.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    )
    result = harness.HarnessResultV11.model_validate_json(result_line)
    assert result.files
    assert result.files[0].op == "write"


def test_recipe_ok_fixture_carries_a_task_block() -> None:
    result_line = (
        (FIXTURES_V11_DIR / "recipe-ok.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    )
    result = harness.HarnessResultV11.model_validate_json(result_line)
    assert result.task is not None
    assert result.task.status == "done"


def test_cancelled_process_fixture_carries_a_signal_on_process_exited() -> None:
    lines = (FIXTURES_V11_DIR / "cancelled-process.ndjson").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in lines[:-1]]
    exited = [e for e in events if e["event_type"] == "process_exited"]
    assert exited and exited[0]["payload"]["signal"] == "SIGKILL"


def test_every_answer_line_validates_as_an_answer_line() -> None:
    lines = (FIXTURES_V11_DIR / "answer-lines.ndjson").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        harness.AnswerLine.model_validate_json(line)


def test_an_answer_line_with_both_targets_set_is_rejected() -> None:
    with pytest.raises(Exception, match="exactly one"):
        harness.Answer(approvalToken="a", questionId="b", action="accept")


def test_an_answer_line_with_neither_target_set_is_rejected() -> None:
    with pytest.raises(Exception, match="exactly one"):
        harness.Answer(action="accept")


def test_a_v11_result_naming_the_v10_version_fails_closed() -> None:
    payload = json.loads(
        (FIXTURES_V11_DIR / "ok-files.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    )
    payload["v"] = "1.0.0"
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessResultV11.model_validate(payload)


# The one thing neither card that produced this seam could test on its own.
# core/agent_loop.py renders the refusal as a string and core/harness.py parses
# it back, with no shared type between them, so each half can pass its own
# suite while the pair silently produces a blocked payload of empty fields --
# which is exactly what the first merge of the two did. This drives the real
# renderer rather than a copy of its output, so a format change fails here.
class TestBlockedPayloadSurvivesTheDriverErrorRoundTrip:
    def _blocked_result(self) -> object:
        denial = ToolResult(
            ok=False,
            tool="bash",
            call_id="call-1",
            decision="deny",
            denial_kind="approval_unavailable",
            policy_id="block-destructive",
            reason="policy 'block-destructive': needs a human",
        )
        turn = TurnResult(
            False,
            "",
            0.0,
            {},
            _agent_loop.approval_unavailable_error(denial),
            failure_kind="invalid_output",
        )
        return harness.result_from(turn, UsageReport(totals=UsageTotals()), {"id": "run-1"})

    def test_every_field_arrives_populated(self) -> None:
        blocked = self._blocked_result().blocked
        assert blocked is not None
        assert blocked.tool == "bash"
        assert blocked.call_id == "call-1"
        assert blocked.policy_id == "block-destructive"
        assert blocked.denial_kind == "approval_unavailable"
        assert "needs a human" in blocked.reason

    def test_the_status_is_blocked_rather_than_a_generic_failure(self) -> None:
        assert self._blocked_result().status == "blocked"
