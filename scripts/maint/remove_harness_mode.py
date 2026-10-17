#!/usr/bin/env python3
"""Delete harness mode: the `exec` command, its contract, fixtures, tests and docs.

``--check`` prints what would be removed and exits 1 while anything is left; the bare run does
``git rm -r -q`` on every path that still exists.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PATHS = (
    "src/docket/cli/_exec.py",
    "src/docket/cli/_harness_answers.py",
    "src/docket/cli/_harness_recipe.py",
    "src/docket/cli/_setup_harness.py",
    "src/docket/core/harness.py",
    "src/docket/core/setup_home.py",
    "src/docket/core/harness_pipeline.py",
    "scripts/harness_schema.py",
    "scripts/maint/move_llm_stub.py",
    "docs/contracts/harness-v1",
    "docs/contracts/harness-v1.1",
    "docs/contracts/harness-v1.2",
    "tests/fixtures/harness-contract",
    "tests/unit/cli/test__exec.py",
    "tests/unit/cli/test__harness_answers.py",
    "tests/unit/cli/test__harness_recipe.py",
    "tests/unit/core/test_harness.py",
    "tests/unit/core/test_setup_home.py",
    "tests/integration/test_harness_cli.py",
    "tests/integration/test_harness_consult.py",
    "tests/integration/test_harness_contract.py",
    "tests/integration/test_harness_pipeline.py",
    "tests/integration/test_harness_v11_consumer.py",
    "tests/integration/test_harness_v12_setup.py",
    "tests/integration/test_consult_seam.py",
    "tests/integration/test_evidence_recipe_seam.py",
    "specs/api/harness-mode.spec.md",
    "docs/DEVELOPMENT-HARNESS.md",
)


def present() -> list[str]:
    return [p for p in PATHS if (REPO / p).exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="list what would be removed")
    args = ap.parse_args()
    todo = present()
    for p in todo:
        print(p)
    if args.check:
        return 1 if todo else 0
    if todo:
        subprocess.run(["git", "rm", "-r", "-q", "--", *todo], cwd=REPO, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
