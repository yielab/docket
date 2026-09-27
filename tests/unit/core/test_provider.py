"""The provider catalog (`core/provider.py`).

Covers ``load_provider_document`` (the `kind: provider` document loader,
specs/functional/model-profiles.spec.md "Provider catalog") and a structural guarantee: every
built-in provider docket knows is a document under ``templates/providers/``, and no other module
holds a provider-name literal in a table of its own (ADR 0011's "seven tables, seven
populations" problem). That guarantee is checked by an AST scan rather than a fixed provider
list, so it keeps holding as the catalog grows.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import provider as _provider

SUBJECT = "docket.core.provider"

_LITERAL_PROVIDER_NAMES = ("anthropic", "openai")


class TestNoProviderNameLiteralOutsideTheCatalog:
    """A provider's identity is a document under ``templates/providers/`` plus this module's
    loader, never a hand-kept table: every base URL, credential name, preset and key prefix is
    a function over the loaded catalog elsewhere, so no other literal should name one."""

    def test_no_dict_or_tuple_literal_names_a_provider_outside_provider_py(self) -> None:
        offenders: list[str] = []
        src_root = Path(_cfg.__file__).resolve().parent
        for path in sorted(src_root.rglob("*.py")):
            if path == Path(_provider.__file__).resolve():
                continue
            if "templates" in path.parts:
                continue
            rel = str(path.relative_to(src_root))
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.Dict, ast.Tuple)):
                    continue
                elements = node.values if isinstance(node, ast.Dict) else node.elts
                keys = node.keys if isinstance(node, ast.Dict) else ()
                strings = [
                    n.value
                    for n in (*elements, *keys)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                ]
                if any(s in _LITERAL_PROVIDER_NAMES for s in strings):
                    offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], f"provider-name literal(s) outside core/provider.py: {offenders}"


class TestBuiltinCatalog:
    def test_anthropic_resolves_on_a_fresh_home(self) -> None:
        # The autouse `_isolate_docket_home` fixture (tests/conftest.py) already points
        # PROVIDERS_FILE/FLEET_FILE at an empty tmp home -- the global scope is empty here,
        # so this only passes once the built-in `anthropic` document is found.
        assert _provider.load_catalog().get("anthropic") is not None

    def test_every_built_in_document_loads(self) -> None:
        directory = _cfg.PROVIDER_TEMPLATES_DIR
        files = sorted(directory.glob("*.yaml"))
        assert files, f"no built-in provider documents found in {directory}"
        for path in files:
            spec = _provider.load_provider_document(path)
            assert spec.name

    def test_default_model_is_the_anthropic_standard_rank(self) -> None:
        spec = _provider.load_catalog().get("anthropic")
        assert spec is not None
        preset = next(p for p in spec.presets if p.name == "anthropic")
        assert f"anthropic/{preset.ranks['standard']}" == _cfg.DEFAULT_MODEL


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

    def test_a_reserved_header_name_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad-headers.yaml"
        doc.write_text(
            "kind: provider\n"
            "name: bad\n"
            "baseUrl: https://example.com/v1\n"
            "auth: {type: none}\n"
            "headers: {Authorization: x}\n"
        )

        with pytest.raises(_provider.ProviderError) as excinfo:
            _provider.load_provider_document(doc)

        assert excinfo.value.field == "headers"
