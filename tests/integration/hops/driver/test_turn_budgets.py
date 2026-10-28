"""A catalog row's budget shares decide where a turn's tool result is cut."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.model_server import FakeModel, Reply, Request, call, say
from tests.support.pods import write_meta_overrides as _write_meta

from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home, use_home
from docket.models import catalog as _catalog

SUBJECT = "docket.hops.application.driver"

# A local row's shares of a 32768-token window at 4 bytes a token: 2% for a tool result.
LOCAL_TOOL_OUTPUT = int(32768 * 4 * 0.02)
# What the cut's own marker paragraph adds to the cap.
MARKER = 80
PRINT = "python3 -c \"print('x' * 20000)\""


def _bash_result(
    fake_model: Callable[..., FakeModel],
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
    **row: Any,
) -> str:
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
    seen: dict[str, str] = {}

    def _finish(request: Request) -> Reply:
        seen["result"] = request.tool_result("run") or ""
        return say("done")

    server = fake_model(sequence=[call("bash", call_id="run", command=PRINT), _finish])
    _catalog.save_provider(
        _catalog.ProviderSpec.model_validate(
            {
                "name": "lab",
                "baseUrl": server.base_url,
                "auth": {"type": "none"},
                "models": [{"id": "m", "contextWindow": 32768}],
                **row,
            }
        )
    )
    _write_meta("bud-agent", role="implementer", model="lab/m", codebase=str(workspace))
    result = DocketDriver().run_turn("bud-agent", "agent:bud-agent:default", "print it", 60)
    assert result.ok, result.error
    return seen["result"]


def test_a_local_row_cuts_a_bash_result_at_its_share(
    fake_model: Callable[..., FakeModel], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "w").mkdir()

    text = _bash_result(fake_model, monkeypatch, tmp_path / "w", local=True)

    assert "[truncated:" in text
    assert len(text) <= LOCAL_TOOL_OUTPUT + MARKER, len(text)


def test_a_hosted_row_keeps_todays_cap(
    fake_model: Callable[..., FakeModel], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "w").mkdir()

    text = _bash_result(fake_model, monkeypatch, tmp_path / "w")

    assert current_home().tool_max_output_chars == 30000
    assert "[truncated:" not in text and "x" * 20000 in text


def test_a_local_row_never_goes_above_the_homes_cap(
    fake_model: Callable[..., FakeModel], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "w").mkdir()

    with use_home(dataclasses.replace(current_home(), tool_max_output_chars=1500)):
        text = _bash_result(fake_model, monkeypatch, tmp_path / "w", local=True)

    assert "[truncated:" in text and len(text) <= 1500 + MARKER, len(text)
