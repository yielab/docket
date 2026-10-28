#!/usr/bin/env python3
"""One-shot pure move: the free helper functions of hops/application/driver.py go to
hops/application/driver_support.py. Unused imports are then removed by ruff."""

from __future__ import annotations

import subprocess
from pathlib import Path

APP = Path("src/docket/hops/application")
lines = (APP / "driver.py").read_text().splitlines(keepends=True)
imports_start = next(i for i, ln in enumerate(lines) if ln.startswith("import atexit"))
all_line = next(i for i, ln in enumerate(lines) if ln.startswith("__all__"))
helpers_start = next(i for i, ln in enumerate(lines) if ln.startswith("# Reads and validates"))
class_line = next(i for i, ln in enumerate(lines) if ln.startswith("@dataclass"))

imports = "".join(lines[imports_start:all_line])
head = "".join(lines[:helpers_start])
helpers = "".join(lines[helpers_start:class_line])
tail = "".join(lines[class_line:])

support_doc = (
    '"""The free helpers ``DocketDriver`` composes a turn from: pod settings, roots, budgets,\n'
    'policy scope, loop config and the trace callback. Moved out of ``driver.py`` unchanged."""\n\n'
    "from __future__ import annotations\n\n"
)
(APP / "driver_support.py").write_text(support_doc + imports + "\n\n" + helpers.rstrip() + "\n")
names = [ln.split("(")[0].split()[1] for ln in helpers.splitlines() if ln.startswith("def _")]
new_import = (
    "from docket.hops.application.driver_support import (\n"
    + "".join(f"    {n},\n" for n in sorted(names))
    + ")\n"
)
driver = head.rstrip() + "\n\n\n" + tail
driver = driver.replace(
    "from docket.hops.application.verdict_tool",
    new_import + "from docket.hops.application.verdict_tool",
    1,
)
(APP / "driver.py").write_text(driver)
for f in ("driver.py", "driver_support.py"):
    subprocess.run(
        ["uv", "run", "ruff", "check", "--select", "F401,I", "--fix", str(APP / f)], check=False
    )
    subprocess.run(["uv", "run", "ruff", "format", str(APP / f)], check=False)
