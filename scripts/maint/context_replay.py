#!/usr/bin/env python3
"""Replay bench: measure recorded agent steps under the current and the proposed token rule.

    context_replay.py DIR [--budget N] [--reserve N] [--policy NAME ...] [--json]
    context_replay.py DIR --repeats [--json]
    context_replay.py DIR --anonymize OUT

DIR holds ``<step>.session.json`` (the durable messages) beside ``<step>.llm_calls.jsonl`` (the
trace ``llm_call`` events of that step, one per model call; per-call usage is only there).
Counted tokens are measured. A ``--policy`` re-projection is an estimate: bytes of the rebuilt
request, scaled per call by the measured input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.agent.loop_request import _FINALIZATION_INSTRUCTION
from docket.agent.ports import ChatMessage, Endpoint, ToolCall, estimate_tokens
from docket.agent.session import condense_history
from docket.agent.tools.builtins.toolbox import read_file, text_outcome
from docket.agent.tools.registry import ToolContext
from docket.bootstrap import bind_adapters
from docket.hops.application.builtin_tools import builtin_registry, describe_tools
from docket.hops.application.compose import _task_section as task_section_of
from docket.hops.application.handoff_tool import parse_values, register_closing_tool
from docket.hops.application.verify_tool import VerifyPlan, verify_tool
from docket.kernel.brief import TaskBrief
from docket.kernel.handoff import HandoffArtifact
from docket.kernel.home import current_home
from docket.kernel.text import normalize_output
from docket.kernel.tool_outcome import VERDICT_TAIL, bounded_text
from docket.models.adapters.openai_wire import build_payload, request_part_bytes
from docket.pipeline.domain import gates
from docket.pipeline.domain import plan as orchestrator
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams.role_composer import registry_for_role
from docket.teams.workspace.repo_map import WORKING_DIRECTORY_LINE, capped_map

Messages = list[dict[str, Any]]
Policy = Callable[[Messages], Messages]


def _relative_listing(content: str, *, sort: bool) -> str:
    """A recorded glob/grep result with the shared absolute prefix stripped, as the tool prints it."""
    lines = content.splitlines()
    paths = [line for line in lines if line.startswith("/")]
    if len(paths) < 2:
        return content
    prefix = os.path.commonpath([line.split(":", 1)[0] for line in paths]).rstrip("/") + "/"
    rebuilt = [line[len(prefix) :] if line.startswith(prefix) else line for line in lines]
    return "\n".join(sorted(rebuilt) if sort else rebuilt)


def _read_window(content: str) -> str:
    """A recorded whole-file read re-rendered by the real ``read`` tool's default window."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "f").write_text(content, encoding="utf-8")
        return read_file((Path(tmp),), "f").content


def tool_output_policy(messages: Messages) -> Messages:
    """ADR 0028 point 3 over recorded results: relative sorted listings, read window, one cap."""
    out = []
    for message in messages:
        if message.get("role") != "tool":
            out.append(message)
            continue
        content = str(message.get("content") or "")
        name = message.get("name")
        if name in ("glob", "grep"):
            content = _relative_listing(content, sort=name == "glob")
        elif name == "read":
            content = _read_window(content)
        out.append({**message, "content": text_outcome(content).content})
    return out


PHASE44_KEEP = 2


def condense_policy(keep: int) -> Policy:
    """ADR 0028 point 4: the real ``condense_history`` over recorded messages, last *keep* whole."""

    def policy(messages: Messages) -> Messages:
        chat = [
            ChatMessage(
                m["role"],
                str(m.get("content") or ""),
                [ToolCall(c["id"], c["name"], c["arguments"]) for c in m.get("toolCalls") or []],
                m.get("toolCallId", ""),
                m.get("name", ""),
            )
            for m in messages
        ]
        return [
            {
                **m,
                "content": c.content,
                "toolCalls": [
                    {"id": t.id, "name": t.name, "arguments": t.arguments} for t in c.tool_calls
                ],
            }
            for m, c in zip(messages, condense_history(chat, keep), strict=True)
        ]

    return policy


def p52_2_policy(messages: Messages) -> Messages:
    """``phase44`` plus normalized ``bash`` output kept head and tail at the cap, and
    the monotone small-result rule of ``condense_history``. The artifact line is not counted."""
    out = []
    for message in tool_output_policy(messages):
        if message.get("role") == "tool" and message.get("name") == "bash":
            normalized = normalize_output(str(message.get("content") or ""))
            out.append({**message, "content": bounded_text(normalized, VERDICT_TAIL)})
        else:
            out.append(message)
    return condense_policy(PHASE44_KEEP)(out)


POLICIES: dict[str, Policy] = {
    "baseline": lambda messages: messages,
    "tool-output": tool_output_policy,
    "condense-k1": condense_policy(1),
    "condense-k2": condense_policy(2),
    "condense-k3": condense_policy(3),
    "phase44": lambda messages: condense_policy(PHASE44_KEEP)(tool_output_policy(messages)),
    "p52-2": p52_2_policy,
}

VERDICT_PATTERN = r"^\s*(APPROVE|REJECT|REQUEST-CHANGES|PASS|FAIL)\b"
_GATE = gates.VerdictGate(pattern=VERDICT_PATTERN, pass_values=["approve"])
_WORD = re.compile(r"[^\W_]+")
_VERDICT_LINE = re.compile(VERDICT_PATTERN + r"(.*)$", re.IGNORECASE | re.DOTALL)
DEFAULT_RESERVE = 4096


@dataclass
class Step:
    name: str
    session: dict[str, Any]
    calls: list[dict[str, Any]]

    @property
    def role(self) -> str:
        return str(self.calls[0].get("agent_role", "")) if self.calls else ""

    @property
    def messages(self) -> Messages:
        return list(self.session.get("messages", []))


@dataclass
class Row:
    name: str
    role: str
    calls: int
    sent: int
    cached: int
    output: int
    largest: int
    counted_old: int
    counted_new: int
    status_old: str
    status_new: str
    final: str
    verdict: str | None


@dataclass
class Projection:
    sent: int
    counted_old: int
    counted_new: int
    stable: int = 0
    transitions: int = 0
    counted_prefix: int = 0


def load_steps(directory: Path) -> list[Step]:
    steps = []
    for path in sorted(directory.glob("*.session.json")):
        name = path.name.removesuffix(".session.json")
        calls_path = directory / f"{name}.llm_calls.jsonl"
        lines = calls_path.read_text().splitlines() if calls_path.is_file() else []
        calls = [json.loads(line) for line in lines if line.strip()]
        calls.sort(key=lambda c: int(c.get("payload", {}).get("iteration", 0)))
        steps.append(Step(name, json.loads(path.read_text()), calls))
    return steps


def _bytes(messages: Messages) -> int:
    total = 0
    for m in messages:
        total += len(str(m.get("content", "")).encode())
        for call in m.get("toolCalls") or []:
            total += len(str(call.get("name", "")).encode())
            total += len(str(call.get("arguments", "")).encode())
    return total


def _payload(call: dict[str, Any], key: str) -> int:
    return int(call.get("payload", {}).get(key, 0) or 0)


def request_messages(step: Step, index: int) -> Messages:
    """Messages sent with call *index*: everything before that call's assistant reply."""
    messages = step.messages
    seen = -1
    for position, message in enumerate(messages):
        if message.get("role") == "assistant":
            seen += 1
            if seen == index:
                return messages[:position]
    return messages


def overhead_tokens(step: Step) -> float:
    """Measured tokens of the first request that no message accounts for (system, tool schemas)."""
    if not step.calls:
        return 0.0
    first = _bytes(request_messages(step, 0)) / current_home().context_bytes_per_token
    return max(0.0, _payload(step.calls[0], "inputTokens") - first)


def _final(step: Step) -> tuple[str, str | None]:
    messages = step.messages
    last = messages[-1] if messages else {}
    if last.get("role") == "assistant" and not last.get("toolCalls"):
        return "kept", orchestrator.parse_verdict(_GATE, str(last.get("content", "")))
    if step.calls and step.calls[-1].get("payload", {}).get("finishReason") == "stop":
        return "discarded", None
    return "pending", None


def _status(counted: int, step: Step, budget: int, reserve: int) -> str:
    if counted > budget:
        return "OVER"
    messages = step.messages
    mid_turn = bool(messages) and messages[-1].get("role") == "tool"
    if mid_turn and step.calls[-1].get("payload", {}).get("finishReason") != "stop":
        estimate = overhead_tokens(step) + _bytes(messages) / current_home().context_bytes_per_token
        if counted + estimate + reserve > budget:
            return "REFUSED-NEXT"
    return "ok"


def measure(
    steps: list[Step],
    budget: int = current_home().agent_loop_token_budget,
    reserve: int = DEFAULT_RESERVE,
) -> list[Row]:
    rows = []
    for step in steps:
        sent = sum(_payload(c, "inputTokens") for c in step.calls)
        cached = sum(_payload(c, "cachedTokens") for c in step.calls)
        output = sum(_payload(c, "outputTokens") for c in step.calls)
        old, new = sent + output, sent - cached + output
        final, verdict = _final(step)
        rows.append(
            Row(
                name=step.name,
                role=step.role,
                calls=len(step.calls),
                sent=sent,
                cached=cached,
                output=output,
                largest=max((_payload(c, "inputTokens") for c in step.calls), default=0),
                counted_old=old,
                counted_new=new,
                status_old=_status(old, step, budget, reserve),
                status_new=_status(new, step, budget, reserve),
                final=final,
                verdict=verdict,
            )
        )
    return rows


def _common_prefix_bytes(a: Messages, b: Messages) -> int:
    total = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        total += _bytes([x])
    return total


def project(step: Step, policy: Policy) -> Projection:
    """Estimate *step* under *policy* from measured input scaled by the request byte ratio.

    ``stable`` counts calls whose request starts with the previous one, byte for byte."""
    overhead = overhead_tokens(step)
    sent = old = new = stable = prefix = 0
    previous: Messages | None = None
    for index, call in enumerate(step.calls):
        measured = _payload(call, "inputTokens")
        request = request_messages(step, index)
        projected = policy(request)
        before, after = _bytes(request), _bytes(projected)
        scaled = overhead + max(0.0, measured - overhead) * (after / before if before else 1.0)
        scaled_cached = _payload(call, "cachedTokens") * (scaled / measured if measured else 1.0)
        output = _payload(call, "outputTokens")
        sent += round(scaled)
        old += round(scaled) + output
        new += round(scaled - scaled_cached) + output
        shared = 0.0
        if previous is not None:
            if projected[: len(previous)] == previous:
                stable += 1
            shared = overhead + _common_prefix_bytes(previous, projected) / (
                current_home().context_bytes_per_token
            )
        prefix += round(scaled - min(scaled, shared)) + output
        previous = projected
    return Projection(sent, old, new, stable, max(0, len(step.calls) - 1), prefix)


def render_table(rows: list[Row], budget: int) -> str:
    head = (
        f"{'step':<15}{'calls':>6}{'sent':>10}{'cached':>10}{'largest':>9}"
        f"{'old rule':>10}{'new rule':>10}  {'old':<14}{'new':<14}{'reply':<10}verdict"
    )
    lines = [f"token budget {budget:,} (counted tokens are measured)", head]
    for r in rows:
        lines.append(
            f"{r.name:<15}{r.calls:>6}{r.sent:>10,}{r.cached:>10,}{r.largest:>9,}"
            f"{r.counted_old:>10,}{r.counted_new:>10,}  {r.status_old:<14}{r.status_new:<14}"
            f"{r.final:<10}{r.verdict or '-'}"
        )
    totals = (
        sum(r.calls for r in rows),
        sum(r.sent for r in rows),
        sum(r.cached for r in rows),
        max((r.largest for r in rows), default=0),
        sum(r.counted_old for r in rows),
        sum(r.counted_new for r in rows),
    )
    lines.append(
        f"{'total':<15}{totals[0]:>6}{totals[1]:>10,}{totals[2]:>10,}{totals[3]:>9,}"
        f"{totals[4]:>10,}{totals[5]:>10,}"
    )
    return "\n".join(lines)


FINALIZATION_POLICY = "p52-3"


def finalization_prefix(step: Step) -> tuple[int, int, int, int]:
    """Bytes of a step's last request, of the finalization request after it, and the bytes the two
    share when the instruction rewrites the system message (before) or trails as a user message
    (after). The system message itself is not recorded, so a stand-in marks its slot."""
    previous = request_messages(step, max(0, len(step.calls) - 1))
    instruction = {"role": "user", "content": _FINALIZATION_INSTRUCTION}
    system = {"role": "system", "content": "SYSTEM"}
    rewritten = {"role": "system", "content": f"SYSTEM\n\n{_FINALIZATION_INSTRUCTION}"}
    trailing = [*step.messages, instruction]
    before = _common_prefix_bytes([system, *previous], [rewritten, *step.messages])
    after = _common_prefix_bytes([system, *previous], [system, *trailing]) - _bytes([system])
    return _bytes(previous), _bytes(trailing), before, after


def render_finalization(steps: list[Step]) -> list[str]:
    lines = [
        f"policy {FINALIZATION_POLICY} (modelled finalization request, not measured)",
        f"{'step':<15}{'last request':>14}{'finalization':>14}{'shared before':>15}{'shared after':>14}",
    ]
    for step in steps:
        last, final, before, after = finalization_prefix(step)
        lines.append(f"{step.name:<15}{last:>14,}{final:>14,}{before:>15,}{after:>14,}")
    return lines


TOOL_SURFACE_POLICY = "p53-6"
_SURFACE_VERDICT = '{"values": ["APPROVE", "REQUEST-CHANGES"], "caseSensitive": false}'


def hop_tool_bytes(role: str, surface: str, descriptions: str) -> tuple[list[str], int]:
    """The tool names and wire bytes a *role* hop is offered under a profile's *surface* and
    *descriptions*, built the way the driver builds a gated, verified hop in a jail."""
    registry = builtin_registry()
    describe_tools(registry, ToolContext(agent_id="bench", role=role, sandbox="auto"), descriptions)
    registry.register(verify_tool(VerifyPlan("true", ".", 30), ""))
    register_closing_tool(registry, parse_values(_SURFACE_VERDICT), None)
    narrowed = registry_for_role(registry, role, surface=surface)
    payload = build_payload(Endpoint("http://bench", "bench"), [], narrowed.specs())
    return sorted(narrowed.names()), request_part_bytes(payload)["tools"]


def render_tool_surface() -> list[str]:
    lines = [
        f"policy {TOOL_SURFACE_POLICY} (tool schemas a hop is offered, measured on the real registry)",
        f"{'role':<13}{'profile':<9}{'tools':>6}{'bytes':>8}  names",
    ]
    for role in ("lead", "implementer", "reviewer", "tester"):
        for profile, surface, descriptions in (
            ("hosted", "full", "full"),
            ("local", "minimal", "compact"),
        ):
            names, size = hop_tool_bytes(role, surface, descriptions)
            lines.append(f"{role:<13}{profile:<9}{len(names):>6}{size:>8,}  {' '.join(names)}")
    return lines


HOP_MESSAGE_POLICY = "p53-4"
_NAMED_PATH = "src/docket/hops/application/compose.py"


def _repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def hop_task_block(description: str, brief_text: str | None, root: str) -> tuple[str, str]:
    """The task block of a non-Lead hop message built two ways over the repository at *root*:
    the whole-tree map with the worktree's absolute path as it was, and the two sections as they
    are (``## Task`` with the map bounded by *brief_text*, then the working-directory line)."""
    old = f"Task: {description}\n\nWorking directory: {root}\n{capped_map(root)}"
    prior = []
    if brief_text is not None:
        brief = TaskBrief(objective=description[:80], context=[brief_text])
        prior = [
            HopResult(
                role="lead",
                ok=True,
                output="plan",
                artifact=HandoffArtifact(summary="plan", brief=brief),
            )
        ]
    task_section = task_section_of(TaskRecord(description=description), description, root, prior)
    return old, f"{task_section}\n\n## Hop\n{WORKING_DIRECTORY_LINE}"


def render_hop_message(steps: list[Step]) -> list[str]:
    """Bytes and counted tokens (``estimate_tokens``) of the task block before and after the two
    sections, per recorded step's first message as the task, over this repository's tracked files;
    the recorded text names no real path, so the last two rows name one file and no brief."""
    root = _repo_root()
    lines = [
        f"policy {HOP_MESSAGE_POLICY} (task block of a hop message over this repository, counted not measured)",
        f"{'task':<15}{'before B':>10}{'after B':>10}{'before tok':>12}{'after tok':>11}",
    ]
    cases: list[tuple[str, str, str | None]] = [
        (step.name, str(step.messages[0].get("content", "")), "") for step in steps
    ]
    cases.append(("names a file", "change the Reviewer prompt", f"edit {_NAMED_PATH}"))
    cases.append(("no brief yet", "change the Reviewer prompt", None))
    for name, description, brief_text in cases:
        old, new = hop_task_block(description, brief_text, root)
        lines.append(
            f"{name:<15}{len(old.encode()):>10,}{len(new.encode()):>10,}"
            f"{estimate_tokens(old):>12,}{estimate_tokens(new):>11,}"
        )
    return lines


def render_projection(steps: list[Step], names: list[str]) -> str:
    base = measure(steps)
    lines = []
    for name in names:
        if name == FINALIZATION_POLICY:
            lines.extend(render_finalization(steps))
            continue
        if name == TOOL_SURFACE_POLICY:
            lines.extend(render_tool_surface())
            continue
        if name == HOP_MESSAGE_POLICY:
            lines.extend(render_hop_message(steps))
            continue
        if name not in POLICIES:
            raise SystemExit(f"unknown policy {name!r}; known: {', '.join(sorted(POLICIES))}")
        lines.append(f"policy {name} (estimate, not measured)")
        lines.append(
            f"{'step':<15}{'sent':>10}{'vs base':>9}{'old rule':>10}{'new rule':>10}"
            f"{'prefix rule':>13}{'stable':>9}"
        )
        for step, row in zip(steps, base, strict=True):
            p = project(step, POLICIES[name])
            ratio = p.sent / row.sent if row.sent else 1.0
            lines.append(
                f"{step.name:<15}{p.sent:>10,}{ratio:>9.2f}{p.counted_old:>10,}{p.counted_new:>10,}"
                f"{p.counted_prefix:>13,}{f'{p.stable}/{p.transitions}':>9}"
            )
    return "\n".join(lines)


class _Filler:
    def __init__(self, seed: str) -> None:
        self.seed = seed

    def word(self, run: str) -> str:
        need = len(run.encode())
        stream = b""
        block = 0
        while len(stream) < need:
            stream += hashlib.sha256(f"{self.seed}\0{run}\0{block}".encode()).digest()
            block += 1
        return "".join(chr(97 + b % 26) for b in stream[:need])

    def text(self, value: str, keep_verdict: bool = False) -> str:
        out = []
        for line in value.splitlines(keepends=True):
            match = _VERDICT_LINE.match(line) if keep_verdict else None
            if match:
                marker = line[: match.end(1)]
                out.append(marker + _WORD.sub(lambda m: self.word(m.group()), line[match.end(1) :]))
            else:
                out.append(_WORD.sub(lambda m: self.word(m.group()), line))
        return "".join(out)

    def value(self, node: Any) -> Any:
        if isinstance(node, str):
            return self.text(node)
        if isinstance(node, list):
            return [self.value(item) for item in node]
        if isinstance(node, dict):
            return {key: self.value(item) for key, item in node.items()}
        return node

    def arguments(self, raw: str) -> str:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return self.text(raw)
        if not isinstance(parsed, dict):
            return self.text(raw)
        return json.dumps(self.value(parsed), separators=(",", ":"), ensure_ascii=False)

    def message(self, message: dict[str, Any]) -> dict[str, Any]:
        final = message.get("role") == "assistant" and not message.get("toolCalls")
        out = dict(message)
        out["content"] = self.text(str(message.get("content", "")), keep_verdict=final)
        if "toolCallId" in message:
            out["toolCallId"] = self.text(str(message["toolCallId"]))
        if "toolCalls" in message:
            out["toolCalls"] = [
                {
                    **call,
                    "id": self.text(str(call.get("id", ""))),
                    "arguments": self.arguments(str(call.get("arguments", ""))),
                }
                for call in message["toolCalls"] or []
            ]
        return out


def _generic_names(steps: list[Step]) -> dict[str, str]:
    roles = Counter(s.role or "step" for s in steps)
    used: Counter[str] = Counter()
    names = {}
    for step in steps:
        role = step.role or "step"
        letter = chr(ord("a") + used[role])
        used[role] += 1
        names[step.name] = role if roles[role] == 1 else f"{role}-{letter}"
    return names


def _seed(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.session.json")) + sorted(directory.glob("*.jsonl")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def anonymize(directory: Path, out_dir: Path) -> list[str]:
    """Write a same-shape copy of every step in *directory*; return the generic step names."""
    steps = load_steps(directory)
    filler = _Filler(_seed(directory))
    names = _generic_names(steps)
    out_dir.mkdir(parents=True, exist_ok=True)
    for step in steps:
        session = dict(step.session)
        session["sessionKey"] = filler.text(str(session.get("sessionKey", "")))
        session["messages"] = [filler.message(m) for m in step.messages]
        target = names[step.name]
        (out_dir / f"{target}.session.json").write_text(
            json.dumps(session, indent=1, ensure_ascii=False) + "\n"
        )
        rows = []
        for call in step.calls:
            row = dict(call)
            for key in ("project", "session_id", "task_id"):
                if key in row:
                    row[key] = filler.text(str(row[key]))
            rows.append(json.dumps(row, ensure_ascii=False))
        (out_dir / f"{target}.llm_calls.jsonl").write_text("\n".join(rows) + "\n")
    return sorted(names.values())


REPEAT_TOOLS = ("read", "grep", "glob")


@dataclass
class _Call:
    tool: str
    path: str  # worktree-relative when the path runs through the task's own directory
    rest: str  # the other arguments, canonical JSON
    size: int  # bytes of the recorded result


def _relative_path(path: str, task: str) -> str:
    """*path* below the task's worktree (the directory named by the task id), else unchanged."""
    parts = path.split("/")
    return "/".join(parts[parts.index(task) + 1 :]) if task and task in parts else path


def _same_path(a: str, b: str) -> bool:
    """One file: equal paths, or a worktree-relative path that ends another, absolute one."""
    if a == b:
        return True
    return any(
        rel and not rel.startswith("/") and other.startswith("/") and other.endswith("/" + rel)
        for rel, other in ((a, b), (b, a))
    )


def _tool_calls(step: Step) -> list[_Call]:
    task = str(step.calls[0].get("task_id", "")) if step.calls else ""
    sizes = {
        m.get("toolCallId"): len(str(m.get("content", "")).encode())
        for m in step.messages
        if m.get("role") == "tool"
    }
    calls = []
    for message in step.messages:
        for call in message.get("toolCalls") or []:
            if call.get("name") not in REPEAT_TOOLS:
                continue
            try:
                args = json.loads(call.get("arguments") or "{}")
            except ValueError:
                continue
            if not isinstance(args, dict):
                continue
            path = _relative_path(str(args.pop("path", "")), task)
            rest = json.dumps(args, sort_keys=True, separators=(",", ":"))
            calls.append(_Call(call["name"], path, rest, sizes.get(call.get("id"), 0)))
    return calls


def _step_repeats(step: Step) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    calls = _tool_calls(step)
    for call in calls:
        for group in groups:
            first: _Call = group["first"]
            if (call.tool, call.rest) == (first.tool, first.rest) and _same_path(
                call.path, first.path
            ):
                group["count"] += 1
                group["bytes"] += call.size
                break
        else:
            groups.append({"first": call, "count": 1, "bytes": 0})
    repeated = [g for g in groups if g["count"] > 1]
    total = sum(g["bytes"] for g in repeated)
    return {
        "step": step.name,
        "role": step.role,
        "calls": len(calls),
        "repeats": [
            {
                "tool": g["first"].tool,
                "arguments": json.dumps(
                    {"path": g["first"].path, **json.loads(g["first"].rest)}, sort_keys=True
                ),
                "count": g["count"],
                "bytes": g["bytes"],
            }
            for g in repeated
        ],
        "repeatedCalls": sum(g["count"] - 1 for g in repeated),
        "rereadFiles": len({g["first"].path for g in repeated if g["first"].tool == "read"}),
        "bytes": total,
        "estTokens": total // current_home().context_bytes_per_token,
    }


def _reads(steps: list[Step], role: str) -> list[_Call]:
    return [c for s in steps if s.role == role for c in _tool_calls(s) if c.tool == "read"]


def _edited(steps: list[Step], role: str) -> list[str]:
    """Paths the *role*'s `edit` and `write` calls named, below the task's worktree."""
    paths = []
    for step in steps:
        if step.role != role:
            continue
        task = str(step.calls[0].get("task_id", "")) if step.calls else ""
        for message in step.messages:
            for call in message.get("toolCalls") or []:
                if call.get("name") not in ("edit", "write"):
                    continue
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except ValueError:
                    continue
                if isinstance(args, dict) and args.get("path"):
                    paths.append(_relative_path(str(args["path"]), task))
    return paths


def _task_overlaps(steps: list[Step]) -> list[dict[str, Any]]:
    by_task: dict[str, list[Step]] = {}
    for step in steps:
        by_task.setdefault(str(step.calls[0].get("task_id", "")) if step.calls else "", []).append(
            step
        )
    tasks = []
    for task, members in sorted(by_task.items()):
        lead = _reads(members, "lead")
        mine = _reads(members, "implementer")
        shared = [c for c in mine if any(_same_path(c.path, r.path) for r in lead)]
        # A shared file the Implementer then edits had to be read for the edit's exact text;
        # the rest is the reading a Lead's locators could have spared it.
        edited = _edited(members, "implementer")
        avoidable = [c for c in shared if not any(_same_path(c.path, e) for e in edited)]
        tasks.append(
            {
                "task": task,
                "leadReads": len(lead),
                "implementerReads": len(mine),
                "overlap": sorted({c.path for c in shared}),
                "bytes": sum(c.size for c in shared),
                "avoidable": sorted({c.path for c in avoidable}),
                "avoidableBytes": sum(c.size for c in avoidable),
            }
        )
    return tasks


def repeats_report(steps: list[Step]) -> dict[str, Any]:
    """Per step the read/grep/glob calls whose canonical arguments repeat, and per task the files
    the Implementer read that the Lead had read. Bytes are the recorded results of the repeats;
    tokens divide them by ``Home.context_bytes_per_token`` (an estimate)."""
    return {
        "bytesPerToken": current_home().context_bytes_per_token,
        "steps": [_step_repeats(s) for s in steps],
        "tasks": _task_overlaps(steps),
    }


def render_repeats(report: dict[str, Any]) -> str:
    lines = [
        f"repeated read/grep/glob calls per step (estimated tokens at "
        f"{report['bytesPerToken']} bytes per token)",
        f"{'step':<15}{'role':<13}{'calls':>6}{'repeated':>9}{'re-read files':>14}"
        f"{'bytes':>9}{'est tokens':>11}",
    ]
    for s in report["steps"]:
        lines.append(
            f"{s['step']:<15}{s['role']:<13}{s['calls']:>6}{s['repeatedCalls']:>9}"
            f"{s['rereadFiles']:>14}{s['bytes']:>9,}{s['estTokens']:>11,}"
        )
        lines += [f"  {r['count']}x {r['tool']} {r['arguments'][:100]}" for r in s["repeats"]]
    lines += ["", "files the implementer read that the lead had read, per task"]
    for task in report["tasks"]:
        lines.append(
            f"  {task['task'] or '(no task id)'}: lead read {task['leadReads']}, implementer read "
            f"{task['implementerReads']}, shared {len(task['overlap'])} ({task['bytes']:,} bytes), "
            f"not edited after {len(task['avoidable'])} ({task['avoidableBytes']:,} bytes)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay recorded agent steps under a token rule.")
    ap.add_argument("directory", type=Path)
    ap.add_argument("--budget", type=int, default=current_home().agent_loop_token_budget)
    ap.add_argument("--reserve", type=int, default=DEFAULT_RESERVE)
    ap.add_argument("--policy", action="append", default=[], metavar="NAME")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repeats", action="store_true")
    ap.add_argument("--anonymize", type=Path, metavar="OUT")
    args = ap.parse_args(argv)
    bind_adapters()
    if args.anonymize:
        print("\n".join(anonymize(args.directory, args.anonymize)))
        return 0
    steps = load_steps(args.directory)
    if not steps:
        print(f"no *.session.json in {args.directory}", file=sys.stderr)
        return 2
    if args.repeats:
        report = repeats_report(steps)
        print(json.dumps(report, indent=1) if args.json else render_repeats(report))
        return 0
    rows = measure(steps, args.budget, args.reserve)
    if args.json:
        print(json.dumps([r.__dict__ for r in rows], indent=1))
    else:
        print(render_table(rows, args.budget))
    if args.policy:
        print()
        print(render_projection(steps, args.policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
