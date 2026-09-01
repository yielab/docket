"""Quick truth & dead-file sweep.

Guards:
  - the 3 dead template files are gone and never referenced under src/ again
    (install/pod provisioning write SOUL/AGENTS/workflow templates inline)
  - README's test-count claims aren't left stale
  - scripts/render-doc-assets.py doesn't point at a file that doesn't exist
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
README = _REPO / "README.md"
TEMPLATES_DIR = _REPO / "src" / "docket" / "templates"
RENDER_DOC_ASSETS = _REPO / "scripts" / "render-doc-assets.py"

_DEAD_TEMPLATES = [
    "SOUL-error-handling.md",
    "status-awareness.md",
    "bug-fix-pipeline.lobster.yml",
]


class TestDeadTemplatesStayDeleted:
    """The 3 zero-reference shipped templates from the audit must not come back."""

    def test_dead_template_files_do_not_exist(self) -> None:
        for name in _DEAD_TEMPLATES:
            assert not (TEMPLATES_DIR / name).exists(), (
                f"{name} was deleted as a dead file — it should not be re-added "
                "under src/docket/templates/"
            )

    def test_dead_templates_not_referenced_under_src(self) -> None:
        offenders: list[str] = []
        for path in (_REPO / "src").rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name in _DEAD_TEMPLATES:
                if name in text:
                    offenders.append(f"{path.relative_to(_REPO)}: {name}")
        assert not offenders, (
            "dead template file(s) referenced again under src/ (re-orphaning guard): "
            + ", ".join(offenders)
        )


class TestTestCountNotStale:
    """README's quoted pytest count must not regress to the old wrong numbers."""

    def test_readme_does_not_claim_stale_test_counts(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "694 tests" not in text
        assert "694-test Python suite" not in text


class TestRenderDocAssetsNoDanglingReference:
    """scripts/render-doc-assets.py must not cite a doc that doesn't exist."""

    def test_no_dangling_cost_feature_audit_reference(self) -> None:
        text = RENDER_DOC_ASSETS.read_text(encoding="utf-8")
        assert "COST-FEATURE-AUDIT" not in text
