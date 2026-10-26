"""The OTLP/HTTP encoder against its golden output."""

from __future__ import annotations

import json
from pathlib import Path

from tests.support.otlp_harness import (
    _projected_spans,
)

from docket.observability.adapters import otlp_http

SUBJECT = "docket.observability.adapters.otlp_http"


_GOLDEN = Path(__file__).resolve().parents[3] / "fixtures" / "otlp-v1" / "dispatch-3-hops.json"


class TestEncodeGolden:
    def test_matches_the_committed_wire_fixture(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(),
            resource={"service.name": "docket"},
            aliases={"session.id": "langfuse.session.id"},
        )
        rendered = json.dumps(doc, sort_keys=True, indent=2) + "\n"
        assert rendered == _GOLDEN.read_text()

    def test_gen_ai_chat_span_shape(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(), resource={}, aliases={"session.id": "langfuse.session.id"}
        )
        spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        chat = next(s for s in spans if s["name"] == "gen_ai.chat")
        assert chat["kind"] == 3
        attrs = {a["key"]: a["value"] for a in chat["attributes"]}
        assert attrs["gen_ai.usage.input_tokens"] == {"intValue": "120"} or attrs[
            "gen_ai.usage.input_tokens"
        ] == {"intValue": "180"}

    def test_session_root_carries_the_aliased_attribute(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(), resource={}, aliases={"session.id": "langfuse.session.id"}
        )
        spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = next(s for s in spans if s["name"] == "docket.session")
        keys = {a["key"] for a in root["attributes"]}
        assert {"session.id", "langfuse.session.id"} <= keys
