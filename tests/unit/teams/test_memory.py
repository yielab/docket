"""`teams/memory.py`: parsing a reply's memory section."""

from __future__ import annotations

import dataclasses

from tests.support.pods import section as _section

from docket.kernel.home import current_home, use_home
from docket.teams import memory as pm

SUBJECT = "docket.teams.memory"


class TestParse:
    def test_the_four_kinds_parse_from_a_trailing_section(self) -> None:
        text = _section(
            "- generated: dist/bundle.js -- Built output, not source.",
            "- command: pytest -q -- Runs the unit tests.",
            "- pitfall: api/schema.proto -- Edits need a regenerated client.",
            "- convention: . -- Public functions carry type hints.",
        )

        parsed = pm.parse_memory_section(text)

        assert [(p.kind, p.subject) for p in parsed] == [
            ("generated", "dist/bundle.js"),
            ("command", "pytest -q"),
            ("pitfall", "api/schema.proto"),
            ("convention", "."),
        ]
        assert parsed[0].note == "Built output, not source."
        assert all(not p.refusal for p in parsed)

    def test_no_section_parses_to_nothing(self) -> None:
        assert pm.parse_memory_section("All done, nothing to add.") == []

    def test_the_last_memory_heading_wins_and_prose_is_ignored(self) -> None:
        text = (
            "## Memory\n- generated: a -- first.\n\nsome prose\n"
            "## Memory\nnot a bullet\n- generated: b -- second.\n"
        )

        assert [p.subject for p in pm.parse_memory_section(text)] == ["b"]

    def test_the_section_ends_at_the_next_heading(self) -> None:
        text = "## Memory\n- generated: a -- one.\n## Next steps\n- generated: b -- two.\n"

        assert [p.subject for p in pm.parse_memory_section(text)] == ["a"]

    def test_a_bullet_outside_the_grammar_or_the_kinds_is_a_refusal(self) -> None:
        parsed = pm.parse_memory_section(_section("- generated: no note here", "- secret: x -- y"))

        assert len(parsed) == 2
        assert all(p.refusal for p in parsed)
        assert "kind" in parsed[1].refusal

    def test_only_the_first_entries_of_a_reply_are_read(self) -> None:
        with use_home(dataclasses.replace(current_home(), pod_memory_max_per_task=2)):
            parsed = pm.parse_memory_section(
                _section(*[f"- generated: f{i} -- n." for i in range(5)])
            )

            assert [p.subject for p in parsed] == ["f0", "f1"]
