"""`docket exporters` -- the pure argument-parsing and auth-header helpers.

`_parse_opts` is the same hand-parsed `--key value` shape `cli/_provider.py` uses;
`_auth_header_for` is the one place that turns a resolved credential list into the header a
wire adapter's `probe`/`emit` takes -- covered here because the CLI integration test
(`tests/integration/test_exporters_cli.py`) only exercises it through a real local server.
"""

from __future__ import annotations

from docket.cli import _exporters
from docket.core import exporter as _exp

SUBJECT = "docket.cli._exporters"


class TestParseOpts:
    def test_splits_positionals_from_key_value_and_key_equals_value(self) -> None:
        pos, opts = _exporters._parse_opts(
            ["langfuse", "--endpoint", "https://x/v1/traces", "--payload=full"]
        )
        assert pos == ["langfuse"]
        assert opts == {"endpoint": "https://x/v1/traces", "payload": "full"}


class TestAuthHeaderFor:
    def _spec(self, auth_type: str, header: str = "") -> _exp.ExporterSpec:
        credentials = {"none": [], "bearer": ["TOK"], "header": ["TOK"], "basic": ["U", "P"]}
        return _exp.ExporterSpec(
            kind="exporter",
            name="x",
            endpoint="https://x/v1/traces",
            auth=_exp.ExporterAuth(
                type=auth_type,  # type: ignore[arg-type]
                header=header,
                credentials=credentials[auth_type],
            ),
        )

    def test_none_auth_never_carries_a_header(self) -> None:
        assert _exporters._auth_header_for(self._spec("none"), []) is None

    def test_bearer_carries_the_resolved_value_on_authorization(self) -> None:
        header = _exporters._auth_header_for(self._spec("bearer"), ["secret-value"])
        assert header == ("Authorization", "Bearer secret-value")

    def test_header_type_uses_the_declared_header_name(self) -> None:
        header = _exporters._auth_header_for(self._spec("header", "X-Api-Key"), ["secret-value"])
        assert header == ("X-Api-Key", "secret-value")

    def test_basic_base64_encodes_user_and_password_in_order(self) -> None:
        header = _exporters._auth_header_for(self._spec("basic"), ["pub", "sec"])
        assert header == ("Authorization", "Basic cHViOnNlYw==")

    def test_missing_values_carry_no_header(self) -> None:
        assert _exporters._auth_header_for(self._spec("bearer"), [""]) is None
