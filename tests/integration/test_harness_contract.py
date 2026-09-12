"""The harness-mode wire contract: generated schema and committed NDJSON fixtures."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from docket.core import harness

SUBJECT = "docket.core.harness"

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "contracts" / "harness-v1" / "schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "harness-contract" / "v1"


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


def test_an_unknown_version_fixture_fails_closed() -> None:
    result_line = (FIXTURES_DIR / "ok.ndjson").read_text(encoding="utf-8").splitlines()[-1]
    payload = json.loads(result_line)
    payload["v"] = "0.9.0"
    with pytest.raises(Exception, match="unsupported harness contract version"):
        harness.HarnessResult.model_validate(payload)
