"""Architecture: the jailed PDF extractor imports the standard library and pypdf, nothing else.

``sandbox/pdf_extract.py`` runs as a copy beside the document, in a jail that reads the interpreter
and its site-packages but not docket's source tree, so an import of ``docket`` (or of any other
third-party package) would fail there. The import contracts (``test_import_contracts.py``) do not
look at external packages; this is the one place the allowed set is stated.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SUBJECT = "docket.sandbox.pdf_extract"

REPO = Path(__file__).resolve().parents[2]
EXTRACTOR = REPO / "src" / "docket" / "sandbox" / "pdf_extract.py"
ALLOWED_THIRD_PARTY = frozenset({"pypdf"})


def disallowed_imports(source: str) -> list[str]:
    """Top-level names *source* imports that are neither standard library nor allowed."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." if node.level else (node.module or "").split(".")[0])
    return sorted(n for n in names if n not in sys.stdlib_module_names | ALLOWED_THIRD_PARTY)


def test_the_extractor_imports_only_the_standard_library_and_pypdf() -> None:
    assert disallowed_imports(EXTRACTOR.read_text(encoding="utf-8")) == []


def test_the_rule_refuses_any_other_third_party_or_docket_import() -> None:
    # Without this a rule that allowed everything would hold the extractor.
    assert disallowed_imports("import os\nimport pypdf\nfrom pypdf import PdfReader\n") == []
    assert disallowed_imports("import yaml\n") == ["yaml"]
    assert disallowed_imports("from docket.kernel import errors\n") == ["docket"]
    assert disallowed_imports("def f():\n    import pydantic\n") == ["pydantic"]
    assert disallowed_imports("from . import x\n") == ["."]
