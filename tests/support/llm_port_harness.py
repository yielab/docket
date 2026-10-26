"""Stubbed urlopen helpers for the chat-completion port tests."""

from __future__ import annotations

from docket.agent.ports import (
    Endpoint,
)

ENDPOINT = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="test-model")
