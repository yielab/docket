"""Reading a shell command line: its invocations, their output redirects, heredocs and wrappers.

The lexing layer under ``governance.security``: ``classify_command`` and ``command_segments`` both
read a command through it, so what the classifier decides about and what a ``when.command``
predicate matches are the same invocations. Pure text work, no I/O.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

# Output-writing redirects only -- `<` (input) does not let arbitrary content
# reach a file the way `>`/`>>`/`>|`/`&>`/`&>>`/`>&` do. A descriptor prefix
# (`2>`) lexes as the digit then the operator, so it needs no entry. `>&` is
# a file redirect unless its target is a descriptor number (`2>&1`), which
# `split_segments` tells apart.
_OUTPUT_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
_INPUT_REDIRECT_OPS: frozenset[str] = frozenset({"<", "<<", "<<<", "<>"})

# Shell operators that start a new command. Anything after one of these is a
# separate binary invocation and must be classified on its own — `ls && rm -rf
# /` is not an `ls`.
_COMMAND_SEPARATORS: frozenset[str] = frozenset({";", "&&", "||", "|", "&", "(", ")", "\n"})


@dataclass(frozen=True)
class Segment:
    """One binary invocation of a command line, with what its output redirects name."""

    tokens: list[str]
    redirects: int  # output redirect operators attached to this invocation
    targets: tuple[str, ...]  # the token after each one; fewer than ``redirects`` when one had none
    subshell: bool = False  # joined to a neighbour by ``|`` or ``&``, so it runs in a subshell

    @property
    def redirected(self) -> bool:
        return self.redirects > 0


def _logical_lines(command: str) -> list[str]:
    """Split *command* at every unquoted, unescaped newline, where the shell starts a new
    command (a quoted newline stays text, a backslash-newline continues the line); ``shlex``
    with ``whitespace_split`` swallows a newline as whitespace and never yields it."""
    lines: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for ch in command:
        if escaped:
            escaped = False
            if ch in "\r\n":
                current.pop()  # drop the backslash: the two lines are one command
                current.append(" ")
            else:
                current.append(ch)
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            current.append(ch)
            continue
        if quote:
            if ch == quote:
                quote = ""
            current.append(ch)
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            continue
        if ch in "\r\n":
            lines.append("".join(current))
            current = []
            continue
        current.append(ch)
    lines.append("".join(current))
    return [line for line in lines if line.strip()]


_HEREDOC_OP = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|(\\?)([A-Za-z0-9_.-]+))")
_SHELL_BINS: frozenset[str] = frozenset(
    {"bash", "sh", "zsh", "dash", "ksh", "ash", "fish", "csh", "tcsh", "source", "."}
)


def _heredocs_on(line: str) -> list[tuple[str, bool, bool]]:
    """The ``(word, quoted, strip_tabs)`` of every ``<<`` heredoc opened on *line*; a ``<<``
    inside quotes, or the ``<<<`` here-string, is not one."""
    found: list[tuple[str, bool, bool]] = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif line.startswith("<<<", i):
            i += 3
            continue
        elif line.startswith("<<", i):
            m = _HEREDOC_OP.match(line, i)
            if m:
                word = m.group(2) if m.group(2) is not None else m.group(3)
                quoted = word is not None or bool(m.group(4))
                found.append((word if word is not None else m.group(5), quoted, bool(m.group(1))))
                i = m.end()
                continue
        i += 1
    return found


def _line_runs_a_shell(line: str) -> bool:
    """True when any segment of *line* runs a shell (or cannot be read), so a heredoc body on
    it may be commands."""
    try:
        for segment in split_segments(line):
            effective = unwrap(segment.tokens)
            if effective is None or os.path.basename(effective[0]) in _SHELL_BINS:
                return True
    except ValueError:
        return True
    return False


def cut_quoted_heredocs(text: str) -> tuple[str, str | None]:
    """Remove the body and closing line of every quoted-delimiter heredoc not fed to a shell.
    The second item is a refusal reason when a quoted heredoc never closes."""
    lines = text.split("\n")
    out: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        out.append(line)
        idx += 1
        pending = _heredocs_on(line)
        if not pending:
            continue
        keep = _line_runs_a_shell(line)
        for word, quoted, strip in pending:
            body_start = idx
            while idx < len(lines):
                candidate = lines[idx].rstrip("\r")
                if (candidate.lstrip("\t") if strip else candidate) == word:
                    break
                idx += 1
            closed = idx < len(lines)
            if quoted and not keep:
                if not closed:
                    return text, f"heredoc {word!r} has no closing delimiter"
            else:
                out.extend(lines[body_start : idx + 1 if closed else idx])
            idx += 1 if closed else 0
    return "\n".join(out), None


def _tokens(command: str) -> list[str]:
    """The shell tokens of *command*, each logical line closed by a ``"\\n"`` token. Raises
    ``ValueError`` on unbalanced quotes; deliberately not caught here."""
    tokens: list[str] = []
    for line in _logical_lines(command):
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens.extend(lexer)
        tokens.append("\n")  # a line boundary is a command separator
    return tokens


def starts_background(command: str) -> bool:
    """Whether *command* holds the lone control operator ``&``, which starts a child the call does
    not wait for, wherever it stands. ``&&``, ``&>``, ``>&`` and a quoted ``&`` are other tokens; a closing ``)`` or ``;`` may be fused to it.
    Raises ``ValueError`` like ``split_segments``."""
    return any(t.count("&") == 1 and set(t) <= set("&();") for t in _tokens(command))


def split_segments(command: str) -> list[Segment]:
    """Split a shell command into per-invocation token lists, plus the output redirects attached
    to each -- kept internal, used only by ``classify_command``."""
    tokens = _tokens(command)

    segments: list[Segment] = []
    current: list[str] = []
    redirects = 0
    targets: list[str] = []
    expecting_target = duplicating = False
    prev_sep = ""
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                sub = prev_sep in ("|", "&") or token in ("|", "&")
                segments.append(Segment(current, redirects, tuple(targets), sub))
            current, redirects, targets, expecting_target = [], 0, [], False
            prev_sep = token
            continue
        # Redirections attach to the current invocation rather than starting a
        # new one, but the target is not a binary -- drop the operator and let
        # the path stay as an argument, recording it as the redirect's target.
        if token in _OUTPUT_REDIRECT_OPS or token in _INPUT_REDIRECT_OPS:
            expecting_target = token in _OUTPUT_REDIRECT_OPS
            duplicating = token == ">&"
            if expecting_target:
                redirects += 1
            continue
        if expecting_target:
            expecting_target = False
            if duplicating and (token.isdigit() or token == "-"):
                redirects -= 1  # `2>&1` copies a descriptor; no file is opened
            else:
                targets.append(token)
        current.append(token)
    if current:
        segments.append(Segment(current, redirects, tuple(targets), prev_sep in ("|", "&")))

    cleaned: list[Segment] = []
    for segment in segments:
        idx = 0
        while idx < len(segment.tokens) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", segment.tokens[idx]
        ):
            idx += 1
        if idx < len(segment.tokens):
            cleaned.append(
                Segment(segment.tokens[idx:], segment.redirects, segment.targets, segment.subshell)
            )
    return cleaned


# Command wrappers: the wrapper is allowlisted, the command it runs is what gets classified.
# `setsid` is not one: a new session leaves the process group that cancellation kills.
# Value is the set of options that consume the next token when written without `=`/attached value.
_WRAPPER_ARG_OPTS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "xargs": frozenset(
        {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a", "-e", "-l", "--max-args", "--max-procs",
         "--delimiter", "--arg-file", "--max-lines", "--max-chars", "--eof", "--replace"}
    ),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "time": frozenset(),
    "command": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
}  # fmt: skip
_MAX_WRAPPER_DEPTH = 8
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _wrapped_command(bin_name: str, tokens: list[str]) -> list[str] | None:
    """The command *tokens* (after the wrapper's own arguments) hand to the shell, ``[]`` when the
    wrapper runs nothing (or only echoes), ``None`` when its options cannot be read safely."""
    takes_arg = _WRAPPER_ARG_OPTS[bin_name]
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok == "--":
            idx += 1
            break
        if bin_name == "env" and _ENV_ASSIGN_RE.fullmatch(tok):
            idx += 1
            continue
        if not tok.startswith("-") or tok == "-":
            break
        if bin_name == "time" and tok not in ("-p", "--portability"):
            return None
        if bin_name == "command" and tok in ("-v", "-V"):
            return []
        if tok in takes_arg:
            idx += 2
            continue
        if bin_name == "env" and (tok.startswith("-S") or tok.startswith("--split-string")):
            return None
        idx += 1
    rest = tokens[idx:]
    if bin_name == "timeout" and rest:
        rest = rest[1:]  # the DURATION operand
    return rest


def unwrap(tokens: list[str]) -> list[str] | None:
    """Peel command wrappers off *tokens* and return the command that really runs (the last
    wrapper's own tokens when it runs nothing); ``None`` when too deep or unreadable."""
    for _ in range(_MAX_WRAPPER_DEPTH):
        bin_name = os.path.basename(tokens[0])
        if bin_name not in _WRAPPER_ARG_OPTS:
            return tokens
        inner = _wrapped_command(bin_name, tokens[1:])
        if inner is None:
            return None
        if not inner:
            return tokens
        tokens = inner
    return None
