"""The exporter catalog (`core/exporter.py`).

Covers ``load_exporter_document`` (the `kind: exporter` document loader,
specs/functional/observability-export.spec.md "Exporter documents"), the built-in + global
catalog merge with inheritance, and the pure ``activation_state`` classification. Mirrors
``tests/unit/core/test_provider.py``'s shape for the sibling catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import exporter as _exporter
from docket.core import secrets as _secrets
from docket.edges import store as _store

SUBJECT = "docket.core.exporter"

# EXPORTERS_FILE/EXPORTERS_HEALTH_FILE are isolated to a tmp DOCKET_HOME by the autouse
# _isolate_docket_home fixture in tests/conftest.py -- no real ~/.docket is ever touched here.


class TestBuiltinCatalog:
    def test_every_built_in_document_loads(self) -> None:
        directory = _cfg.EXPORTER_TEMPLATES_DIR
        files = sorted(directory.glob("*.yaml"))
        assert len(files) == 5, f"expected 5 built-in exporter documents, found {len(files)}"
        for path in files:
            spec = _exporter.load_exporter_document(path)
            assert spec.name

    def test_fresh_catalog_is_five_builtins_all_disabled(self) -> None:
        catalog = _exporter.load_catalog()
        assert set(catalog.entries) == {
            "otel-collector",
            "jaeger",
            "langfuse",
            "honeycomb",
            "phoenix",
        }
        for name, spec in catalog.entries.items():
            assert catalog.source_of(name) == "built-in"
            state, missing = _exporter.activation_state(spec, health=None)
            assert (state, missing) == ("disabled", [])

    def test_every_builtin_declares_minimal_privacy(self) -> None:
        catalog = _exporter.load_catalog()
        for name, spec in catalog.entries.items():
            assert spec.privacy_label == "minimal", name
            assert spec.privacy_classes == frozenset()

    def test_langfuse_reads_the_session_root_as_the_trace_input_and_output(self) -> None:
        aliases = _exporter.load_catalog().get("langfuse").aliases
        assert aliases["docket.session.input"] == "langfuse.observation.input"
        assert aliases["docket.session.output"] == "langfuse.observation.output"


class TestLoadExporterDocument:
    def test_loads_a_minimal_no_auth_document(self, tmp_path: Path) -> None:
        doc = tmp_path / "phoenix.yaml"
        doc.write_text("kind: exporter\nname: phoenix\nendpoint: http://127.0.0.1:6006/v1/traces\n")

        spec = _exporter.load_exporter_document(doc)

        assert spec.name == "phoenix"
        assert spec.dialect == "otlp-http"
        assert spec.auth.type == "none"
        assert spec.privacy_label == "minimal"
        assert spec.privacy_classes == frozenset()
        assert spec.content_max_chars == 4000
        assert spec.enabled is False
        assert spec.resource == {"service.name": "docket"}

    def test_wrong_kind_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text("kind: provider\nname: phoenix\n")

        with pytest.raises(_exporter.ExporterError, match="kind"):
            _exporter.load_exporter_document(doc)

    def test_missing_name_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text("kind: exporter\nendpoint: http://127.0.0.1:4318/v1/traces\n")

        with pytest.raises(_exporter.ExporterError, match="name"):
            _exporter.load_exporter_document(doc)


class TestNegativeRefusals:
    """The three fail-closed cases the card names explicitly."""

    def test_credential_shaped_value_in_credentials_is_refused_naming_the_field(
        self, tmp_path: Path
    ) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: langfuse\n"
            "endpoint: https://cloud.langfuse.com/api/public/otel/v1/traces\n"
            "auth:\n"
            "  type: basic\n"
            "  credentials: [pk-lf-1234567890123456789, sk-lf-1234567890123456789]\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert "auth.credentials" in str(excinfo.value)
        assert "credential VALUE" in str(excinfo.value)

    def test_unknown_dialect_is_refused_listing_otlp_http(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\nname: mystery\ndialect: otlp-grpc\nendpoint: http://127.0.0.1:4317\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert "otlp-http" in excinfo.value.valid

    def test_unknown_event_type_is_refused_naming_it(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: mystery\n"
            "endpoint: http://127.0.0.1:4318/v1/traces\n"
            "events: [nope]\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert "nope" in str(excinfo.value)


class TestPrivacyFields:
    """`ExporterSpec`'s own privacy/share fields: resolution, refusal, and legacy capture
    (observability-export.spec.md "Exporter privacy fields", requirements 80-84)."""

    def test_resolves_a_declared_level(self, tmp_path: Path) -> None:
        doc = tmp_path / "actions.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: mystery\n"
            "endpoint: http://127.0.0.1:4318/v1/traces\n"
            "privacy: actions\n"
        )

        spec = _exporter.load_exporter_document(doc)

        assert spec.privacy_label == "actions"
        assert spec.privacy_classes == {"toolArguments", "errors"}

    def test_unset_resolves_to_minimal(self, tmp_path: Path) -> None:
        doc = tmp_path / "bare.yaml"
        doc.write_text("kind: exporter\nname: mystery\nendpoint: http://127.0.0.1:4318/v1/traces\n")

        spec = _exporter.load_exporter_document(doc)

        assert spec.privacy_label == "minimal"
        assert spec.privacy_classes == frozenset()

    def test_privacy_and_share_together_is_refused_naming_both(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: mystery\n"
            "endpoint: http://127.0.0.1:4318/v1/traces\n"
            "privacy: actions\n"
            "share: [prompts]\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert "privacy" in str(excinfo.value)
        assert "share" in str(excinfo.value)

    def test_unknown_privacy_level_is_refused_naming_the_field(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: mystery\n"
            "endpoint: http://127.0.0.1:4318/v1/traces\n"
            "privacy: everything\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert excinfo.value.field == "privacy"
        assert "minimal" in excinfo.value.valid

    def test_unknown_share_class_is_refused_naming_it(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: exporter\n"
            "name: mystery\n"
            "endpoint: http://127.0.0.1:4318/v1/traces\n"
            "share: [secrets]\n"
        )

        with pytest.raises(_exporter.ExporterError) as excinfo:
            _exporter.load_exporter_document(doc)
        assert "secrets" in str(excinfo.value)


class TestAuthArity:
    def test_basic_requires_exactly_two_ordered_credentials(self) -> None:
        with pytest.raises(Exception, match="exactly 2"):
            _exporter.ExporterAuth(type="basic", credentials=["ONLY_ONE"])

    def test_bearer_requires_exactly_one(self) -> None:
        with pytest.raises(Exception, match="exactly 1"):
            _exporter.ExporterAuth(type="bearer", credentials=["A", "B"])

    def test_none_requires_zero(self) -> None:
        with pytest.raises(Exception, match="exactly 0"):
            _exporter.ExporterAuth(type="none", credentials=["A"])

    def test_header_requires_the_header_name(self) -> None:
        with pytest.raises(Exception, match=r"auth\.header"):
            _exporter.ExporterAuth(type="header", credentials=["A"])


class TestGlobalOverrideInheritance:
    """The global-document merge scenario the card names explicitly."""

    def test_partial_global_override_inherits_unset_fields(self) -> None:
        _store.write_json(
            _cfg.EXPORTERS_FILE,
            {
                "exporters": {
                    "langfuse": {
                        "kind": "exporter",
                        "name": "langfuse",
                        "enabled": True,
                        "endpoint": "https://lf.internal/api/public/otel/v1/traces",
                    }
                }
            },
        )

        catalog = _exporter.load_catalog()
        spec = catalog.get("langfuse")

        assert spec is not None
        assert catalog.source_of("langfuse") == "global"
        assert spec.endpoint == "https://lf.internal/api/public/otel/v1/traces"
        assert spec.auth.type == "basic"
        assert spec.auth.credentials == ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]
        builtin = _exporter.load_exporter_document(_cfg.EXPORTER_TEMPLATES_DIR / "03-langfuse.yaml")
        assert spec.aliases == builtin.aliases
        assert spec.resource == {"service.name": "docket"}

    def test_needs_credential_when_only_one_of_two_is_stored(self) -> None:
        _secrets.save_secrets({"LANGFUSE_PUBLIC_KEY": "pk-lf-abcdefghijklmnopqrstuvwx"})
        _store.write_json(
            _cfg.EXPORTERS_FILE,
            {"exporters": {"langfuse": {"kind": "exporter", "name": "langfuse", "enabled": True}}},
        )

        spec = _exporter.load_catalog().get("langfuse")
        assert spec is not None

        state, missing = _exporter.activation_state(spec, health=None)
        assert (state, missing) == ("needs credential", ["LANGFUSE_SECRET_KEY"])

    def test_enabled_when_both_credentials_are_stored(self) -> None:
        _secrets.save_secrets(
            {
                "LANGFUSE_PUBLIC_KEY": "pk-lf-abcdefghijklmnopqrstuvwx",
                "LANGFUSE_SECRET_KEY": "sk-lf-abcdefghijklmnopqrstuvwx",
            }
        )
        _store.write_json(
            _cfg.EXPORTERS_FILE,
            {"exporters": {"langfuse": {"kind": "exporter", "name": "langfuse", "enabled": True}}},
        )

        spec = _exporter.load_catalog().get("langfuse")
        assert spec is not None

        state, missing = _exporter.activation_state(spec, health=None)
        assert (state, missing) == ("enabled", [])


class TestActivationStateUnreachable:
    def test_unreachable_when_last_error_is_newer_than_last_ok(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter",
            name="otel-collector",
            endpoint="http://127.0.0.1:4318/v1/traces",
            enabled=True,
        )
        health = {
            "lastOk": "2026-09-27T10:00:00Z",
            "lastError": "connection refused",
            "lastErrorAt": "2026-09-27T11:00:00Z",
        }

        state, missing = _exporter.activation_state(spec, health=health)
        assert (state, missing) == ("unreachable", [])

    def test_enabled_when_last_ok_is_newer_than_last_error(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter",
            name="otel-collector",
            endpoint="http://127.0.0.1:4318/v1/traces",
            enabled=True,
        )
        health = {
            "lastOk": "2026-09-27T12:00:00Z",
            "lastError": "connection refused",
            "lastErrorAt": "2026-09-27T11:00:00Z",
        }

        state, missing = _exporter.activation_state(spec, health=health)
        assert (state, missing) == ("enabled", [])


class TestVerifyEndpoint:
    def test_transport_failure_is_unreachable(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter", name="phoenix", endpoint="http://127.0.0.1:6006/v1/traces"
        )
        verification = _exporter.verify_endpoint(
            spec, _exporter.ProbeResult(status=None, error="connection refused")
        )
        assert verification.reachable is False
        assert verification.warning == "connection refused"

    def test_2xx_has_no_warning(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter", name="phoenix", endpoint="http://127.0.0.1:6006/v1/traces"
        )
        verification = _exporter.verify_endpoint(spec, _exporter.ProbeResult(status=200))
        assert verification.reachable is True
        assert verification.warning == ""

    def test_401_names_the_credential(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter",
            name="honeycomb",
            endpoint="https://api.honeycomb.io/v1/traces",
            auth={
                "type": "header",
                "header": "x-honeycomb-team",
                "credentials": ["HONEYCOMB_API_KEY"],
            },
        )
        verification = _exporter.verify_endpoint(spec, _exporter.ProbeResult(status=401))
        assert verification.reachable is True
        assert "HONEYCOMB_API_KEY" in verification.warning


class TestDeleteExporter:
    def test_built_in_with_no_global_override_is_refused(self) -> None:
        with pytest.raises(_exporter.ExporterError, match="built-in"):
            _exporter.delete_exporter("phoenix")

    def test_unknown_name_is_refused(self) -> None:
        with pytest.raises(_exporter.ExporterError, match="not in the exporter catalog"):
            _exporter.delete_exporter("does-not-exist")

    def test_removes_a_global_entry(self) -> None:
        spec = _exporter.ExporterSpec(
            kind="exporter", name="my-otel", endpoint="http://127.0.0.1:4318/v1/traces"
        )
        _exporter.save_exporter(spec)
        assert _exporter.load_catalog().get("my-otel") is not None

        _exporter.delete_exporter("my-otel")
        assert _exporter.load_catalog().get("my-otel") is None


class TestExportExporter:
    def test_round_trips_a_built_in(self) -> None:
        rendered = _exporter.export_exporter("phoenix")
        assert "kind: exporter" in rendered
        assert "name: phoenix" in rendered
        # never a credential value -- only names ever live in the model.
        assert "HONEYCOMB_API_KEY" not in rendered

    def test_unknown_name_is_refused(self) -> None:
        with pytest.raises(_exporter.ExporterError):
            _exporter.export_exporter("does-not-exist")
