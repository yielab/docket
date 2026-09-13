"""Local provider registration (`core/provider.py`).

Covers the public ``PROVIDER_CREDENTIAL_NAMES`` table -- the single
definition shared with ``edges/adapters/llm.py`` so a provider added to
one reader is not silently missing from the other.
"""

from __future__ import annotations

from docket.core import provider as _provider
from docket.edges.adapters import llm as _llm

SUBJECT = "docket.core.provider"


class TestProviderCredentialNames:
    def test_adapter_reads_the_same_object(self) -> None:
        assert _llm._PROVIDER_CREDENTIAL_NAMES is _provider.PROVIDER_CREDENTIAL_NAMES

    def test_five_known_providers(self) -> None:
        assert set(_provider.PROVIDER_CREDENTIAL_NAMES) == {
            "anthropic",
            "openai",
            "google",
            "openrouter",
            "ai-gateway",
        }
