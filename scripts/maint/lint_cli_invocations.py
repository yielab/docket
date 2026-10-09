#!/usr/bin/env python3
"""Check every `docket ...` invocation in the given files against the live Click tree.

Only inline code spans, fenced blocks and lines that start with `docket` count; prose
such as "docket writes" is skipped. Each word must be a verb of its group, each option
an option of its leaf and the positional count must fit. Placeholders (`<x>`, `[x]`,
`UPPER`, `...`, `$VAR`, quoted text) stand for values; where a verb is expected only `<x>`,
`[x]` and `...` do, and the rest of a `<a|b>` line must fit at least one of those verbs. A spec's
`## Changelog` is the record and is cut.

Usage: lint_cli_invocations.py [--self-check] FILE...  (prints file:line: invocation: reason)
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import typer.main

from docket.cli import app

ROOT_CMD: Any = typer.main.get_command(app)
SPAN = re.compile(r"`([^`]*)`")
STOP_WORDS = {"|", "||", "&&", ";", "#", ">", ">>", "<", "2>", "2>&1", "\\"}
HELP = {"-h", "--help"}
# Printed output and quoted literals that open with the word docket, not commands.
OUTPUT_LITERALS = (
    "docket - ",  # a header in the plain console voice ("docket - Apply plan myapp")
    "docket smoke ok",
    "docket release journey ok",
    "docket starter approved",
    "docket is running and will pick it up",
    "docket exec: run ",
    "docket \u00b7 ",
)
RECORD_HEADING = "## Changelog"
PLANTED = (
    ("docket task list --retry", True),
    ("docket - Apply plan myapp <- .../templates/recipes/secure-build", False),
    ("docket status <agent>", True),
    ("docket setup sandbox isolate on", True),
    ("docket task FOO", True),
    ("docket pod $VERB --json", True),
    ("docket pod <apply|export> a b c", True),
    ("docket setup <provider|model> list --bogus", True),
    ("docket setup <provider|model> list", False),
    ("docket pod <recipes|roles|policies> NAME", False),
    ("docket task <verb> ...", False),
    ("docket task add 'two words' --pod p", False),
    ("docket pod set KEY VALUE [--member ID]", False),
    ("docket log 50", False),
    ("docket --version", False),
    ("docket task list | head", False),
)


def _placeholder(w: str) -> bool:
    return w[0] in "<[\"'{$" or w == "..." or re.fullmatch(r"[A-Z][A-Z0-9_./-]*", w) is not None


def _verb_placeholder(w: str) -> bool:
    """Only a bracketed placeholder may stand where a verb goes; `FOO` and `$X` are not verbs."""
    return w[0] in "<[" or w == "..."


VERB_ALTERNATIVES = re.compile(r"<([a-z-]+(?:\|[a-z-]+)+)>")


def invocations(line: str, in_fence: bool) -> list[str]:
    """Every `docket ...` command text on one line."""
    line = line.replace("\\|", "|")
    found: list[str] = []
    if in_fence or re.match(r"^\s*\$\s+docket(\s|$)", line):
        text = re.split(r"\s{2,}", line.strip())[0]
        text = text[2:] if text.startswith("$ ") else text
        if text.startswith("docket ") or text == "docket":
            found.append(text)
        return [f for f in found if not f.startswith(OUTPUT_LITERALS)]
    for span in SPAN.findall(line):
        s = span.strip()
        if s.startswith("docket ") or s == "docket":
            found.append(s)
    return [f for f in found if not f.startswith(OUTPUT_LITERALS)]


def split(text: str) -> list[str]:
    """Words of an invocation up to the first shell operator or comment."""
    try:
        raw = shlex.split(text, posix=True)
    except ValueError:
        raw = text.split()
    out: list[str] = []
    skip_values = False
    for w in raw:
        if w in STOP_WORDS or w.startswith("#"):
            break
        w = w.rstrip("\\")
        if not re.match(r"\[[^-<\"'$]", w):
            w = w.strip("[](),")
        if not w or (skip_values and not w.startswith("-")):
            continue
        skip_values = "|--" in w
        out.append(w.split("|--")[0] if skip_values else w)
    return out


def _placeholder_verbs(node: Any, w: str) -> str | None:
    """A `<a|b|c>` verb placeholder lists live verbs; any other placeholder is unchecked."""
    m = VERB_ALTERNATIVES.fullmatch(w)
    missing = [a for a in m.group(1).split("|") if a not in node.commands] if m else []
    return f"'{missing[0]}' is not a verb of '{node.name}'" if missing else None


def _walk_verbs(words: list[str]) -> tuple[Any, int, str | None]:
    node = ROOT_CMD
    i = 0
    while i < len(words) and getattr(node, "commands", None) is not None:
        w = words[i]
        if w.startswith("-") or _verb_placeholder(w):
            return node, i, _placeholder_verbs(node, w)
        if _placeholder(w):
            return node, i, f"'{w}' is not a verb of '{node.name or 'docket'}'"
        alts = [a for a in re.split(r"[|/]", w) if a]
        if all(a in node.commands for a in alts):
            node = node.commands[alts[0]]
            i += 1
            continue
        if node is not ROOT_CMD and getattr(node, "invoke_without_command", False) and w.isdigit():
            break
        return node, i, f"'{w}' is not a verb of '{node.name or 'docket'}'"
    return node, i, None


def _check_rest(node: Any, words: list[str], i: int) -> str | None:
    params = {o: p for p in node.params for o in getattr(p, "opts", [])}
    max_pos = sum(
        1 if p.nargs == 1 else 10**6 for p in node.params if p.param_type_name == "argument"
    )
    is_group = getattr(node, "commands", None) is not None
    positional = 0
    j = i
    while j < len(words) and words[j] != "--":
        w = words[j]
        if w.startswith("-") and not w.startswith("-<"):
            names = w.split("=")[0].split("|")
            name = names[0]
            if any(n not in HELP and n not in params for n in names):
                where = f"group '{node.name}'" if is_group else f"'{' '.join(words[:i])}'"
                return f"'{w.split('=')[0]}' is not an option of {where}"
            takes = name in params and not getattr(params[name], "is_flag", False) and "=" not in w
            j += 2 if takes else 1
            continue
        if is_group and not _verb_placeholder(w):
            if not (getattr(node, "invoke_without_command", False) and w.isdigit()):
                return f"'{w}' is not a verb of '{node.name}'"
        else:
            positional += 1
        j += 1
    if not is_group and positional > max_pos:
        return f"'{' '.join(words[:i])}' takes {max_pos} positional argument(s), got {positional}"
    return None


def problems(words: list[str]) -> str | None:
    """Why `docket <words>` is not a live invocation, or None."""
    node, i, why = _walk_verbs(words)
    if why:
        return why
    if i < len(words) and getattr(node, "commands", None) is not None:
        alternatives = VERB_ALTERNATIVES.fullmatch(words[i])
        if alternatives is None:
            return None if words[i].startswith("<") else _check_rest(node, words, i)
        failures: list[str] = []
        for verb in alternatives.group(1).split("|"):
            why = problems([*words[:i], verb, *words[i + 1 :]])
            if why is None:
                return None
            failures.append(f"as '{verb}': {why}")
        return failures[0]
    return _check_rest(node, words, i)


def lint_text(label: str, text: str) -> list[str]:
    """Findings `label:line: invocation: reason` for one document."""
    hits: list[str] = []
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        for inv in invocations(line, in_fence):
            words = split(inv)[1:]
            why = problems(words) if words else None
            if why:
                hits.append(f"{label}:{n}: {inv[:90]}: {why}")
    return hits


def editable(path: Path, text: str) -> str:
    """The text of a document without a spec's changelog record."""
    if "specs" not in path.parts:
        return text
    lines = text.splitlines(keepends=True)
    for n, line in enumerate(lines):
        if line.rstrip("\n") == RECORD_HEADING:
            return "".join(lines[:n])
    return text


def leaf_examples() -> Iterator[tuple[str, str]]:
    """(command path, Example: line) for every leaf of the live tree."""
    stack: list[tuple[str, Any]] = [("docket", ROOT_CMD)]
    while stack:
        name, node = stack.pop()
        for child_name, child in sorted(getattr(node, "commands", {}).items()):
            stack.append((f"{name} {child_name}", child))
        if getattr(node, "commands", None) is None:
            for line in (node.help or "").splitlines():
                if line.strip().startswith("Example:"):
                    yield name, line.strip().removeprefix("Example:").strip()


def lint_examples() -> list[str]:
    """Findings for the `Example:` line of every leaf's help."""
    hits: list[str] = []
    for name, example in leaf_examples():
        for inv in invocations(example, False) or [example]:
            words = split(inv)[1:]
            why = problems(words) if inv.startswith("docket") and words else None
            if why:
                hits.append(f"help of '{name}': {inv[:90]}: {why}")
    return hits


def lint(paths: Iterable[Path]) -> list[str]:
    """Findings over files, cutting each spec's changelog."""
    hits: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits += lint_text(str(path), editable(path, text))
    return hits


def self_check() -> list[str]:
    """Problems with the linter itself: a planted line missed or a true one flagged."""
    out: list[str] = []
    for line, false in PLANTED:
        found = lint_text("planted", f"`{line}`\n")
        if bool(found) != false:
            out.append(f"{line}: expected {'a finding' if false else 'none'}, got {found}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint docket invocations against the live tree.")
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--self-check", action="store_true", help="plant false lines, expect them back")
    args = ap.parse_args(argv)
    if args.self_check:
        problems_found = self_check()
        print("\n".join(problems_found))
        return 1 if problems_found else 0
    hits = lint(args.files)
    print("\n".join(hits))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
