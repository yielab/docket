"""The ``external`` gate kind -- parse, short form, ``on:`` key validation, reachability and the
plan label. See specs/functional/pipeline-format.spec.md ("Gates" item 5, "Outcome routing")."""

from __future__ import annotations

import yaml

from docket.pipeline.domain.short_form import normalize_pipeline

SUBJECT = "docket.pipeline.domain.short_form"


_SHORT = """\
name: gated
steps:
  - id: plan
    role: lead
  - build: implementer
    gate: {external: "verify.sh --strict"}
    on:
      pass: stop
      fail: {goto: build, max: 2}
      needs_human: ask
  - id: ask
    input: {from: build}
    on:
      answered: {goto: build, max: 1}
      declined: fail
"""


def test_normalization_is_idempotent() -> None:
    doc = yaml.safe_load(_SHORT)
    once = normalize_pipeline(doc)
    assert normalize_pipeline(once) == once
    assert once["steps"][1]["gate"] == {"type": "external", "command": "verify.sh --strict"}
