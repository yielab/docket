"""The OpenAI-compatible adapter's `/models` limits and request bytes (`models/adapters/openai_http.py`).

The four recorded `/models` bodies under `tests/fixtures/provider-models/` are the oracle for the
per-row limits field map; no test here opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from docket.agent.llm import Endpoint, ModelLimits
from docket.models.adapters import openai_http as llm

SUBJECT = "docket.models.adapters.openai_http"

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "provider-models"


def _body(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class _Response:
    def __init__(self, body: str, status: int = 200) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def _probe(monkeypatch: pytest.MonkeyPatch, body: str) -> llm.ProbeResult:
    monkeypatch.setattr(llm, "open_same_origin", lambda *a, **k: _Response(body))
    return llm.probe_models(Endpoint(base_url="http://127.0.0.1:1/v1", model_id="x"))


class TestRecordedModelsBodies:
    def test_llamacpp_window_is_n_ctx_never_the_training_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _probe(monkeypatch, _body("llamacpp"))
        assert result.limits == {"/models/local-model.gguf": ModelLimits(32768, None)}

    def test_anthropic_window_and_output_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _probe(monkeypatch, _body("anthropic"))
        assert result.limits["claude-haiku-5-5"] == ModelLimits(1_000_000, 128_000)
        assert result.limits["claude-sonnet-4-6"] == ModelLimits(1_000_000, 128_000)

    def test_gateway_limits_and_a_zero_row_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _probe(monkeypatch, _body("gateway"))
        assert result.limits["anthropic/claude-sonnet-4.5"] == ModelLimits(1_000_000, 64_000)
        assert result.limits["anthropic/claude-haiku-4.5"] == ModelLimits(200_000, 64_000)
        assert result.limits["alibaba/wan-v2.5-t2v-preview"] == ModelLimits(None, None)

    def test_openrouter_limits_and_a_null_output_cap_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _probe(monkeypatch, _body("openrouter"))
        assert result.limits["openrouter/free"] == ModelLimits(200_000, None)
        assert result.limits["minimax/minimax-m3.1-flash:free"] == ModelLimits(1_000_000, 524_288)

    def test_every_advertised_id_has_an_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("anthropic", "gateway", "llamacpp", "openrouter"):
            result = _probe(monkeypatch, _body(name))
            assert set(result.limits) == set(result.model_ids)

    @pytest.mark.parametrize("value", [None, 0, -5, "32768", 1.5, True, [1]])
    def test_a_value_that_is_not_a_positive_integer_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch, value: Any
    ) -> None:
        body = json.dumps({"data": [{"id": "m", "context_window": value, "max_tokens": value}]})
        assert _probe(monkeypatch, body).limits == {"m": ModelLimits(None, None)}

    def test_an_unrecognised_body_yields_no_limits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _probe(monkeypatch, "[]").limits == {}
        assert _probe(monkeypatch, "not json").limits == {}
