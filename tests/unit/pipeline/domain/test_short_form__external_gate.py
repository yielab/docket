"""The ``external`` gate kind -- parse, short form, ``on:`` key validation, reachability and the
plan label. See specs/functional/pipeline-format.spec.md ("Gates" item 5, "Outcome routing")."""

from __future__ import annotations

import pytest
import yaml
from tests.support.roles import ROLE_NAMES

from docket.pipeline.domain.short_form import normalize_pipeline

SUBJECT = "docket.pipeline.domain.short_form"


_SHORT = """\
name: gated
steps:
  - plan: lead
  - build: implementer
    gate: {external: "verify.sh --strict"}
    on:
      pass: stop
      fail: {goto: build, max: 2}
      needs_human: ask
  - ask:
      input: {from: build}
      on:
        answered: {goto: build, max: 1}
        declined: fail
"""


def test_the_external_gate_expands_and_the_expansion_is_not_a_second_authored_form() -> None:
    doc = yaml.safe_load(_SHORT)
    once = normalize_pipeline(doc, ROLE_NAMES)
    assert once["steps"][1]["gate"] == {"type": "external", "command": "verify.sh --strict"}
    with pytest.raises(ValueError, match="canonical form"):
        normalize_pipeline(once, ROLE_NAMES)
