"""Every `docket ...` invocation in the docs, specs, templates and help examples is live.

The removed-name guard proves old names are gone; this one runs
scripts/maint/lint_cli_invocations.py in process against the live Click tree.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "maint" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rcn = _load("rewrite_cli_names")
lint = _load("lint_cli_invocations")

ROOTS: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "docs",
    "specs",
    "src/docket/templates",
)
# The spec index keeps the retirement notes of removed commands, as a record.
RECORD_FILES: tuple[str, ...] = ("specs/README.md",)


def findings(roots: tuple[str, ...] = ROOTS) -> list[str]:
    hits: list[str] = []
    for path in rcn.iter_files(roots, RECORD_FILES):
        text = rcn.read_text(path)
        if text is None:
            continue
        editable, _record = rcn.split_record(path, text)
        hits += lint.lint_text(rcn._rel(path), editable)
    return hits


class TestRoots:
    def test_every_documented_invocation_is_live(self) -> None:
        start = time.monotonic()
        hits = findings() + lint.lint_examples()
        assert hits == [], "invocations the live tree does not have:\n" + "\n".join(hits)
        assert time.monotonic() - start < 2.0

    def test_the_linter_catches_its_planted_lines(self) -> None:
        assert lint.self_check() == []

    def test_every_leaf_has_an_example_line(self) -> None:
        assert len(list(lint.leaf_examples())) > 40


class TestPlanted:
    def test_an_option_the_leaf_lacks_is_found(self, tmp_path: Path) -> None:
        doc = tmp_path / "x.md"
        doc.write_text("Run `docket task list --retry` to see.\n", encoding="utf-8")
        assert len(lint.lint([doc])) == 1

    def test_a_spec_body_is_checked_and_its_changelog_is_not(self, tmp_path: Path) -> None:
        spec = tmp_path / "specs" / "functional" / "x.spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(
            "# X\n\nUse `docket status <agent>`.\n\n## Changelog\n\n- `docket status <agent>`\n",
            encoding="utf-8",
        )
        assert len(lint.lint([spec])) == 1

    def test_a_false_example_line_is_found(self, monkeypatch) -> None:
        monkeypatch.setattr(
            lint, "leaf_examples", lambda: iter([("docket x", "docket status <a>")])
        )
        assert len(lint.lint_examples()) == 1
