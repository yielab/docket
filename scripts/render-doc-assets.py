#!/usr/bin/env python3
"""Render the complete public terminal-visual set.

The isolation scene consumes a byte-verified CLI golden. The governance scene
uses the same commands and outcomes as ``scripts/smoke_workflow.py``. Keeping
the data and renderer together makes every retained PNG/GIF reproducible and
removes manual terminal captures from the public documentation workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
GOLDEN_DIR = ROOT / "tests" / "golden" / "cases"
OUTPUTS = ("hero.gif", "isolation.png", "governance.png")
FONT_PATH = ASSET_DIR / "DejaVuSansMono.ttf"
SMOKE_PATH = ROOT / "scripts" / "smoke_workflow.py"
CONTRACT_KEY = "docket-render-contract"

WIDTH = 1200
HEIGHT = 700
TITLE_HEIGHT = 48
PADDING = 34
LINE_HEIGHT = 28
FONT_SIZE = 19

BACKGROUND = "#111827"
TITLEBAR = "#1f2937"
TEXT = "#e5e7eb"
MUTED = "#94a3b8"
BLUE = "#7dd3fc"
GREEN = "#86efac"
YELLOW = "#fde68a"
RED = "#fda4af"


# The vendored, licensed font keeps glyphs and layout identical on Linux and macOS.
REGULAR = ImageFont.truetype(str(FONT_PATH), FONT_SIZE)
BOLD = REGULAR


def _golden_lines(relative: str) -> list[str]:
    """Load one current CLI golden and remove its harness-only exit marker."""

    raw = (GOLDEN_DIR / relative).read_text(encoding="utf-8")
    lines = raw.replace("<HOME>", "~").splitlines()
    if lines and lines[0].startswith("EXIT:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def _wrapped(lines: list[str], *, columns: int = 98) -> list[str]:
    result: list[str] = []
    for line in lines:
        if not line:
            result.append("")
            continue
        indent = len(line) - len(line.lstrip())
        result.extend(
            textwrap.wrap(
                line,
                width=columns,
                subsequent_indent=" " * indent,
                replace_whitespace=False,
                drop_whitespace=False,
            )
            or [""]
        )
    return result


def _line_style(line: str) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    stripped = line.lstrip()
    if stripped.startswith("$"):
        return BLUE, BOLD
    if stripped.startswith("✓"):
        return GREEN, BOLD
    if stripped.startswith("⚠"):
        return YELLOW, BOLD
    if stripped.startswith(("✗", "ERROR")):
        return RED, BOLD
    if stripped.startswith(("Project:", "Pod —", "Tool-call gate", "Run evidence")):
        return TEXT, BOLD
    if not stripped:
        return MUTED, REGULAR
    return TEXT, REGULAR


def _terminal(title: str, lines: list[str], *, height: int = HEIGHT) -> Image.Image:
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, TITLE_HEIGHT), fill=TITLEBAR)
    for x, color in ((28, RED), (52, YELLOW), (76, GREEN)):
        draw.ellipse((x - 7, 17, x + 7, 31), fill=color)
    title_width = draw.textlength(title, font=REGULAR)
    draw.text(((WIDTH - title_width) / 2, 13), title, font=REGULAR, fill=MUTED)

    y = TITLE_HEIGHT + PADDING
    for line in _wrapped(lines):
        if y + LINE_HEIGHT > height - PADDING:
            break
        color, font = _line_style(line)
        draw.text((PADDING, y), line, font=font, fill=color)
        y += LINE_HEIGHT
    return image


def _isolation_lines() -> list[str]:
    golden = _golden_lines("readonly/info_myshop.golden")
    stop = golden.index("Workspace files") if "Workspace files" in golden else len(golden)
    public_lines = [line for line in golden[:stop] if not line.strip().startswith("Telegram:")]
    return [
        "$ docket info myshop",
        *public_lines,
        "Run evidence",
        "  per-project workspace + session key; no shared worker history",
    ]


def _governance_lines() -> list[str]:
    return [
        "$ docket pod myapp dispatch",
        "→ Dispatching 1 pending task through Lead → Implementer → Reviewer → Tester",
        "⚠ waiting_approval — tester hop requires an explicit decision",
        "",
        "$ docket approve apr-demo",
        "✓ Approval granted; the waiting action may now proceed",
        "$ docket pod myapp dispatch",
        "✓ done — five typed hops; measured token usage retained",
        "",
        "$ docket gates status",
        "Tool-call gate",
        "✓ Policy engine + high-risk command classifier: always active",
        "✓ Approval routing: session mode",
        "✓ Workspace isolation: pod resources + Implementer worktree",
        "",
        "$ docket audit verify",
        "✓ 2 chained line(s) verified clean",
    ]


def _hero_scenes() -> list[list[str]]:
    isolation = _isolation_lines()
    governance = _governance_lines()
    return [
        [
            "$ docket init",
            "✓ Provisioned project pod myapp: Lead + Implementer",
            "✓ Allocated a dedicated workspace, git worktree, scratch directory, and port range",
            "",
            "Docket owns the turn loop so every tool call crosses one policy chokepoint.",
        ],
        isolation,
        governance[:9],
        [
            *governance[:9],
            "",
            "$ docket runs list",
            "✓ terminal run, task, session, trace, usage, and audit evidence retained",
            "$ docket trace myapp",
            "✓ model request → gated tool call → tool result → final turn",
        ],
    ]


def _render_contract() -> str:
    """Fingerprint every source that can change the public visual story."""

    sources = (
        Path(__file__).read_bytes(),
        FONT_PATH.read_bytes(),
        (GOLDEN_DIR / "readonly/info_myshop.golden").read_bytes(),
        SMOKE_PATH.read_bytes(),
    )
    return hashlib.sha256(b"\0".join(sources)).hexdigest()


def _write_assets(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    contract = _render_contract()
    png_info = PngInfo()
    png_info.add_text(CONTRACT_KEY, contract)
    _terminal("docket — project isolation", _isolation_lines()).save(
        target / "isolation.png", optimize=True, pnginfo=png_info
    )
    _terminal("docket — governed turn", _governance_lines()).save(
        target / "governance.png", optimize=True, pnginfo=png_info
    )

    frames = [_terminal("docket — govern agent work", scene) for scene in _hero_scenes()]
    frames[0].save(
        target / "hero.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[1800, 2400, 2600, 3200],
        loop=0,
        optimize=True,
        disposal=2,
        comment=f"{CONTRACT_KEY}:{contract}".encode(),
    )


def _contract_value(image: Image.Image) -> str | None:
    if image.format == "PNG":
        value = image.info.get(CONTRACT_KEY)
        return value if isinstance(value, str) else None
    comment = image.info.get("comment")
    prefix = f"{CONTRACT_KEY}:".encode()
    if isinstance(comment, bytes) and comment.startswith(prefix):
        return comment.removeprefix(prefix).decode("ascii", errors="strict")
    return None


def _same_render_contract(left_path: Path, right_path: Path) -> bool:
    """Compare source fingerprint and structural output across host rasterizers."""

    with Image.open(left_path) as left, Image.open(right_path) as right:
        if left.format != right.format or left.n_frames != right.n_frames:
            return False
        if left.size != right.size or left.mode != right.mode:
            return False
        if _contract_value(left) != _contract_value(right):
            return False
        if left.info.get("loop") != right.info.get("loop"):
            return False
        for frame_index in range(left.n_frames):
            left.seek(frame_index)
            right.seek(frame_index)
            if left.info.get("duration") != right.info.get("duration"):
                return False
    return True


def _check() -> int:
    with tempfile.TemporaryDirectory(prefix="docket-doc-assets-") as tmp:
        generated = Path(tmp)
        _write_assets(generated)
        drift = [
            name
            for name in OUTPUTS
            if not (ASSET_DIR / name).is_file()
            or not _same_render_contract(ASSET_DIR / name, generated / name)
        ]
    if drift:
        print("documentation asset drift: " + ", ".join(drift))
        print("run: uv run python scripts/render-doc-assets.py")
        return 1
    print("documentation assets are reproducible: " + ", ".join(OUTPUTS))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when committed assets drift")
    args = parser.parse_args()
    if args.check:
        return _check()
    _write_assets(ASSET_DIR)
    print("wrote " + ", ".join(str(ASSET_DIR / name) for name in OUTPUTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
