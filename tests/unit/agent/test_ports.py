"""Agent identity: prompt composition from the workspace identity files.

The display name is a pure function of docket metadata (name → role).
"""

from __future__ import annotations

import dataclasses

import pytest

from docket.agent import ports as _ports
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.agent.ports"

# ── estimate_tokens ──────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string_is_zero_tokens(self) -> None:
        assert _ports.estimate_tokens("") == 0

    def test_uses_the_documented_bytes_per_token_ratio(self) -> None:
        text = "x" * 40
        assert (
            _ports.estimate_tokens(text)
            == len(text.encode("utf-8")) // current_home().context_bytes_per_token
        )

    def test_reuses_the_existing_config_ratio_not_a_second_one(self) -> None:
        """The whole point of reusing `Home.context_bytes_per_token` (rather than inventing a second ratio) is that changing the one config value changes both `maintain check`'s and this module's estimate together."""
        text = "y" * 100
        before = _ports.estimate_tokens(text)
        with use_home(dataclasses.replace(current_home(), context_bytes_per_token=10)):
            after = _ports.estimate_tokens(text)
        assert before == 25
        assert after == 10

    def test_utf8_multibyte_text_counted_in_bytes_not_characters(self) -> None:
        # "é" is 2 bytes in UTF-8 -- the estimate must reflect that, not the
        # 1-character length Python's `len()` would report.
        text = "é" * 8  # 16 bytes
        assert _ports.estimate_tokens(text) == 16 // current_home().context_bytes_per_token


class TestRaiseKey:
    """The one value the stop message's ``raise`` tail and the hop's ``raise`` field both read."""

    @pytest.mark.parametrize(
        ("bound", "source", "expected"),
        [
            ("rounds", "default", "AGENT_LOOP_MAX_ITERATIONS"),
            ("toolCalls", "default", "AGENT_LOOP_MAX_TOOL_CALLS"),
            ("time", "step", "timeout"),
            ("time", "pod", "turnTimeoutS"),
            ("time", "default", "AGENT_LOOP_WALL_CLOCK_TIMEOUT_S"),
            ("tokens", "task", "maxTokens"),
            ("tokens", "pod_budget", "budgetTokens"),
            ("tokens", "default", "AGENT_LOOP_TOKEN_BUDGET"),
        ],
    )
    def test_each_owner_names_its_own_key(self, bound: str, source: str, expected: str) -> None:
        assert _ports.raise_key(bound, source) == expected  # type: ignore[arg-type]
        assert _ports.BudgetStop(bound, 1, 1, source).raise_key == expected  # type: ignore[arg-type]
