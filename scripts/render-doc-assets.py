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
WORDMARK = "docket"

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
    # The wordmark sits left of the traffic lights' gap; the scene title stays centred.
    draw.text((104, 13), WORDMARK, font=REGULAR, fill=TEXT)
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
# lines or path prefixes, and a trailing "# ..." on a "$" line is a reader's note, never
# captured output.
_TEAM = [
    "$ docket models preset local",
    "$ docket init --recipe secure-build",
    "⋯",
    "→ Provisioning 'software' pod 'myapp' (lead, implementer)...",
    "✓   myapp-lead  [lead]  local/local-model",
    "✓   myapp-implementer  [implementer]  local/local-model",
    "Apply plan — myapp <- ⋯/templates/recipes/secure-build",
    "  [add] role: security-vetter",
    "  [add] policy: require-approval-secret-writes.yaml",
    "  [add] member: security-vetter",
    "  [add] pipeline: pipeline.yaml",
    "✓ Applied 4 change(s) to pod 'myapp' from ⋯/templates/recipes/secure-build.",
    "$ docket pod myapp export                  # the team, written back next to the code",
    "✓ Exported pod 'myapp' to ~/code/myapp/.docket.",
    "$ find .docket -type f | sort",
    ".docket/pipeline.yaml",
    ".docket/pod.yaml",
    ".docket/policies/require-approval-secret-writes.yaml",
    ".docket/roles/security-vetter.md",
    ".docket/roles/security-vetter.yaml",
]

_PLAN = [
    "$ docket validate                          # every file starts with kind:",
    "ok ~/code/myapp/.docket/roles/security-vetter.yaml (role security-vetter)",
    "ok ~/code/myapp/.docket/policies/require-approval-secret-writes.yaml "
    "(policy secure-build-secret-writes)",
    "ok ~/code/myapp/.docket/pipeline.yaml (pipeline secure-build)",
    "ok ~/code/myapp/.docket/pod.yaml (pod myapp)",
    "$ docket pipeline plan myapp",
    "Pipeline plan — myapp",
    "Source: bound pipeline (hash 45f7aaf31d1f...)",
    "Pipeline: secure-build",
    "  [plan] role=lead -> myapp-lead [gate: none]",
    "  [build] role=implementer -> myapp-implementer [gate: mechanical(verifyCmd)]",
    "  [vet] role=security-vetter -> myapp-security-vetter [gate: verdict(approve, rework->build)]",
    "$ docket pod myapp set-verify myapp-implementer \\",
    "    \"python3 -c 'import calc; assert calc.add(2, 3) == 5'\"",
    "✓ Set verify command for myapp-implementer: "
    "\"python3 -c 'import calc; assert calc.add(2, 3) == 5'\"",
    '$ docket pod myapp delegate "Fix calc.add so it returns the sum of a and b"',
    "✓ Queued for pod 'myapp': [task-efbd46e7-d7ce-4f7a-b787-d6c8abfd3cf6] Fix calc.add so it "
    "returns the sum of a and b",
]

_DISPATCH = [
    "$ docket pod myapp dispatch",
    "→ Dispatching 1 pending task(s) through: lead → implementer → security-vetter",
    "✓   [task-efbd46e7-d7ce-4f7a-b787-d6c8abfd3cf6] done — 3 hop(s), $0.0000",
    "$ docket trace agent:myapp:task-efbd46e7-d7ce-4f7a-b787-d6c8abfd3cf6",
    "  2026-09-27T19:47:54  session_start              (lead)",
    "  ⋯",
    "  2026-09-27T19:48:19  tool_result                (lead)  text=## Plan for Implementer",
    "  ⋯",
    "  2026-09-27T19:48:50  tool_result                (implementer)  text=The fix is complete. "
    "I changed `calc.add` to return `a + b` instead of `a - b`. The verification gate passes",
    "  ⋯",
    "  2026-09-27T19:49:07  tool_result                (security-vetter)  text=The `calc.py` "
    "file now correctly implements `add` with `return a + b`.",
    "⋯",
    "- **Secrets:** No credentials or secrets in the file.",
    "⋯",
    "APPROVE",
    "  2026-09-27T19:49:07  session_end                (lead)  status=done",
]

_RECORD = [
    "$ docket config explain myapp-implementer",
    "Effective configuration — myapp-implementer",
    "  Role:            implementer",
    "  Pod:             myapp",
    "  Model:           local/local-model  (policy)",
    "  Endpoint:        http://127.0.0.1:8081/v1  (ready)",
    "  Provider:        local  (global, openai-chat)",
    "  Credential:      (none)  (none)",
    "⋯",
    "  Tools allowed: bash, edit, fetch, glob, grep, read, write",
    "⋯",
    "│ secure-build-secret-writes │ pre_tool_call │ require_approval │",
    "⋯",
    "  Pipeline:        bound pipeline (hash 45f7aaf31d1f...)",
    "  Config source:   ⋯/templates/recipes/secure-build  (digest 441848f22bd2..., drift: no)",
    "⋯",
    "$ docket audit verify",
    "✓ 8 chained line(s) verified clean.",
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
    "~/code/myapp                                              125d81a [main]",
    "~/.docket/workspaces/projects/myapp-implementer/tasks/task-6f1c2a9e-4b7d-4e0a-9c35-8d2f7a1b0c64  125d81a "
    "[docket/myapp/task-6f1c2a9e-4b7d-4e0a-9c35-8d2f7a1b0c64]",
    "$ git status --short                       # your checkout: only the exported team",
    "?? .docket/",
    "$ git -C ~/.docket/workspaces/projects/myapp-implementer/tasks/task-6f1c2a9e-4b7d-4e0a-9c35-8d2f7a1b0c64 diff",
    "⋯",
    "@@ -1,2 +1,2 @@",
    " def add(a, b):",
    "-    return a - b",
    "+    return a + b",
]

_GATE = [
    "$ docket policies test pre_tool_call implementer 'git push origin production'",
    "  Result: ask",
    "  Reason: matches high-risk action class 'prod-deploy': Production deploys and release pushes",
    "  Policy: 'high-risk-deploy' -> require_approval",
    "$ docket pod myapp delegate \\",
    '    "Publish the fix: run exactly this bash command once and report its output: '
    'git push origin production"',
    "$ docket pod myapp dispatch",
    "→ Dispatching 1 pending task(s) through: lead → implementer → security-vetter",
    "✓   [task-d4f97e63-0842-4c79-9e44-5e1df1318f8b] done — 3 hop(s), $0.0000",
    "$ docket audit",
    "  ⋯",
    "  2026-09-27T19:49:30.146Z  demo        tool.ask          tool=bash agent=myapp-implementer "
    "role=implementer project=myapp policy_id='high-risk-deploy' policy_action='require_approval' ⋯",
    "  2026-09-27T19:51:30.180Z  demo        approval.deny     "
    "token=apr-e480b929-4092-47c7-a541-4137f438098d project=myapp channel=timeout",
    "$ docket audit verify",
    "✓ 8 chained line(s) verified clean.",
]


_HERO_TITLES = ("the team you define", "validate, plan, queue", "the run", "the record")


def _hero_scenes() -> list[list[str]]:
    return [_TEAM, _PLAN, _DISPATCH, _RECORD]


def _render_contract() -> str:
    """Fingerprint every source that can change the public visual story."""

    sources = (Path(__file__).read_bytes(), FONT_PATH.read_bytes())
    return hashlib.sha256(b"\0".join(sources)).hexdigest()


def _write_assets(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    contract = _render_contract()
    png_info = PngInfo()
    png_info.add_text(CONTRACT_KEY, contract)
    _terminal("pod isolation", _ISOLATION, height=_fit_height(_ISOLATION)).save(
        target / "isolation.png", optimize=True, pnginfo=png_info
    )
    _terminal("the tool-call gate", _GATE, height=_fit_height(_GATE)).save(
        target / "governance.png", optimize=True, pnginfo=png_info
    )

    frames = [
        _terminal(title, scene) for title, scene in zip(_HERO_TITLES, _hero_scenes(), strict=True)
    ]
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
