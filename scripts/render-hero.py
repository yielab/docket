#!/usr/bin/env python3
"""Render docs/assets/hero.gif — a synthetic terminal animation.

This is the reproducible source for the hero GIF. It needs no live OpenClaw
install: the terminal output is canned demo data using anonymized agent names
(webapp / api / blog — never real client names).

Positioning rule (see internal-docs/COST-FEATURE-AUDIT.md): the GIF MUST lead
with provisioning + isolation and treat the budget as a guardrail tail. The
centerpiece screen is `docket info` (session-key isolation), NOT a cost table.

Usage:  python3 scripts/render-hero.py
Deps:   Pillow.  Style: Catppuccin Mocha, FiraCode Nerd Font.
"""
import os
from PIL import Image, ImageDraw, ImageFont

# ─── Catppuccin Mocha palette ────────────────────────────────────────────────
BASE     = (30, 30, 46)      # #1e1e2e  background
TITLEBAR = (43, 43, 64)      # #2b2b40  title bar
TEXT     = (205, 214, 244)   # #cdd6f4
SUBTEXT  = (186, 194, 222)   # #bac2de
OVERLAY  = (108, 112, 134)   # #6c7086  dim / prompts / (policy)
GREEN    = (166, 227, 161)   # #a6e3a1  ✓ / ● up
SKY      = (137, 220, 235)   # #89dceb  subcommand
BLUE     = (137, 180, 250)   # #89b4fa  agent ids / docket
MAUVE    = (203, 166, 247)   # #cba6f7
YELLOW   = (249, 226, 175)   # #f9e2af  flags / values
PEACH    = (250, 179, 135)   # #fab387  isolation callout
RED      = (243, 139, 168)
TEAL     = (148, 226, 213)

W, H = 940, 868
PAD_X = 30
TOP = 64
LINE = 30
FONT_SIZE = 21

FONT_DIR = os.path.expanduser("~/.local/share/fonts")
REG = ImageFont.truetype(os.path.join(FONT_DIR, "FiraCodeNerdFont-Retina.ttf"), FONT_SIZE)
BOLD = ImageFont.truetype(os.path.join(FONT_DIR, "FiraCodeNerdFont-Bold.ttf"), FONT_SIZE)
TITLE_FONT = ImageFont.truetype(os.path.join(FONT_DIR, "FiraCodeNerdFont-Retina.ttf"), 17)

# A "span" is (text, color, bold?). A "line" is a list of spans.
def S(text, color=TEXT, bold=False):
    return (text, color, bold)

# ─── The narrative (final state of each command block) ───────────────────────
# Each block = (prompt_spans, [output_line_spans, ...])
BLOCKS = [
    # 1. Provision an isolated agent — the core purpose, first.
    (
        [S("$ ", OVERLAY), S("docket ", BLUE, True), S("add ", SKY), S("webapp ", BLUE), S("~/code/webapp", SUBTEXT)],
        [
            [S("✓ ", GREEN), S("Provisioned: ", TEXT), S("webapp ", BLUE), S("(repo, claude-sonnet-4-6)", OVERLAY)],
            [S("  ", TEXT), S("isolated workspace + session key", PEACH)],
            [S("✓ ", GREEN), S("Done — 1 added.", TEXT)],
        ],
    ),
    # 2. The fleet at a glance.
    (
        [S("$ ", OVERLAY), S("docket ", BLUE, True), S("list", SKY)],
        [
            [S("OpenClaw  ", TEXT, True), S("● ", GREEN), S("gateway up  ", SUBTEXT), S("● ", GREEN), S("telegram on  ", SUBTEXT), S("│  ", OVERLAY), S("3 agents", SUBTEXT)],
            [S("  webapp  ", BLUE), S("repo  ", SUBTEXT), S("claude-sonnet-4-6  ", TEXT), S("(policy)   ", OVERLAY), S("● ", GREEN), S("isolated", SUBTEXT)],
            [S("  api     ", BLUE), S("repo  ", SUBTEXT), S("claude-sonnet-4-6  ", TEXT), S("(policy)   ", OVERLAY), S("● ", GREEN), S("isolated", SUBTEXT)],
            [S("  blog    ", BLUE), S("task  ", SUBTEXT), S("claude-haiku-4-5   ", TEXT), S("(policy)   ", OVERLAY), S("● ", GREEN), S("isolated", SUBTEXT)],
        ],
    ),
    # 3. Isolation — the centerpiece (replaces the old cost-table screen).
    (
        [S("$ ", OVERLAY), S("docket ", BLUE, True), S("info ", SKY), S("webapp", BLUE)],
        [
            [S("  Codebase:     ", SUBTEXT, True), S("~/code/webapp", TEXT)],
            [S("  Workspace:    ", SUBTEXT, True), S("~/.openclaw/workspaces/projects/webapp  ", TEXT), S("(700)", OVERLAY)],
            [S("  Session key:  ", SUBTEXT, True), S("agent:webapp:webapp   ", TEXT), S("← no cross-project leak", PEACH)],
            [S("  Model:        ", SUBTEXT, True), S("claude-sonnet-4-6 ", TEXT), S("(policy)", OVERLAY)],
            [S("  Memory:       ", SUBTEXT, True), S("isolated · daily logs", TEXT)],
        ],
    ),
    # 4. Keep the fleet healthy.
    (
        [S("$ ", OVERLAY), S("docket ", BLUE, True), S("doctor", SKY)],
        [
            [S("✓ ", GREEN), S("Gateway service: active", TEXT)],
            [S("✓ ", GREEN), S("Config drift (meta ↔ openclaw.json): in sync", TEXT)],
            [S("✓ ", GREEN), S("Session keys: unique per project (no leak)", TEXT)],
            [S("✓ ", GREEN), S("Fleet healthy", GREEN, True)],
        ],
    ),
    # 5. Budget guardrail — last, not the headline.
    (
        [S("$ ", OVERLAY), S("docket ", BLUE, True), S("profile ", SKY), S("webapp ", BLUE), S("--budget ", SUBTEXT), S("10", YELLOW)],
        [
            [S("✓ ", GREEN), S("Budget guardrail set: ", TEXT), S("webapp ", BLUE), S("pauses if spend exceeds ", TEXT), S("$10", YELLOW)],
        ],
    ),
]


def base_frame():
    img = Image.new("RGB", (W, H), BASE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 42], fill=TITLEBAR)
    for cx, col in ((33, RED), (57, YELLOW), (81, GREEN)):
        d.ellipse([cx - 7, 14, cx + 7, 28], fill=col)
    title = "docket — OpenClaw fleet ops"
    tw = d.textlength(title, font=TITLE_FONT)
    d.text(((W - tw) / 2, 13), title, font=TITLE_FONT, fill=OVERLAY)
    return img, d


def draw_line(d, y, spans, cursor_after=None):
    """Draw a line of spans at vertical y. cursor_after: char-limit for the
    last partial span (typing effect) — if set, only that span is truncated
    and a block cursor is drawn."""
    x = PAD_X
    for i, (text, color, bold) in enumerate(spans):
        f = BOLD if bold else REG
        d.text((x, y), text, font=f, fill=color)
        x += d.textlength(text, font=f)
    if cursor_after is not None:
        d.rectangle([x, y + 3, x + 11, y + FONT_SIZE + 4], fill=SUBTEXT)


def render(committed, typing_prompt=None, typed_chars=0, show_cursor=False):
    """committed: list of finished lines. typing_prompt: spans being typed."""
    img, d = base_frame()
    y = TOP
    for line in committed:
        draw_line(d, y, line)
        y += LINE
    if typing_prompt is not None:
        # reveal typing_prompt up to typed_chars (across spans)
        partial, remaining = [], typed_chars
        for text, color, bold in typing_prompt:
            if remaining <= 0:
                break
            chunk = text[:remaining]
            partial.append((chunk, color, bold))
            remaining -= len(chunk)
        draw_line(d, y, partial, cursor_after=0 if show_cursor else None)
    return img


def main():
    frames, durations = [], []

    def add(img, ms):
        frames.append(img)
        durations.append(ms)

    committed = []
    add(render(committed), 700)  # initial pause

    for prompt, outputs in BLOCKS:
        nchars = sum(len(t) for t, _, _ in prompt)
        # typing animation: ~2 chars/frame
        c = 0
        while c < nchars:
            c = min(nchars, c + 3)
            add(render(committed, prompt, c, show_cursor=True), 55)
        add(render(committed, prompt, nchars, show_cursor=True), 380)  # pause before run
        committed.append(prompt)
        # reveal output lines one at a time
        for out_line in outputs:
            committed.append(out_line)
            add(render(committed), 90)
        committed.append([S("", TEXT)])  # blank spacer line
        add(render(committed), 1500)  # hold

    durations[-1] = 2600  # linger on final frame

    out = os.path.join(os.path.dirname(__file__), "..", "docs", "assets", "hero.gif")
    out = os.path.normpath(out)
    # Additive frames (disposal=1) let the optimizer store only per-frame diffs
    # instead of repainting the full 940x868 canvas each frame — much smaller.
    frames[0].save(
        out, save_all=True, append_images=frames[1:],
        duration=durations, loop=0, optimize=True, disposal=1,
    )
    print(f"wrote {out}: {len(frames)} frames, {sum(durations)/1000:.1f}s")


if __name__ == "__main__":
    main()
