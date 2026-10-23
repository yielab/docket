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
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import provider as _provider
from docket.core.llm import ModelLimits
from docket.edges.adapters.llm import ProbeResult
from docket.kernel.clock import use_clock

SUBJECT = "docket.core.provider"

_LITERAL_PROVIDER_NAMES = ("anthropic", "openai")


class _Day:
    """A clock stopped at midnight UTC of the given day in January 1970."""

    def __init__(self, day: int) -> None:
        self._moment = datetime(1970, 1, day, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def monotonic(self) -> float:
        return self._moment.timestamp()


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

    def test_anthropic_sends_the_version_header_its_models_route_requires(self) -> None:
        spec = _provider.load_catalog().get("anthropic")
        assert spec is not None
        assert spec.headers.get("anthropic-version") == "2023-06-01"

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


def _spec(name: str = "gw", *rows: _provider.ModelRow) -> _provider.ProviderSpec:
    return _provider.ProviderSpec(
        name=name,
        baseUrl="http://127.0.0.1:1/v1",
        auth=_provider.AuthSpec(type="none"),
        models=list(rows),
    )


def _probe(*limits: tuple[str, int | None, int | None], status: int = 200) -> ProbeResult:
    return ProbeResult(
        status=status,
        model_ids=[model_id for model_id, _, _ in limits],
        limits={model_id: ModelLimits(window, out) for model_id, window, out in limits},
    )


class TestShippedTemplatesDeclareNoLimit:
    def test_no_built_in_row_carries_a_window_or_an_output_cap(self) -> None:
        for path in sorted(_cfg.PROVIDER_TEMPLATES_DIR.glob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            assert "contextWindow" not in text
            assert "maxTokens" not in text

    def test_prices_and_presets_stay(self) -> None:
        spec = _provider.load_catalog().get("anthropic")
        assert spec is not None
        assert spec.prices_as_of
        assert any(row.price is not None for row in spec.models)
        assert spec.presets


class TestObservedLimitsStore:
    def test_record_writes_the_documented_shape_through_the_store(self) -> None:
        _provider.record_observed_models(_spec(), _probe(("m", 32768, None), ("n", None, 4096)))
        on_disk = json.loads(_cfg.PROVIDER_MODELS_FILE.read_text(encoding="utf-8"))
        entry = on_disk["providers"]["gw"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["observedAt"])
        assert entry["models"] == {
            "m": {"contextWindow": 32768, "maxTokens": None},
            "n": {"contextWindow": None, "maxTokens": 4096},
        }

    def test_reads_back_what_was_written_and_a_stranger_is_none(self) -> None:
        _provider.record_observed_models(_spec(), _probe(("m", 32768, 2048)))
        assert _provider.observed_limits("gw", "m") == ModelLimits(32768, 2048)
        assert _provider.observed_limits("gw", "never-seen") is None
        assert _provider.observed_limits("other", "m") is None
        assert _provider.observed_at("other") == ""

    def test_a_probe_that_is_not_a_200_records_nothing_and_keeps_the_old_observation(self) -> None:
        _provider.record_observed_models(_spec(), _probe(("m", 100, None)))
        _provider.record_observed_models(_spec(), ProbeResult(status=None, transport_error="down"))
        _provider.record_observed_models(_spec(), _probe(status=401))
        assert _provider.observed_limits("gw", "m") == ModelLimits(100, None)

    def test_a_new_observation_replaces_the_providers_models_and_keeps_other_providers(
        self,
    ) -> None:
        _provider.record_observed_models(_spec("a"), _probe(("m", 1, 1)))
        _provider.record_observed_models(_spec("b"), _probe(("m", 2, 2)))
        _provider.record_observed_models(_spec("a"), _probe(("n", 3, 3)))
        assert _provider.observed_limits("a", "m") is None
        assert _provider.observed_limits("a", "n") == ModelLimits(3, 3)
        assert _provider.observed_limits("b", "m") == ModelLimits(2, 2)


class TestResolveLimits:
    def test_declared_beats_observed_beats_unknown_per_limit(self) -> None:
        spec = _spec("gw", _provider.ModelRow(id="m", contextWindow=1000))
        _provider.record_observed_models(spec, _probe(("m", 32768, 9000)))
        got = _provider.resolve_limits(spec, "m")
        assert (got.context_window, got.context_window_source) == (1000, "declared")
        assert (got.max_output, got.max_output_source) == (9000, "observed")
        assert got.source == "declared"
        assert got.observed_at != ""

    def test_a_never_observed_undeclared_model_is_unknown_not_a_number(self) -> None:
        spec = _spec("gw", _provider.ModelRow(id="m"))
        got = _provider.resolve_limits(spec, "m")
        assert (got.context_window, got.max_output) == (None, None)
        assert (got.context_window_source, got.max_output_source) == ("unknown", "unknown")
        assert got.source == "unknown"
        assert got.observed_at == ""

    def test_an_observed_null_limit_stays_unknown(self) -> None:
        spec = _spec("gw", _provider.ModelRow(id="m"))
        _provider.record_observed_models(spec, _probe(("m", 4096, None)))
        got = _provider.resolve_limits(spec, "m")
        assert (got.context_window_source, got.max_output_source) == ("observed", "unknown")


class TestRegistrationRecordsWhatTheProbeSaw:
    def test_register_provider_records_the_probe_but_a_refused_one_does_not(self) -> None:
        spec = _spec("gw", _provider.ModelRow(id="m"))
        _provider.register_provider(spec, probe=_probe(("m", 32768, None)))
        assert _provider.observed_limits("gw", "m") == ModelLimits(32768, None)
        down = _spec("down")
        _provider.register_provider(down, probe=ProbeResult(status=None, transport_error="x"))
        assert _provider.observed_at("down") == ""


class TestRefreshObservedModelsDue:
    @pytest.fixture()
    def probes(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []

        def fake(spec: _provider.ProviderSpec) -> ProbeResult:
            seen.append(spec.name)
            return _probe(("m", 7000, None))

        monkeypatch.setattr(_provider, "probe_spec", fake)
        return seen

    def test_a_fresh_home_with_only_built_ins_probes_nothing(self, probes: list[str]) -> None:
        assert _provider.refresh_observed_models_due() == []
        assert probes == []

    def test_a_registered_provider_is_probed_once_a_day(self, probes: list[str]) -> None:
        _provider.save_provider(_spec("gw"))
        assert _provider.refresh_observed_models_due() == ["gw"]
        assert _provider.observed_limits("gw", "m") == ModelLimits(7000, None)
        assert _provider.refresh_observed_models_due() == []
        assert probes == ["gw"]

    def test_a_stale_observation_is_refreshed(
        self, probes: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _provider.save_provider(_spec("gw"))
        with use_clock(_Day(1)):
            _provider.refresh_observed_models_due()
        assert _provider.observed_at("gw") == "1970-01-01"
        monkeypatch.setattr(_provider, "probe_spec", lambda spec: _probe(("m", 9, None)))
        with use_clock(_Day(2)):
            assert _provider.refresh_observed_models_due() == ["gw"]
        assert _provider.observed_limits("gw", "m") == ModelLimits(9, None)

    def test_a_failing_probe_is_skipped_without_stopping_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _provider.save_provider(_spec("aa"))
        _provider.save_provider(_spec("bb"))

        def fake(spec: _provider.ProviderSpec) -> ProbeResult:
            if spec.name == "aa":
                raise RuntimeError("boom")
            return _probe(("m", 5, None))

        monkeypatch.setattr(_provider, "probe_spec", fake)
        assert _provider.refresh_observed_models_due() == ["bb"]


class TestRegisterRefusesAnUnusableRankSource:
    def test_an_anthropic_document_without_its_anchors_is_not_registered(self) -> None:
        from docket.kernel.errors import DocumentError

        builtin = _provider.load_catalog().get("anthropic")
        assert builtin is not None
        broken = _provider.ProviderSpec.model_validate(
            {**builtin.model_dump(by_alias=True), "presets": []}
        )

        with pytest.raises(DocumentError) as excinfo:
            _provider.register_provider(broken, probe=ProbeResult(status=200))

        assert "economy" in str(excinfo.value)
        assert not _cfg.PROVIDERS_FILE.exists()
