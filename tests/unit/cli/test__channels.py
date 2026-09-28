"""`docket channels` -- the pure argument-parsing and override-shaping helpers.

`_parse_sets` is the repeated `--set key=value` shape (distinct from `cli/_exporters.py`'s
fixed-flag `_parse_opts`, since the same option repeats with a different key each time);
`_apply_sets` is the one place a raw `--set` pair turns into a model-shaped overrides dict.
Covered here because the CLI integration path (`enable_channel`/`set_content`) is already
exercised at the core layer in `tests/unit/core/test_channel.py`.
"""

from __future__ import annotations

from docket.cli import _channels
from docket.core import channel as _chan

SUBJECT = "docket.cli._channels"


class TestParseSets:
    def test_splits_positionals_from_repeated_set_flags(self) -> None:
        pos, sets = _channels._parse_sets(
            ["ntfy", "--set", "topic=myapp", "--set", "server=https://ntfy.example.com"]
        )
        assert pos == ["ntfy"]
        assert sets == {"topic": "myapp", "server": "https://ntfy.example.com"}

    def test_supports_set_equals_form(self) -> None:
        pos, sets = _channels._parse_sets(["telegram", "--set=actors=123,456"])
        assert pos == ["telegram"]
        assert sets == {"actors": "123,456"}

    def test_a_set_value_with_no_equals_is_dropped(self) -> None:
        pos, sets = _channels._parse_sets(["ntfy", "--set", "topic"])
        assert pos == ["ntfy"]
        assert sets == {}

    def test_no_sets_yields_only_positionals(self) -> None:
        pos, sets = _channels._parse_sets(["console"])
        assert pos == ["console"]
        assert sets == {}


class TestApplySets:
    def _spec(self, dialect: str = "webhook") -> _chan.ChannelSpec:
        return _chan.ChannelSpec(kind="channel", name="x", dialect=dialect, capabilities=["notify"])

    def test_actors_key_becomes_a_comma_split_list(self) -> None:
        overrides = _channels._apply_sets(self._spec(), {"actors": "a, b ,c"})
        assert overrides == {"actors": ["a", "b", "c"]}

    def test_secret_key_stays_a_top_level_string(self) -> None:
        overrides = _channels._apply_sets(self._spec(), {"secret": "WEBHOOK_SECRET"})
        assert overrides == {"secret": "WEBHOOK_SECRET"}

    def test_any_other_key_lands_in_config(self) -> None:
        overrides = _channels._apply_sets(self._spec(), {"topic": "myapp"})
        assert overrides == {"config": {"topic": "myapp"}}

    def test_config_override_merges_over_the_spec_existing_config(self) -> None:
        spec = _chan.ChannelSpec(
            kind="channel",
            name="x",
            dialect="ntfy",
            capabilities=["notify"],
            config={"server": "https://ntfy.sh", "topic": ""},
        )
        overrides = _channels._apply_sets(spec, {"topic": "myapp"})
        assert overrides == {"config": {"server": "https://ntfy.sh", "topic": "myapp"}}

    def test_no_sets_yields_no_overrides(self) -> None:
        assert _channels._apply_sets(self._spec(), {}) == {}
