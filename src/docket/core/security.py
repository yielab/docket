"""Security-gate logic: docket's own command classifier + approval/isolation config.

``core/tools.py``'s ``dispatch_tool`` is the single chokepoint every tool
call passes through, and the ``pre_tool_call`` policy hook (plus
``classify_command`` below) is unconditionally live on it — there is no
separate "enable the gate" step, and no daemon-side exec-approval mechanism
to configure at all (there is no daemon). What remains configurable is
docket's own approval-routing and workspace-isolation state
(``core/fleet.py``'s ``FleetSecurity``, ``docket gates enable/disable``,
``docket gates isolate``) — not whether tool calls are gated, only where a
resulting prompt is routed and whether tool execution runs sandboxed.

This module also owns ``classify_command``/``match_high_risk``: the
argument-aware classifier that decides ``allow``/``ask``/``deny`` for a shell
command, used by both ``core/tools.py``'s live gate and
``edges/adapters/system.py``'s ``run_verify_cmd``.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

from docket.core import fleet as _fleet

# Curated set of common, lower-risk binaries `classify_command` allows
# unattended. Destructive/sensitive bins (rm, dd, docker, systemctl, ...) and
# shell interpreters are deliberately OMITTED so they fall through to `ask`.
# NOTE: a bin listed here (e.g. git, npm) can still have a HIGH_RISK_PATTERNS
# class attached for documentation/visibility (`docket gates classes`) — see
# `HighRiskClass`'s docstring for why that does not exclude it from this list.
SAFE_BINS: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "nl",
    "grep", "egrep", "rg", "fd", "find", "file", "stat", "tree", "realpath",
    "dirname", "basename",
    "sed", "awk", "jq", "yq", "diff", "comm",
    "git", "node", "npm", "npx", "pnpm", "yarn", "python3", "pip", "pip3",
    "go", "cargo", "rustc", "make", "cmake",
    "date", "env", "printf", "which", "xargs", "tee", "less",
    "mkdir", "touch", "cp", "mv", "ln",
)  # fmt: skip


@dataclass(frozen=True)
class HighRiskClass:
    """A named, documented high-risk action class.

    ``pattern`` is a case-insensitive regex matched against a full command
    string (e.g. ``"git push origin production"``), not just a binary name.

    ``bins`` names the SAFE_BINS members this class can be performed through,
    for documentation/visibility only (``docket gates classes``) — it does
    **not** exclude them from ``SAFE_BINS``. Excluding a bin like
    ``git``/``npm`` wholesale to force its high-risk invocations to ask would
    also force every benign invocation to ask — an unacceptable usability
    regression for tools used constantly. Per-argument enforcement of these
    classes is exactly what ``classify_command`` below provides instead: it
    reads the whole command line, so ``git push origin production`` asks
    while ``git status`` does not, without excluding ``git`` from
    ``SAFE_BINS`` at all. ``match_high_risk`` is the underlying classification
    entry point — wired into ``run_verify_cmd`` (refuse before the shell
    starts) and into dispatch's ``pre_output`` scan, in addition to
    ``classify_command``'s own live use in ``core/tools.py``'s gate.
    """

    name: str
    description: str
    pattern: str
    bins: tuple[str, ...] = ()


# Seed list of high-risk action classes: money-movement, prod-deploy, and
# secret-access. Intentionally small and named — a policy foundation, not
# exhaustive coverage. Not user-configurable yet; a config-file override is
# a natural follow-up. All three classes are fully enforced via
# `classify_command` (argument-aware).
HIGH_RISK_PATTERNS: tuple[HighRiskClass, ...] = (
    HighRiskClass(
        name="money-movement",
        description="Payment/financial operations: charges, refunds, payouts, transfers",
        pattern=(
            r"\bstripe\b|\bpaypal\b|\bbraintree\b|charge\s+customer|refund.*amount"
            r"|wire\s+transfer|bank\s+transfer|\bpayout\b"
        ),
    ),
    HighRiskClass(
        name="prod-deploy",
        description="Production deploys and release pushes",
        pattern=(
            r"git\s+push\s+.*\b(main|master|production|prod)\b|npm\s+publish"
            r"|docker\s+(push|stop)\b|terraform\s+apply|kubectl\s+(apply|delete|rollout)"
            r"|helm\s+upgrade"
        ),
        bins=("git", "npm"),
    ),
    HighRiskClass(
        name="secret-access",
        description="Secret/credential writes and key generation",
        pattern=(
            r"vault\s+(write|kv\s+put)|ssh-keygen|openssl\s+genrsa"
            r"|kubectl\s+(create|apply).*secret|aws.*secretsmanager.*put-secret"
        ),
    ),
)


def match_high_risk(command: str) -> HighRiskClass | None:
    """Return the first HIGH_RISK_PATTERNS class matching *command*, else None.

    The single classification entry point, wired onto the two paths docket
    itself controls: ``run_verify_cmd`` (which refuses a matching command
    outright, before the shell ever starts) and dispatch's ``pre_output``
    hop-output scan. ``classify_command`` below also calls this to decide
    ``ask`` for a live tool call — the check ``core/tools.py``'s
    ``dispatch_tool`` chokepoint actually enforces.

    Three sibling helpers — ``high_risk_bins``, ``is_high_risk`` and
    ``resolve_command_action`` — were removed rather than kept beside this
    one: they modelled a bare ask/allow decision at a granularity too coarse
    to be useful (binary name only, never arguments) and had accumulated
    zero production callers. ``classify_command`` is their proper
    replacement: it reads the whole command line, so ``git push origin
    production`` asks while ``git status`` does not, without needing a
    coarse always-ask resolver at all. The policy itself is also published,
    honestly, by ``docket gates classes`` and
    ``specs/functional/security-gates.spec.md``.
    """
    for cls in HIGH_RISK_PATTERNS:
        if re.search(cls.pattern, command, re.IGNORECASE):
            return cls
    return None


# ── argument-aware command classification ────────────────────────────────
#
# `core/tools.py`'s `dispatch_tool` runs every tool call itself, so this
# classifier has a real enforcement point downstream. What follows is
# deliberately NOT a restoration of the old bare-binary-name classifier
# described in `match_high_risk`'s docstring above: that granularity made
# `git push origin production` indistinguishable from `git status`. This one
# reads the whole command line, including every segment behind a `;`, `&&`
# or pipe.

# Shell operators that start a new command. Anything after one of these is a
# separate binary invocation and must be classified on its own — `ls && rm -rf
# /` is not an `ls`.
_COMMAND_SEPARATORS: frozenset[str] = frozenset({";", "&&", "||", "|", "&", "(", ")", "\n"})

# Substrings that make a command line impossible to classify statically: the
# real binary is produced at runtime. Their presence forces an approval rather
# than a guess.
_OPAQUE_MARKERS: tuple[str, ...] = ("$(", "`", "${", "eval ", "exec ")


@dataclass(frozen=True)
class CommandVerdict:
    """What docket decided about one shell command, and why.

    ``action`` is ``allow`` | ``ask`` | ``deny``. ``ask`` routes to
    ``core/approval.py``, which fails closed on timeout — so an unclassifiable
    command never silently runs.

    ``reason`` is written for a human approver reading a Telegram/CLI prompt,
    not for a log grep: it names the specific binary or risk class that caused
    the verdict.
    """

    action: str
    reason: str
    bin_name: str = ""
    risk_class: str = ""

    @property
    def blocked(self) -> bool:
        """True when the command may not run as-is (denied, or awaiting a human)."""
        return self.action != "allow"


def split_command_segments(command: str) -> list[list[str]]:
    """Split a shell command into per-invocation token lists.

    ``ls -la && git push origin main`` becomes ``[["ls", "-la"], ["git",
    "push", "origin", "main"]]``. Leading ``VAR=value`` assignments are dropped
    so the binary is always the first token of a segment.

    Raises ``ValueError`` for input shlex cannot tokenize (unbalanced quotes) —
    the caller treats that as unclassifiable, never as safe.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)  # ValueError on unbalanced quotes; deliberately not caught here

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                segments.append(current)
            current = []
            continue
        # Redirections attach to the current invocation rather than starting a
        # new one, but the target is not a binary — drop the operator and let
        # the path stay as an argument.
        if token in (">", ">>", "<", "2>", "&>"):
            continue
        current.append(token)
    if current:
        segments.append(current)

    cleaned: list[list[str]] = []
    for segment in segments:
        idx = 0
        while idx < len(segment) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", segment[idx]):
            idx += 1
        if idx < len(segment):
            cleaned.append(segment[idx:])
    return cleaned


def classify_command(command: str) -> CommandVerdict:
    """Decide whether *command* may run unattended.

    The rules, in order — first match wins:

    1. **Empty** -> deny. Nothing to run.
    2. **Opaque** (command substitution, ``eval``, ``exec``) -> ask. The binary
       that will actually run is not knowable from the text.
    3. **Untokenizable** -> ask. Same reasoning: an unparseable command is not
       a safe command.
    4. **A high-risk action class matches the full line** -> ask, naming the
       class. This is what makes the check argument-aware rather than
       binary-only: ``git`` is allowlisted, but ``git push origin
       production`` is a production deploy that must still ask.
    5. **Any segment's binary is off ``SAFE_BINS``** -> ask, naming it. Every
       segment is checked, so a safe binary cannot smuggle an unsafe one in
       behind ``;`` or ``&&``.
    6. Otherwise -> allow.

    **What this does not catch, stated plainly:** a safe binary used
    destructively within its own remit (``git reset --hard``), writes through a
    redirect to a path outside the workspace (path containment in
    ``core/tools.py`` covers the file tools, not shell redirects), and anything
    a script on the allowlist does once started. It is a gate, not a sandbox —
    sandboxed exec (``core/tools.py``'s ``ToolContext.sandbox``) is a
    separate, opt-in mechanism this classifier neither provides nor requires.
    """
    text = command.strip()
    if not text:
        return CommandVerdict("deny", "empty command")

    lowered = text.lower()
    for marker in _OPAQUE_MARKERS:
        if marker in lowered:
            return CommandVerdict(
                "ask", f"command is not statically analysable (contains {marker.strip()!r})"
            )

    try:
        segments = split_command_segments(text)
    except ValueError as ex:
        return CommandVerdict("ask", f"command could not be parsed ({ex})")
    if not segments:
        return CommandVerdict("deny", "no binary found in command")

    risk = match_high_risk(text)
    if risk is not None:
        return CommandVerdict(
            "ask",
            f"matches high-risk action class {risk.name!r}: {risk.description}",
            bin_name=os.path.basename(segments[0][0]),
            risk_class=risk.name,
        )

    for segment in segments:
        bin_name = os.path.basename(segment[0])
        if bin_name not in SAFE_BINS:
            return CommandVerdict(
                "ask", f"{bin_name!r} is not on the curated allowlist", bin_name=bin_name
            )

    return CommandVerdict(
        "allow",
        "all binaries allowlisted, no high-risk class matched",
        bin_name=os.path.basename(segments[0][0]),
    )


def apply_approval_routing() -> int:
    """Route gated-tool-call approval prompts to each agent's session channel.

    Writes fleet.json's approval-routing state to on/session. Returns the
    count of channel-bound agents (informational) -- a bound agent only
    actually receives a prompt once ``docket serve --telegram`` is running
    with a bot token configured (``core/telegram.py``), so this count is a
    readiness signal, not a guarantee a prompt will be delivered.
    """
    _fleet.set_approval_routing(enabled=True, mode="session")
    count = 0
    for aid in _fleet.all_agent_ids():
        if _fleet.get_binding(aid):
            count += 1
    return count


def disable_approval_routing() -> None:
    """Turn approval-routing off in fleet.json."""
    _fleet.disable_approval_routing()


def apply_workspace_isolation() -> None:
    """Record that per-agent Docker sandbox isolation is desired.

    The Docker capability check is the caller's responsibility. Writes
    fleet.json's isolation mode; **not yet consulted by the turn loop** —
    ``edges/adapters/docket_runtime.py``'s ``DocketDriver`` always constructs
    its ``ToolContext`` with ``sandbox="off"``, so this flag does not yet
    change what a real tool call does. Recorded honestly here so the state
    exists for a future card to wire, not silently dropped.
    """
    _fleet.set_sandbox_isolation(mode="non-main")


def disable_workspace_isolation() -> None:
    """Turn the recorded sandbox-isolation mode off (mode: off)."""
    _fleet.disable_sandbox_isolation()
