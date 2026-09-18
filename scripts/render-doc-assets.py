#!/usr/bin/env python3
"""Render the complete public terminal-visual set from one real captured journey.

``scripts/maint/capture-doc-journey.sh`` drives the real CLI against a live model and writes one
transcript per scene; the scenes below transcribe that output. Keeping the data and renderer
together makes every retained PNG/GIF reproducible without a model or a terminal screenshot.
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
OUTPUTS = ("hero.gif", "isolation.png", "governance.png")
FONT_PATH = ASSET_DIR / "DejaVuSansMono.ttf"
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
    if stripped.startswith("✓") or line.startswith("+"):
        return GREEN, BOLD
    if stripped.startswith(("⚠", "Result:")):
        return YELLOW, BOLD
    if stripped.startswith(("✗", "ERROR")) or line.startswith("-"):
        return RED, BOLD
    if stripped.startswith(("Project:", "Pod —")):
        return TEXT, BOLD
    if not stripped or stripped.startswith(("⋯", "→", "@@")):
        return MUTED, REGULAR
    return TEXT, REGULAR


def _styled(
    lines: list[str],
) -> list[tuple[str, str, ImageFont.FreeTypeFont | ImageFont.ImageFont]]:
    """Wrap every line, keeping a command's style across wraps and backslash continuations."""

    result: list[tuple[str, str, ImageFont.FreeTypeFont | ImageFont.ImageFont]] = []
    continued = False
    for line in lines:
        color, font = _line_style("$" if continued else line)
        for piece in _wrapped([line]):
            result.append((piece, color, font))
        continued = line.lstrip().startswith("$") or continued
        continued = continued and line.endswith("\\")
    return result


def _fit_height(lines: list[str]) -> int:
    """The smallest frame height that shows every wrapped line of a still image."""

    return max(HEIGHT, TITLE_HEIGHT + 2 * PADDING + LINE_HEIGHT * len(_styled(lines)))


def _terminal(title: str, lines: list[str], *, height: int = HEIGHT) -> Image.Image:
    styled = _styled(lines)
    if TITLE_HEIGHT + 2 * PADDING + LINE_HEIGHT * len(styled) > height:
        raise SystemExit(f"scene {title!r} needs {len(styled)} lines; it would be cut off")
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, TITLE_HEIGHT), fill=TITLEBAR)
    for x, color in ((28, RED), (52, YELLOW), (76, GREEN)):
        draw.ellipse((x - 7, 17, x + 7, 31), fill=color)
    title_width = draw.textlength(title, font=REGULAR)
    draw.text(((WIDTH - title_width) / 2, 13), title, font=REGULAR, fill=MUTED)

    y = TITLE_HEIGHT + PADDING
    for piece, color, font in styled:
        draw.text((PADDING, y), piece, font=font, fill=color)
        y += LINE_HEIGHT
    return image


# Every scene below is a verbatim transcript of one real run of
# scripts/maint/capture-doc-journey.sh; docs/assets/README.md records which run. Only
# three edits are allowed when refreshing it: the capture root becomes "~", "⋯" marks elided
# lines, and a trailing "# ..." on a "$" line is a reader's note, never captured output.
_INIT = [
    "$ docket models preset local",
    "⋯",
    "✓ Preset 'local' applied.",
    "⋯",
    "✓ Registered local endpoint selected; no API key needed.",
    "$ docket init",
    "⋯",
    "✓ Tool-call gate: always active (policy engine + high-risk command classifier)",
    "✓ Installed 6 baseline policies",
    "⋯",
    "→ Provisioning 'software' pod 'myapp' (lead, implementer)...",
    "✓   myapp-lead  [lead]  local/local-model",
    "✓   myapp-implementer  [implementer]  local/local-model",
    "$ docket pod myapp add reviewer",
    "✓ Added myapp-reviewer [reviewer] local/local-model",
    "$ docket pod myapp set-verify myapp-implementer \\",
    "    \"python3 -c 'import calc; assert calc.add(2, 3) == 5'\"",
    "✓ Set verify command for myapp-implementer: "
    "\"python3 -c 'import calc; assert calc.add(2, 3) == 5'\"",
]

_DISPATCH = [
    '$ docket pod myapp delegate "Fix calc.add so it returns the sum of a and b"',
    "✓ Queued for pod 'myapp': [task-992eeb02-6cef-422d-af5d-339f0511cfcd] Fix calc.add so it "
    "returns the sum of a and b",
    "$ docket pod myapp dispatch",
    "→ Dispatching 1 pending task(s) through: lead → implementer → reviewer",
    "✓   [task-992eeb02-6cef-422d-af5d-339f0511cfcd] done — 3 hop(s), $0.0000",
    "$ docket trace agent:myapp:task-992eeb02-6cef-422d-af5d-339f0511cfcd",
    "  2026-09-18T13:02:18  session_start              (lead)",
    "  ⋯",
    "  2026-09-18T13:02:48  context_composed           (implementer)",
    "  ⋯",
    "  2026-09-18T13:03:35  context_composed           (reviewer)",
    "  ⋯",
    "  2026-09-18T13:04:41  tool_result                (reviewer)  text=I've reviewed the "
    "implementation. The change is straightforward and correct:",
    "⋯",
    "APPROVE",
    "  2026-09-18T13:04:41  session_end                (lead)  status=done",
]

_ISOLATION = [
    "$ docket info myapp-implementer",
    "Project: myapp implementer (myapp-implementer)",
    "  Workspace:         ~/.docket/workspaces/projects/myapp-implementer",
    "  Codebase:          ~/code/myapp",
    "  Model:             local/local-model",
    "  Session Key:       agent:myapp:default",
    "  Project Scope:     default",
    "⋯",
    "$ git worktree list",
    "~/code/myapp                                              f5d53b3 [main]",
    "~/.docket/workspaces/projects/myapp-implementer/worktree  f5d53b3 "
    "[docket/myapp/myapp-implementer]",
    "$ git status --short                       # your checkout: untouched",
    "$ git -C ~/.docket/workspaces/projects/myapp-implementer/worktree diff",
    "⋯",
    "@@ -1,2 +1,2 @@",
    " def add(a, b):",
    "-    return a - b",
    "+    return a + b",
]

_GATE = [
    "$ docket policies test pre_tool_call implementer 'git push origin production'",
    "  Result: require_approval",
    "$ docket pod myapp delegate \\",
    '    "Publish the fix: run exactly this bash command once and report its output: '
    'git push origin production"',
    "$ docket pod myapp dispatch",
    "→ Dispatching 1 pending task(s) through: lead → implementer → reviewer",
    "✓   [task-fdbcb619-28bd-4ad4-b174-6f0e68497d9d] done — 3 hop(s), $0.0000",
    "$ docket audit",
    "  ⋯",
    "  2026-09-18T13:05:15.720Z  demo        tool.ask          tool=bash agent=myapp-implementer "
    "role=implementer project=myapp-implementer policy_id='high-risk-deploy' "
    "policy_action='require_approval' ⋯",
    "  2026-09-18T13:07:15.781Z  demo        approval.deny     "
    "token=apr-e3d11049-8601-4011-8e9e-46c5e98bb53e project=myapp-implementer channel=timeout",
    "$ docket trace export myapp | grep '\"deny\"'",
    '{⋯ "agent_role": "implementer", "event_type": "tool_result", "payload": {"tool": "bash", '
    '"callId": "c02cuhNC56eQZyNGRL8RLeKSN1pnWKwX", "decision": "deny", "ok": false, '
    '"executed": false, "denialKind": "approval_timeout", "policyId": "high-risk-deploy", '
    '"reason": "approval timed out and was denied"}}',
    "$ docket audit verify",
    "✓ 6 chained line(s) verified clean.",
]

_HARNESS = [
    "$ export DOCKET_HOME=~/hh DOCKET_LLM_BASE_URL=http://127.0.0.1:8081/v1",
    "$ docket harness run --workspace ~/code/svc --model local/local-model \\",
    "    --task 'Run exactly this bash command: git push origin production' \\",
    "    2>/dev/null | tail -1 | python3 -m json.tool",
    "{",
    '    "v": "1.0.0",',
    '    "token": "run-824ce693-1c71-4333-b781-2ffe641329ea",',
    '    "status": "blocked",',
    "    ⋯",
    '    "blocked": {',
    '        "tool": "bash",',
    '        "call_id": "6Kd4UFWbyWfEfzTwkXwD9boT47aFZRiN",',
    '        "denial_kind": "approval_unavailable",',
    '        "policy_id": "",',
    '        "reason": "matches high-risk action class \'prod-deploy\': Production deploys and '
    'release pushes"',
    "    },",
    "    ⋯",
    '    "run_state": "failed"',
    "}",
]


def _hero_scenes() -> list[list[str]]:
    trace_export = _GATE.index("$ docket trace export myapp | grep '\"deny\"'")
    gate = _GATE[:trace_export] + _GATE[trace_export + 2 :]
    return [_INIT, _DISPATCH, gate, _HARNESS]


def _render_contract() -> str:
    """Fingerprint every source that can change the public visual story."""

    sources = (Path(__file__).read_bytes(), FONT_PATH.read_bytes())
    return hashlib.sha256(b"\0".join(sources)).hexdigest()


def _write_assets(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    contract = _render_contract()
    png_info = PngInfo()
    png_info.add_text(CONTRACT_KEY, contract)
    _terminal("docket — pod isolation", _ISOLATION, height=_fit_height(_ISOLATION)).save(
        target / "isolation.png", optimize=True, pnginfo=png_info
    )
    _terminal("docket — the tool-call gate", _GATE, height=_fit_height(_GATE)).save(
        target / "governance.png", optimize=True, pnginfo=png_info
    )

    frames = [_terminal("docket — govern agent work", scene) for scene in _hero_scenes()]
    frames[0].save(
        target / "hero.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[3200, 3600, 4200, 4200],
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
