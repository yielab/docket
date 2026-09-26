"""The wheel actually ships the shipped recipe bundles it claims to."""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

LANE = "release"
REASON = "Prevents a recipe bundle from validating in the source tree while silently failing to reach the published artifact a user actually installs."
RETIRE_WHEN = "packaging moves off hatchling's default git-tracked-file inclusion for src/docket, or recipes gain their own dedicated packaging test."

ROOT = Path(__file__).resolve().parents[3]
RECIPES_DIR = ROOT / "src" / "docket" / "templates" / "recipes"


def test_wheel_contains_every_shipped_recipe_file(tmp_path: Path) -> None:
    """Build a real wheel and unzip it -- no reliance on hatchling's default behaviour."""
    dist = tmp_path / "dist"
    env = {**os.environ, "PYTHONPATH": ""}
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    wheel = next(dist.glob("docket-*.whl"))

    expected = {
        f"docket/templates/recipes/{p.relative_to(RECIPES_DIR)}"
        for p in RECIPES_DIR.rglob("*")
        if p.is_file()
    }
    assert expected, "no recipe files found in the source tree to check against"

    with zipfile.ZipFile(wheel) as z:
        packaged = set(z.namelist())

    missing = expected - packaged
    assert not missing, f"recipe files missing from the built wheel: {sorted(missing)}"
