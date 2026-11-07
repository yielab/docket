"""The label of a reviewer case: `label.yaml` says whether the diff in `repo/change.diff` is `good`
or `bad`, why, and who decided. `check-solutions` is the label's proof (specs/test-framework.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, ValidationError

LABEL_FILE = "label.yaml"
DIFF_FILE = "change.diff"

NonEmpty = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


class LabelError(ValueError):
    """A label that cannot be read; the message names the key at fault."""


class Label(BaseModel):
    """`good`: the reference solution, which passes the hidden test. `bad`: a mutant that passes
    the visible tests and fails the hidden one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Literal["good", "bad"]
    why: NonEmpty
    labelled_by: NonEmpty


def read_label(case: Path) -> Label:
    """The label of the case directory *case*; `LabelError` names the file and the key at fault."""
    file = case / LABEL_FILE
    if not file.is_file():
        raise LabelError(f"{LABEL_FILE}: file missing")
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise LabelError(f"{LABEL_FILE}: not valid YAML ({error})") from error
    if not isinstance(raw, dict):
        raise LabelError(f"{LABEL_FILE}: must be a mapping of keys")
    try:
        return Label.model_validate(raw)
    except ValidationError as error:
        parts = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
        raise LabelError(f"{LABEL_FILE}: " + "; ".join(parts)) from error
