"""Acceptance guard: no live `openclaw` coupling left under `src/`.

docket has no ACL (`edges/adapters/openclaw.py`), no `openclaw` shell-out, no
`openclaw.json`/`CONFIG_FILE`, and no auth-profiles any more -- a clean break
with no compatibility layer. This guard's criterion: `command grep -ril
openclaw src/` should turn up nothing but deliberate historical comments.

It walks every `.py` file under `src/docket` token by token (stronger than a
plain grep for one shell-out pattern or one file format) and forbids the word
"openclaw" (case-insensitive) from appearing anywhere EXCEPT:

  * a `#` comment, or
  * a real docstring (the first statement of a module/class/function) --

i.e. prose explaining what used to be there is fine and expected (this
codebase's convention, see CLAUDE.md, is to narrate *why* code changed); a
live import, identifier, or non-docstring string literal is not -- that
would mean actual code still depends on the deleted daemon/ACL/file format.

Proven RED before being trusted: a reference to a fake `docket.edges.adapters
.openclaw` import (`import docket.edges.adapters.openclaw as _oc`) was
planted in a scratch copy of a real module and this guard failed with that
file listed as an offender; the plant was then reverted and the guard passed
again.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"


def _docstring_line_ranges(tree: ast.Module) -> set[int]:
    """Line numbers spanned by a real docstring: the first statement of the
    module, a class, or a function/async function -- the only string
    literals ast treats as documentation rather than data."""
    lines: set[int] = set()
    candidates: list[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.append(node)
    for node in candidates:
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            doc_expr = body[0]
            end = doc_expr.end_lineno or doc_expr.lineno
            lines.update(range(doc_expr.lineno, end + 1))
    return lines


def _offenders_in_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - would fail collection anyway
        return [f"{path}: SyntaxError parsing for the guard: {exc}"]
    doc_lines = _docstring_line_ranges(tree)

    offenders: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    for tok in tokens:
        lowered = tok.string.lower()
        if "openclaw" not in lowered:
            continue
        if tok.type == tokenize.COMMENT:
            continue  # allowed: a `#` comment narrating history
        if tok.type == tokenize.STRING and tok.start[0] in doc_lines:
            continue  # allowed: inside a real module/class/function docstring
        offenders.append(
            f"{path.relative_to(SRC)}:{tok.start[0]}: "
            f"{tokenize.tok_name[tok.type]} {tok.string.strip()[:80]!r}"
        )
    return offenders


def test_no_live_openclaw_reference_outside_comments_and_docstrings() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        offenders.extend(_offenders_in_file(path))
    assert not offenders, (
        "Live `openclaw` reference(s) found outside comments/docstrings -- the "
        "clean break means no code may import, name, or otherwise depend on the "
        "deleted ACL/daemon/file-format any more (a historical comment or docstring "
        "explaining what used to be there is fine; real code is not):\n" + "\n".join(offenders)
    )
