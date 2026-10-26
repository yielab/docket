"""Agent identity: prompt composition from the workspace identity files.

The display name is a pure function of docket metadata (name → role).
"""

from __future__ import annotations

import dataclasses

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
