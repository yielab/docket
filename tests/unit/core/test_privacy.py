"""Privacy classes and levels: the pure resolve/describe lookups (core/privacy.py)."""

from __future__ import annotations

import pytest

from docket.core import privacy

SUBJECT = "docket.core.privacy"


class TestLevels:
    def test_minimal_grants_nothing(self) -> None:
        assert privacy.LEVELS["minimal"] == frozenset()

    def test_levels_are_monotonic(self) -> None:
        assert privacy.LEVELS["minimal"] < privacy.LEVELS["actions"]
        assert privacy.LEVELS["actions"] < privacy.LEVELS["conversation"]
        assert privacy.LEVELS["conversation"] < privacy.LEVELS["full"]
        assert privacy.LEVELS["full"] == frozenset(privacy.CONTENT_CLASSES)


class TestResolve:
    def test_resolve_a_known_level(self) -> None:
        label, classes = privacy.resolve("actions", None)
        assert label == "actions"
        assert classes == privacy.LEVELS["actions"]

    def test_resolve_neither_argument_is_minimal(self) -> None:
        assert privacy.resolve(None, None) == ("minimal", frozenset())

    def test_resolve_an_explicit_share_matching_no_level_is_custom(self) -> None:
        label, classes = privacy.resolve(None, ["toolArguments", "prompts"])
        assert label == "custom"
        assert classes == frozenset({"toolArguments", "prompts"})

    def test_resolve_a_share_matching_a_level_returns_that_labels_name(self) -> None:
        label, classes = privacy.resolve(None, list(privacy.LEVELS["actions"]))
        assert label == "actions"
        assert classes == privacy.LEVELS["actions"]

    def test_resolve_rejects_an_unknown_level(self) -> None:
        with pytest.raises(ValueError, match="not a known privacy level"):
            privacy.resolve("bogus", None)

    def test_resolve_rejects_an_unknown_class(self) -> None:
        with pytest.raises(ValueError, match="not a known privacy class"):
            privacy.resolve(None, ["bogus"])

    def test_resolve_rejects_both_arguments_given(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            privacy.resolve("actions", ["prompts"])


class TestDescribe:
    def test_describe_covers_every_content_class_in_order(self) -> None:
        rows = privacy.describe(frozenset())
        assert [cls for cls, _granted, _attrs in rows] == list(privacy.CONTENT_CLASSES)
        assert all(granted is False for _cls, granted, _attrs in rows)

    def test_describe_marks_granted_classes(self) -> None:
        rows = privacy.describe(privacy.LEVELS["actions"])
        granted = {cls for cls, is_granted, _attrs in rows if is_granted}
        assert granted == privacy.LEVELS["actions"]

    def test_describe_names_at_least_one_attribute_per_class(self) -> None:
        rows = privacy.describe(frozenset(privacy.CONTENT_CLASSES))
        assert all(attrs for _cls, _granted, attrs in rows)
