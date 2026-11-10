"""Guard: no module but the provider catalog holds a provider-name literal in a table.

A provider's identity is a document under ``templates/providers/`` plus the loader in
``models/catalog.py``, never a hand-kept table: every base URL, credential name, preset and
key prefix is a function over the loaded catalog elsewhere, so no other literal should name
one. The check is an AST scan rather than a fixed provider list, so it keeps holding as the
catalog grows (ADR 0011's "seven tables, seven populations" problem).
"""

from __future__ import annotations

import ast
from pathlib import Path

from docket.models import catalog as _provider

_LITERAL_PROVIDER_NAMES = ("anthropic", "openai")


class TestNoProviderNameLiteralOutsideTheCatalog:
    """A provider's identity is a document under ``templates/providers/`` plus this module's
    loader, never a hand-kept table: every base URL, credential name, preset and key prefix is
    a function over the loaded catalog elsewhere, so no other literal should name one."""

    def test_no_dict_or_tuple_literal_names_a_provider_outside_provider_py(self) -> None:
        offenders: list[str] = []
        src_root = Path(_provider.__file__).resolve().parent.parent
        for path in sorted(src_root.rglob("*.py")):
            if path == Path(_provider.__file__).resolve():
                continue
            if "templates" in path.parts:
                continue
            rel = str(path.relative_to(src_root))
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.Dict, ast.Tuple)):
                    continue
                elements = node.values if isinstance(node, ast.Dict) else node.elts
                keys = node.keys if isinstance(node, ast.Dict) else ()
                strings = [
                    n.value
                    for n in (*elements, *keys)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                ]
                if any(s in _LITERAL_PROVIDER_NAMES for s in strings):
                    offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], f"provider-name literal(s) outside models/catalog.py: {offenders}"
