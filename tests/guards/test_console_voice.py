"""Ratchet: Rich markup literals outside ui.py only fall.

Every colour, weight and symbol belongs to ``ui.py``. ``console_voice_baseline.txt`` records
how many markup literals (``[green]``, ``[bold]``, ...) each other module still carries; a
module's count may not rise and an unlisted module may not gain one. A card that rewrites a
module through ``ui`` lowers its entry in the same commit, via ``--write``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import docket

SRC = Path(docket.__file__).resolve().parent
BASELINE = Path(__file__).with_name("console_voice_baseline.txt")
_MARKUP = re.compile(r"\[(?:bold|dim|green|red|yellow|cyan|magenta|blue|white)[^\]]*\]")


def count_literals() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "ui.py":
            continue
        n = len(_MARKUP.findall(path.read_text(encoding="utf-8")))
        if n:
            counts[rel] = n
    return counts


def read_baseline() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, _, n = line.rpartition(" ")
            out[name] = int(n)
    return out


def test_no_module_gains_a_markup_literal() -> None:
    base = read_baseline()
    bad = [
        f"{mod}: {n} > {base.get(mod, 0)}"
        for mod, n in count_literals().items()
        if n > base.get(mod, 0)
    ]
    assert not bad, "console voice ratchet regressed (use ui.* instead):\n" + "\n".join(bad)


if __name__ == "__main__" and "--write" in sys.argv:
    lines = ["# Rich markup literals outside ui.py; shrink-only, regenerate with --write"]
    lines += [f"{m} {n}" for m, n in count_literals().items()]
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
