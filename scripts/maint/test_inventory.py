#!/usr/bin/env python3
"""Classify every pytest file into a target lane and propose the move map.

Lanes:
  unit         one src module under test, in-process
  integration  several modules or a real CLI process, still product behaviour
  guards       AST / layout invariants over the tree
  agent/truth  asserts on prose (README, GOVERNANCE, specs index, positioning)
  agent/release  builds or installs artifacts, adapter parity, journeys
  agent/harness  tests of the agent's own hook scripts under .agents/

Pure analysis. Writes nothing unless --out is given.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests" / "python"
SRC = ROOT / "src" / "docket"

PROSE_PATHS = re.compile(
    r'"(README|GOVERNANCE|SUPPORT|ROADMAP|TODO|CLAUDE|CHANGELOG)\.md"|"specs"|"docs"'
)
ARTIFACT_BUILD = re.compile(r"uv build|pip install|\"build\"|sdist|wheel|Formula|homebrew", re.I)
HARNESS = re.compile(r"\.agents/|\"\.agents\"|context_snapshot|card_packet")
REMOVED = re.compile(r"_removed|tier_shims")
ARCHAEOLOGY = re.compile(
    r"\b[WP]\d{2}-\d+\b|\bD-\d+\b|\bPhase \d+\b|\b20\d{2}-\d{2}-\d{2}\b|\bCL-[A-Z]\b"
)


SUPPORT_MODULES = {
    "docket.config",
    "docket.core.models",
    "docket.core.utils",
    "docket.edges.store",
    "docket.ui",
}


def docket_imports(tree: ast.AST) -> Counter[str]:
    """Subject modules weighted by imported names; fixture-only modules are excluded."""
    mods: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("docket"):
            parts = node.module.split(".")
            if len(parts) >= 3:
                mods[".".join(parts[:3])] += len(node.names)
            elif len(parts) == 2:
                for alias in node.names:
                    mods[f"docket.{parts[1]}.{alias.name}"] += 1
            else:
                for alias in node.names:
                    mods[f"docket.{alias.name}"] += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("docket"):
                    mods[".".join(alias.name.split(".")[:3])] += 1
    for m in SUPPORT_MODULES:
        mods.pop(m, None)
    return mods


def uses_ast_on_src(text: str) -> bool:
    return "ast.parse" in text and ("src" in text or "SRC" in text or "inspect.getsource" in text)


def classify(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    name = path.stem
    tests = sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    )
    subprocess_calls = len(re.findall(r"subprocess\.(run|Popen|check_output|call)", text))
    imports = docket_imports(tree)
    primary = imports.most_common(1)[0][0] if imports else None
    archaeology = len(ARCHAEOLOGY.findall(text))

    if HARNESS.search(text):
        lane = "agent/harness"
    elif "adoption" in name or (
        ARTIFACT_BUILD.search(text)
        and (
            "adoption" in name
            or "release" in name
            or "journey" in name
            or "adapter" in name
            or "package" in name
            or "distribution" in name
            or "smoke" in name
        )
    ):
        lane = "agent/release"
    elif PROSE_PATHS.search(text) and (
        "truth" in name
        or "docs" in name
        or "positioning" in name
        or "metrics_script" in name
        or "dead_file" in name
    ):
        lane = "agent/truth"
    elif (
        (uses_ast_on_src(text) and tests <= 8)
        or name.startswith("test_no_")
        or REMOVED.search(name)
        or name
        in (
            "test_config_single_owner",
            "test_docket_home_isolation",
            "test_completions_drift",
            "test_workspace_root_agreement",
            "test_runtime_package_boundary",
        )
    ):
        lane = "guards"
    elif (
        subprocess_calls
        or "CliRunner" in text
        or (primary or "").startswith("docket.cli")
        or len(imports) >= 5
    ):
        lane = "integration"
    else:
        lane = "unit"

    target = None
    if lane == "unit" and primary:
        parts = primary.split(".")
        target = (
            f"tests/unit/{'/'.join(parts[1:-1])}/test_{parts[-1]}.py"
            if len(parts) > 2
            else f"tests/unit/test_{parts[-1]}.py"
        )
    elif lane == "integration":
        target = f"tests/integration/{path.name}"
    elif lane == "guards":
        target = f"tests/guards/{path.name}"
    else:
        target = f"tests/{lane}/{path.name}"

    return {
        "file": path.name,
        "lane": lane,
        "primary_module": primary,
        "modules": dict(imports.most_common(5)),
        "lines": text.count("\n"),
        "tests": tests,
        "subprocess_calls": subprocess_calls,
        "archaeology_refs": archaeology,
        "target": target,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out", type=Path, help="write inventory JSON and moves.tsv into this directory"
    )
    ap.add_argument("--lane", help="only print files in this lane")
    args = ap.parse_args()

    rows = [classify(p) for p in sorted(TESTS.glob("test_*.py"))]
    if args.lane:
        rows = [r for r in rows if r["lane"] == args.lane]

    by_lane: Counter[str] = Counter()
    lines_by_lane: Counter[str] = Counter()
    for r in rows:
        by_lane[str(r["lane"])] += 1
        lines_by_lane[str(r["lane"])] += int(r["lines"])  # type: ignore[call-overload]
    print(f"{'lane':16} {'files':>5} {'lines':>7}")
    for lane, n in sorted(by_lane.items()):
        print(f"{lane:16} {n:5} {lines_by_lane[lane]:7}")

    merges: dict[str, list[str]] = {}
    for r in rows:
        if r["lane"] == "unit":
            merges.setdefault(str(r["target"]), []).append(str(r["file"]))
    multi = {k: v for k, v in merges.items() if len(v) > 1}
    print(f"\nunit targets fed by more than one file: {len(multi)}")
    for k, v in sorted(multi.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k}  <-  {len(v)} files: {', '.join(v)}")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "inventory.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        with (args.out / "moves.tsv").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(f"tests/python/{r['file']}\t{r['target']}\t{r['lane']}\n")
        print(f"\nwrote {args.out / 'inventory.json'} and moves.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
