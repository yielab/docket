"""``docket pod test <prompt>`` runs a prompt's tests file against a model through the real chat
backend and records the result once per model and prompt hash (model-profiles.spec.md, "Prompt
variants and the floor"). The model is a loopback server speaking the OpenAI-compatible wire.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from tests.support.cli import pod_cli
from tests.support.home import register_local_provider
from tests.support.model_server import FakeModel, say

from docket.kernel.home import current_home
from docket.teams import prompt_tests, prompts

SUBJECT = "docket.interfaces.cli.commands.pod_prompt"

_MODEL = "loopback/e2e-model"
_PROMPT = (
    "---\nkind: prompt\nname: reviewer\nversion: 1.0.0\nlayer: hop\nfor: reviewer\n"
    "output: handoff/v1\ntests: reviewer.tests.yaml\n---\nYou are the Reviewer.\n"
)
_TESTS = """
cases:
  - name: approves a clean diff
    input: "diff: nothing changed"
    assert:
      - calledHandoff: true
"""


def _serve(model: FakeModel) -> None:
    """Make the catalog's keyless ``loopback`` provider answer from *model*."""
    register_local_provider(
        current_home().root, "loopback", [{"id": "e2e-model"}], base_url=model.base_url
    )


@pytest.fixture()
def reviewer() -> str:
    """An operator-scope ``hop/reviewer`` with a tests file; returns its text hash."""
    directory = current_home().prompts_dir / "hop"
    directory.mkdir(parents=True)
    (directory / "reviewer.md").write_text(_PROMPT, encoding="utf-8")
    (directory / "reviewer.tests.yaml").write_text(_TESTS, encoding="utf-8")
    return prompts.resolve_prompt("hop", "reviewer").sha256


def test_a_model_that_never_calls_handoff_fails_and_the_result_is_recorded_once(
    reviewer: str, fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(sequence=[say("APPROVE")])
    _serve(model)

    first = pod_cli("test", "hop/reviewer", "--model", _MODEL)

    assert first.exit_code == 1, first.output
    assert prompt_tests.recorded(_MODEL, reviewer) == {
        "prompt": "hop/reviewer",
        "result": "fail",
        "cases": 1,
        "failed": ["approves a clean diff"],
    }
    assert model.requests[0].tools == ["handoff"]
    on_disk = json.loads((current_home().state_dir / "prompt-tests.json").read_text())
    assert on_disk["results"][_MODEL][reviewer]["result"] == "fail"

    second = pod_cli("test", "hop/reviewer", "--model", _MODEL)

    assert second.exit_code == 1, second.output
    assert "recorded" in second.output
    assert len(model.requests) == 1


def test_force_runs_again_and_replaces_the_record(
    reviewer: str, fake_model: Callable[..., FakeModel]
) -> None:
    from tests.support.model_server import call

    model = fake_model(sequence=[say("APPROVE"), call("handoff")])
    _serve(model)
    assert pod_cli("test", "hop/reviewer", "--model", _MODEL).exit_code == 1

    forced = pod_cli("test", "hop/reviewer", "--model", _MODEL, "--force")

    assert forced.exit_code == 0, forced.output
    recorded = prompt_tests.recorded(_MODEL, reviewer)
    assert recorded is not None and recorded["result"] == "pass"
    assert len(model.requests) == 2


def test_a_prompt_with_no_tests_file_exits_two() -> None:
    result = pod_cli("test", "hop/reviewer", "--model", _MODEL)

    assert result.exit_code == 2, result.output
    assert "no tests file" in result.output
