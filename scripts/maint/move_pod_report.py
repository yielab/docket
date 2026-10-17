"""Move the pure readers of ``cli/_pod_show.py`` into ``core/pod_report.py``.

Every top-level symbol that is not a renderer (``_kv``, ``render_*``, ``_render_*``)
moves with its text unchanged; ``_network_text`` becomes ``network_text`` because the
renderers now import it. Run once from the repository root.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path("src/docket/cli/_pod_show.py")
DST = Path("src/docket/core/pod_report.py")
RENDER = re.compile(r"^(_kv|render_\w+|_render_\w+)$")

CORE_DOC = '''"""The pod and member reports behind ``docket pod show`` and ``GET /pods/<p>``.

Read-only readers that compose existing resolvers into one report. See
specs/data/cli-json-shapes.spec.md, "`docket pod show --json`".
"""
'''

CLI_DOC = '''"""``docket pod show`` -- Rich rendering of the reports built by ``core.pod_report``."""
'''


def main() -> None:
    text = SRC.read_text()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    body = tree.body
    first = next(
        i for i, n in enumerate(body) if not isinstance(n, ast.Expr | ast.ImportFrom | ast.Import)
    )
    start = body[first].lineno
    moved: list[str] = []
    kept: list[str] = []
    for idx in range(first, len(body)):
        node = body[idx]
        lo = node.lineno
        hi = body[idx + 1].lineno - 1 if idx + 1 < len(body) else len(lines)
        chunk = "".join(lines[lo - 1 : hi])
        name = getattr(node, "name", None)
        if name and RENDER.match(name):
            kept.append(chunk)
        else:
            moved.append(chunk)
    assert start > 0
    imports = "".join(lines[body[1].lineno - 1 : start - 1]).rstrip() + "\n"
    core_imports = "\n".join(ln for ln in imports.splitlines() if "import ui" not in ln)
    core_body = re.sub(r"\b_network_text\b", "network_text", "".join(moved).rstrip() + "\n")
    DST.write_text(CORE_DOC + "\n" + core_imports + "\n\n\n" + core_body)
    cli_imports = (
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "from docket import ui\n"
        "from docket.core.pod_report import network_text\n"
    )
    cli_body = re.sub(r"\b_network_text\b", "network_text", "".join(kept).rstrip() + "\n")
    SRC.write_text(CLI_DOC + "\n" + cli_imports + "\n\n" + cli_body)


if __name__ == "__main__":
    main()
