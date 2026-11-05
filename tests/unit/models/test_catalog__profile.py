"""A catalog row's model profile: the two built-ins, the overrides, the budgets it derives."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.agent.ports import ModelLimits
from docket.kernel.home import current_home
from docket.models import catalog as _provider
from docket.models import provider_lifecycle as _lifecycle
from docket.models.application import endpoint
from docket.models.application.probe import ProbeResult

SUBJECT = "docket.models.catalog"

_LOCAL = "kind: provider\nname: lab\nbaseUrl: http://127.0.0.1:8081/v1\nlocal: true\n"
_HOSTED = "kind: provider\nname: lab\nbaseUrl: https://example.com/v1\nauth: {type: none}\n"


def _load(tmp_path: Path, text: str) -> _provider.ProviderSpec:
    doc = tmp_path / "lab.yaml"
    doc.write_text(text)
    return _provider.load_provider_document(doc)


class TestProfileOfARow:
    def test_a_local_row_without_a_profile_is_local(self, tmp_path: Path) -> None:
        profile = _provider.profile_of(_load(tmp_path, _LOCAL))

        assert profile.name == "local"
        assert (profile.tool_surface, profile.descriptions, profile.tool_choice) == (
            "minimal",
            "compact",
            "forced-on-close",
        )

    def test_any_other_row_is_hosted(self, tmp_path: Path) -> None:
        profile = _provider.profile_of(_load(tmp_path, _HOSTED))

        assert profile.name == "hosted"
        assert (profile.tool_surface, profile.descriptions, profile.tool_choice) == (
            "full",
            "full",
            "auto",
        )

    def test_a_declared_profile_beats_the_local_flag(self, tmp_path: Path) -> None:
        assert _provider.profile_of(_load(tmp_path, _LOCAL + "profile: hosted\n")).name == "hosted"
        assert _provider.profile_of(_load(tmp_path, _HOSTED + "profile: local\n")).name == "local"

    def test_no_built_in_profile_declares_sampling(self, tmp_path: Path) -> None:
        for text in (_LOCAL, _HOSTED):
            sampling = _provider.profile_of(_load(tmp_path, text)).sampling
            assert (sampling.temperature, sampling.top_p) == (None, None)

    def test_a_row_declares_sampling_and_overrides(self, tmp_path: Path) -> None:
        text = _LOCAL + (
            "sampling: {temperature: 0.7, topP: 0.8}\n"
            "toolSurface: full\ndescriptions: full\ntoolChoice: auto\n"
        )

        profile = _provider.profile_of(_load(tmp_path, text))

        assert profile.name == "local"
        assert (profile.sampling.temperature, profile.sampling.top_p) == (0.7, 0.8)
        assert (profile.tool_surface, profile.descriptions, profile.tool_choice) == (
            "full",
            "full",
            "auto",
        )

    @pytest.mark.parametrize(
        ("line", "field"),
        [
            ("profile: tiny\n", "profile"),
            ("sampling: {topP: 0}\n", "sampling.topP"),
            ("sampling: {temperature: 3}\n", "sampling.temperature"),
            ("toolChoice: always\n", "toolChoice"),
            ("budgets: {readWindow: 1.5}\n", "budgets.readWindow"),
            # A share the profile does not know (the deleted history share) is refused, not ignored.
            ("budgets: {history: 0.5}\n", "budgets.history"),
        ],
    )
    def test_a_bad_value_names_its_field(self, tmp_path: Path, line: str, field: str) -> None:
        with pytest.raises(_provider.ProviderError) as excinfo:
            _load(tmp_path, _LOCAL + line)

        assert excinfo.value.field == field

    def test_the_shipped_documents_resolve_by_their_local_flag(self) -> None:
        catalog = _provider.load_catalog()

        assert _provider.profile_of(catalog.get("local")).name == "local"
        assert _provider.profile_of(catalog.get("anthropic")).name == "hosted"


class TestResolveProfile:
    def test_a_model_takes_the_profile_of_its_provider_row(self) -> None:
        assert endpoint.resolve_profile("local/qwen").name == "local"
        assert endpoint.resolve_profile("anthropic/claude-sonnet-4-6").name == "hosted"

    def test_a_provider_absent_from_the_catalog_is_hosted(self) -> None:
        assert endpoint.resolve_profile("nowhere/model").name == "hosted"
        assert endpoint.resolve_profile("bare-model-id").name == "hosted"


def _observe(provider: str, model_id: str, window: int | None, out: int | None) -> None:
    spec = _provider.load_catalog().get(provider)
    assert spec is not None
    _lifecycle.record_observed_models(
        spec,
        ProbeResult(status=200, model_ids=[model_id], limits={model_id: ModelLimits(window, out)}),
    )


class TestHandoffWindow:
    def test_a_hosted_model_gives_its_window_and_output_cap(self) -> None:
        _observe("anthropic", "claude-haiku-4-5-20251001", 200_000, 64_000)

        assert endpoint.handoff_window("anthropic/claude-haiku-4-5-20251001") == (200_000, 64_000)

    def test_a_local_model_claims_no_window(self) -> None:
        _observe("local", "qwen", 32_768, 4_096)

        assert endpoint.handoff_window("local/qwen") == (None, None)

    def test_a_model_with_no_known_window_gives_none(self) -> None:
        assert endpoint.handoff_window("anthropic/never-seen") == (None, None)
        assert endpoint.handoff_window("nowhere/model") == (None, None)
        assert endpoint.handoff_window("") == (None, None)


class TestBudgets:
    def test_local_budgets_are_shares_of_the_window_in_characters(self, tmp_path: Path) -> None:
        spec = _load(tmp_path, _LOCAL + "models: [{id: m, contextWindow: 32768}]\n")
        per_token = current_home().context_bytes_per_token

        budgets = _provider.profile_of(spec, "m").budgets

        assert budgets.read_window_chars == int(32768 * 0.05 * per_token)
        assert budgets.tool_output_chars == int(32768 * 0.02 * per_token)

    def test_a_row_declares_its_own_shares(self, tmp_path: Path) -> None:
        text = _HOSTED + "models: [{id: m, contextWindow: 1000}]\nbudgets: {readWindow: 0.5}\n"

        budgets = _provider.profile_of(_load(tmp_path, text), "m").budgets

        assert budgets.read_window_chars == 500 * current_home().context_bytes_per_token
        assert budgets.tool_output_chars is None

    def test_a_hosted_row_budgets_nothing(self, tmp_path: Path) -> None:
        """No share sizes the history: a session is compacted only when a request does not fit."""
        spec = _load(tmp_path, _HOSTED + "models: [{id: m, contextWindow: 32768}]\n")

        assert _provider.profile_of(spec, "m").budgets == _provider.ProfileBudgets()

    def test_an_unknown_window_gives_no_budget_rather_than_a_guess(self, tmp_path: Path) -> None:
        spec = _load(tmp_path, _LOCAL + "models: [{id: m}]\n")

        assert _provider.profile_of(spec, "m").budgets == _provider.ProfileBudgets()
        assert _provider.profile_of(spec).budgets == _provider.ProfileBudgets()
