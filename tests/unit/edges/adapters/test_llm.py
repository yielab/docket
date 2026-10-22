"""The OpenAI-compatible adapter's `/models` limits and request bytes (`edges/adapters/llm.py`).

The four recorded `/models` bodies under `tests/fixtures/provider-models/` are the oracle for the
per-row limits field map; no test here opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from docket.core.llm import Endpoint, ModelLimits, user
from docket.core.provider import ModelRow, ProviderSpec
from docket.edges.adapters import llm

SUBJECT = "docket.edges.adapters.llm"

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


class TestEndpointLimitsPrecedence:
    @staticmethod
    def _spec(*rows: ModelRow) -> ProviderSpec:
        return ProviderSpec.model_validate(
            {
                "name": "gw",
                "baseUrl": "http://127.0.0.1:1/v1",
                "auth": {"type": "none"},
                "models": [r.model_dump(by_alias=True, exclude_none=True) for r in rows],
            }
        )

    def test_declared_beats_observed_beats_unknown_per_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import provider

        monkeypatch.setattr(
            provider,
            "observed_limits",
            lambda name, model_id: ModelLimits(32768, 9000) if model_id == "m" else None,
        )
        spec = self._spec(ModelRow(id="m", contextWindow=1000), ModelRow(id="n"))
        both = llm.endpoint_from_spec(spec, "gw", "m", "")
        assert (both.context_window_tokens, both.max_output_tokens) == (1000, 9000)
        unlisted = llm.endpoint_from_spec(spec, "gw", "n", "")
        assert (unlisted.context_window_tokens, unlisted.max_output_tokens) == (None, None)


class TestRequestBytes:
    def test_a_non_ascii_part_is_measured_as_utf8(self) -> None:
        text = "ñáé" * 100
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m")
        payload = llm.build_payload(endpoint, [user(text)])
        measured = llm.request_part_bytes(payload)["user"]
        assert measured == len(json.dumps(payload["messages"][0], ensure_ascii=False).encode())
        assert measured < len(json.dumps(payload["messages"][0]).encode())


class TestUsageDecoding:
    def test_cache_write_tokens_from_either_body_shape(self) -> None:
        openai_shape = {
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "prompt_tokens_details": {"cache_write_tokens": 4}},
        }
        anthropic_shape = {
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "cache_creation_input_tokens": 6},
        }
        assert llm.decode_response(openai_shape).usage.cache_write_tokens == 4
        assert llm.decode_response(anthropic_shape).usage.cache_write_tokens == 6
