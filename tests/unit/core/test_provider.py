"""The provider catalog (`core/provider.py`).

Covers the public ``PROVIDER_CREDENTIAL_NAMES`` table -- the single
definition shared with ``edges/adapters/llm.py`` so a provider added to
one reader is not silently missing from the other -- and ``load_provider_document``,
the `kind: provider` document loader (specs/functional/model-profiles.spec.md "Provider
catalog").
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


class TestLoadProviderDocument:
    def test_loads_a_minimal_local_document(self, tmp_path: Path) -> None:
        doc = tmp_path / "local.yaml"
        doc.write_text(
            "kind: provider\nname: local\nbaseUrl: http://127.0.0.1:8081/v1\nlocal: true\n"
        )

        spec = _provider.load_provider_document(doc)

        assert spec.name == "local"
        assert spec.dialect == "openai-chat"
        assert spec.base_url == "http://127.0.0.1:8081/v1"
        assert spec.auth.type == "none"
        assert spec.local is True

    def test_unknown_dialect_names_the_valid_value(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: provider\n"
            "name: bad\n"
            "baseUrl: https://example.com/v1\n"
            "dialect: grpc\n"
            "auth: {type: none}\n"
        )

        with pytest.raises(_provider.ProviderError) as excinfo:
            _provider.load_provider_document(doc)

        assert excinfo.value.field == "dialect"
        assert "openai-chat" in excinfo.value.valid
