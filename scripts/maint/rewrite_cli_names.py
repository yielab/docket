#!/usr/bin/env python3
"""Rewrite invocations of removed docket commands to the eleven-command surface.

Modes: ``--dry-run`` (diff), ``--write`` (idempotent rewrite), ``--check`` (list
surviving invocations of removed names, exit 1), ``--unmappable`` (lines the table
cannot rewrite one to one), ``--self-check`` (every replacement is a live command).
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ROOTS = (
    "src/docket",
    "scripts",
    "tests",
    "examples",
    "benchmarks",
    "docs",
    "specs",
    "README.md",
    "CONTRIBUTING.md",
)

# Paths that are never rewritten or checked: the record, the captured output,
# the frozen contract, working notes and this tool's own fixtures.
EXCLUDED = (
    "docs/cycles-ended",
    "docs/adr",
    "CHANGELOG.md",
    "internal-docs",
    ".agents",
    ".claude",
    "tests/golden/cases",
    "docs/contracts/harness-v1/schema.json",
    "tests/fixtures/harness-contract",
    "scripts/maint/rewrite_cli_names.py",
    "tests/guards/test_no_removed_cli_names.py",
)
EXCLUDED_PARTS = {"__pycache__", ".git", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}

# Exact substrings that look like an invocation and are not one.
ALLOW = (
    "docket harness contract",  # the published contract's schema title
    '"docket help" not in',  # a test asserting the removed word is absent
)

LIVE_POD_VERBS = (
    "show|add|remove|reset|delete|set|unset|apply|export|validate|plan|check|recipes|roles|policies"
)
OLD_POD_ACTIONS = (
    "config|add|info|delete|dispatch|answer|pregrant|roster|lead|maintain|apply|export|members"
    "|remove|reset|set-verify|queue|evidence|corrections|explain|worktrees|sync|delegate|list"
)
REMOVED_TOP_LEVEL = [
    "delegate",
    "dispatch",
    "runs",
    "trace",
    "approve",
    "deny",
    "chat",
    "add",
    "info",
    "delete",
    "maintain",
    "profile",
    "config",
    "pipeline",
    "roles",
    "validate",
    "plugins",
    "recipes",
    "policies",
    "gates",
    "harness",
    "doctor",
    "cost",
    "metrics",
    "snapshot",
    "models",
    "keys",
    "audit",
    "notify",
    "exporters",
    "mcp",
    "serve",
    "list",
    "context",
    "logs",
    "edit",
    "scope",
    "persona",
    "help",
    "conversations",
    "channels",
    "wire",
    "unwire",
    "completions",
]

_LEAD = r"(?<![\w.-])docket[ \t]+"
_END = r"(?![\w-])"
# Any token that is not a live `pod` verb: the old positional pod slot.
POD = rf"(?!(?:{LIVE_POD_VERBS}){_END})\S+"
_ANY = r"[^\s`')]+"
_ARG = rf"(?!-)({_ANY})"
# "docket runs teams" is prose; only the command forms of `runs` count.
_RUNS = r"runs(?=[ \t]+(?:show|list|cancel)\b|[ \t]*(?:[`'\")]|$))"


def _c(words: str, tail: str = "") -> re.Pattern[str]:
    return re.compile(rf"{_LEAD}{words}{_END}{tail}")


def _pod(action: str, tail: str = "") -> re.Pattern[str]:
    return re.compile(rf"{_LEAD}pod[ \t]+{POD}[ \t]+{action}{_END}{tail}")


# Ordered, most specific first. Each replacement names only live commands.
TABLE: list[tuple[re.Pattern[str], str]] = [
    # docket pod <p> <action>
    (_pod("dispatch"), "docket run"),
    (_pod("delegate"), "docket task add"),
    (_pod("queue"), "docket task list"),
    (_pod("config[ \t]+set"), "docket pod set"),
    (_pod("config[ \t]+unset"), "docket pod unset"),
    (_pod("config[ \t]+(?:explain|show|get)"), "docket pod show"),
    (_pod("config"), "docket pod show"),
    (
        _pod("set-verify", r"[ \t]+(\S+)[ \t]+(\"[^\"]*\"|'[^']*'|\S+)"),
        r"docket pod set verify \2 --member \1",
    ),
    (_pod("answer"), "docket task answer"),
    (_pod("apply"), "docket pod apply"),
    (_pod("sync"), "docket pod apply"),
    (_pod("export"), "docket pod export"),
    (_pod("remove"), "docket pod remove"),
    (_pod("add"), "docket pod add"),
    (_pod("reset"), "docket pod reset"),
    (_pod("delete"), "docket pod delete"),
    (_pod("(?:list|info|members|roster)"), "docket pod show"),
    # profile, maintain
    (_c("profile", rf"[ \t]+{_ANY}[ \t]+--resume"), "docket run --resume"),
    (_c("profile", rf"[ \t]+{_ANY}[ \t]+--budget[ \t]+({_ANY})"), r"docket pod set budgetUsd \1"),
    (_c("maintain", rf"[ \t]+{_ANY}[ \t]+check"), "docket setup --fix"),
    # pipeline, validate, config
    (_c("pipeline[ \t]+run"), "docket run --pipeline"),
    (_c("pipeline[ \t]+plan"), "docket pod plan"),
    (_c("pipeline[ \t]+validate"), "docket pod validate"),
    (_c("validate"), "docket pod validate"),
    (_c("config[ \t]+set"), "docket pod set"),
    (_c("config[ \t]+unset"), "docket pod unset"),
    (_c("config(?:[ \t]+explain)?"), "docket pod show"),
    # roles, policies, recipes, plugins
    (_c("policies[ \t]+test"), "docket pod check"),
    (_c("policies[ \t]+validate"), "docket pod validate"),
    (_c("(?:roles|policies|recipes)[ \t]+add"), "docket pod apply"),
    (_c("roles(?:[ \t]+(?:list|show))?(?![ \t]+validate)"), "docket pod roles"),
    (_c("policies(?:[ \t]+(?:list|show))?(?![ \t]+init)"), "docket pod policies"),
    (_c("recipes(?:[ \t]+(?:list|show))?"), "docket pod recipes"),
    (_c("plugins(?:[ \t]+list)?"), "docket pod policies --plugins"),
    # tasks and runs
    (_c("delegate"), "docket task add"),
    (_c("dispatch"), "docket run"),
    (_c("approve"), "docket task approve"),
    (_c("deny"), "docket task deny"),
    (_c("chat"), "docket task answer"),
    (_c("runs[ \t]+show"), "docket task show"),
    (_c("runs[ \t]+list"), "docket task list"),
    (_c("runs[ \t]+cancel"), "docket task cancel"),
    (re.compile(_LEAD + _RUNS), "docket task list"),
    (_c("trace[ \t]+tail", rf"(?:[ \t]+(?!-){_ANY})?"), "docket task trace --tail"),
    (_c("trace"), "docket task trace"),
    # status
    (_c("snapshot"), "docket status --all --json"),
    (_c("cost"), "docket status"),
    (_c("metrics"), "docket status"),
    # log
    (_c("audit[ \t]+verify"), "docket log verify"),
    (_c("audit"), "docket log"),
    # roster
    (_c("add[ \t]+--from"), "docket init --from"),
    (_c("add"), "docket pod add"),
    (_c("delete", rf"[ \t]+{_ARG}"), r"docket pod delete --pod \1"),
    (_c("delete"), "docket pod delete"),
    # setup
    (_c("doctor[ \t]+--fix"), "docket setup --fix"),
    (_c("doctor"), "docket setup"),
    (_c("gates"), "docket setup sandbox"),
    (_c("models[ \t]+provider"), "docket setup provider"),
    (_c("models"), "docket setup model"),
    (_c("keys[ \t]+add", rf"[ \t]+{_ARG}"), r"docket setup provider add \1 --credential"),
    (_c("keys"), "docket setup provider"),
    (_c("channels"), "docket setup notify"),
    (_c("unwire"), "docket setup notify unbind"),
    (_c("wire"), "docket setup notify bind"),
    (_c("notify"), "docket setup notify"),
    (_c("exporters"), "docket setup export"),
    (_c("mcp[ \t]+servers"), "docket setup mcp"),
    (_c("mcp[ \t]+serve"), "docket start --mcp"),
    (_c("mcp"), "docket setup mcp"),
    (_c("completions"), "docket setup shell"),
    # service and exec
    (_c("serve"), "docket start"),
    (_c("harness[ \t]+run"), "docket exec"),
    (_c("harness[ \t]+status"), "docket task show"),
]

_NAMES = "|".join(n for n in REMOVED_TOP_LEVEL if n != "runs")
REMOVED = re.compile(_LEAD + rf"(?:(?:{_NAMES}){_END}|{_RUNS})")
REMOVED_POD = re.compile(_LEAD + rf"pod[ \t]+{POD}[ \t]+(?:{OLD_POD_ACTIONS})" + _END)


def rewrite_line(line: str) -> str:
    for pattern, repl in TABLE:
        line = pattern.sub(repl, line)
    return line


def rewrite_text(text: str) -> str:
    return "".join(rewrite_line(ln) for ln in text.splitlines(keepends=True))


def _masked(line: str) -> str:
    for allowed in ALLOW:
        line = line.replace(allowed, " " * len(allowed))
    return line


def survivors(line: str) -> bool:
    line = _masked(line)
    return bool(REMOVED.search(line) or REMOVED_POD.search(line))


def unmappable(line: str) -> bool:
    return survivors(rewrite_line(line))


def _excluded(rel: str) -> bool:
    if any(part in EXCLUDED_PARTS for part in rel.split("/")):
        return True
    return any(rel == e or rel.startswith(e + "/") for e in EXCLUDED)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def iter_files(paths: Iterable[str | Path], skip: Iterable[str] = ()) -> Iterator[Path]:
    skips = tuple(skip)
    for raw in paths:
        base = Path(raw)
        if not base.is_absolute():
            base = ROOT / base
        candidates = sorted(base.rglob("*")) if base.is_dir() else [base]
        for path in candidates:
            if not path.is_file():
                continue
            rel = _rel(path)
            if _excluded(rel) or any(rel == s or rel.startswith(s + "/") for s in skips):
                continue
            yield path


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


_RECORD_HEADING = "## Changelog"


def split_record(path: Path, text: str) -> tuple[str, str]:
    """A spec's changelog is the record: (editable text, record text) for ``path``."""
    if not _rel(path).startswith("specs/"):
        return text, ""
    for n, line in enumerate(text.splitlines(keepends=True)):
        if line.rstrip("\n") == _RECORD_HEADING:
            head = "".join(text.splitlines(keepends=True)[:n])
            return head, text[len(head) :]
    return text, ""


def scan(paths: Iterable[str | Path], pred=survivors, skip: Iterable[str] = ()) -> list[str]:
    hits: list[str] = []
    for path in iter_files(paths, skip):
        text = read_text(path)
        if text is None:
            continue
        editable, _record = split_record(path, text)
        for n, line in enumerate(editable.splitlines(), 1):
            if pred(line):
                hits.append(f"{_rel(path)}:{n}: {line.strip()}")
    return hits


def check(paths: Iterable[str | Path], skip: Iterable[str] = ()) -> list[str]:
    return scan(paths, survivors, skip)


def unmappable_lines(paths: Iterable[str | Path], skip: Iterable[str] = ()) -> list[str]:
    return scan(paths, unmappable, skip)


def diffs(paths: Iterable[str | Path], skip: Iterable[str] = ()) -> Iterator[tuple[Path, str, str]]:
    for path in iter_files(paths, skip):
        old = read_text(path)
        if old is None:
            continue
        editable, record = split_record(path, old)
        new = rewrite_text(editable) + record
        if new != old:
            yield path, old, new


def _leading_words(replacement: str) -> list[str]:
    words: list[str] = []
    for word in replacement.split()[1:]:
        if word[0] in "-<\\\"'$":
            break
        words.append(word)
    return words


def self_check() -> list[str]:
    import typer.main

    from docket.cli import app

    root = typer.main.get_command(app)
    problems: list[str] = []
    for _pattern, repl in TABLE:
        node = root
        for word in _leading_words(repl):
            children = getattr(node, "commands", None)
            if children is None:
                break
            if word not in children:
                problems.append(f"{repl!r}: {word!r} is not a live command")
                break
            node = children[word]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    for flag in ("dry-run", "write", "check", "unmappable", "self-check"):
        mode.add_argument(f"--{flag}", action="store_true")
    ap.add_argument("paths", nargs="*", help="files or directories (default: the standard roots)")
    args = ap.parse_args(argv)
    paths = args.paths or list(DEFAULT_ROOTS)
    if args.self_check:
        problems = self_check()
        print("\n".join(problems))
        return 1 if problems else 0
    if args.check or args.unmappable:
        hits = check(paths) if args.check else unmappable_lines(paths)
        print("\n".join(hits))
        print(f"{len(hits)} line(s)", file=sys.stderr)
        return 1 if (hits and args.check) else 0
    changed = 0
    for path, old, new in diffs(paths):
        changed += 1
        if args.write:
            path.write_text(new, encoding="utf-8")
            print(f"rewrote {_rel(path)}")
        else:
            rel = _rel(path)
            sys.stdout.writelines(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    f"a/{rel}",
                    f"b/{rel}",
                )
            )
    print(f"{changed} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
