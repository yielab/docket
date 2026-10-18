#!/usr/bin/env python3
"""Replay bench: measure recorded agent steps under the current and the proposed token rule.

    context_replay.py DIR [--budget N] [--reserve N] [--policy NAME ...] [--json]
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

from docket import config
from docket.core import orchestrator, pipeline
from docket.core.llm import ChatMessage, ToolCall
from docket.core.session import condense_history
from docket.edges.adapters.toolbox import read_file, text_outcome

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


POLICIES: dict[str, Policy] = {
    "baseline": lambda messages: messages,
    "tool-output": tool_output_policy,
    "condense-k1": condense_policy(1),
    "condense-k2": condense_policy(2),
    "condense-k3": condense_policy(3),
    "phase44": lambda messages: condense_policy(PHASE44_KEEP)(tool_output_policy(messages)),
}

VERDICT_PATTERN = r"^\s*(APPROVE|REJECT|REQUEST-CHANGES|PASS|FAIL)\b"
_GATE = pipeline.VerdictGate(pattern=VERDICT_PATTERN, pass_values=["approve"])
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
    first = _bytes(request_messages(step, 0)) / config.CONTEXT_BYTES_PER_TOKEN
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
        estimate = overhead_tokens(step) + _bytes(messages) / config.CONTEXT_BYTES_PER_TOKEN
        if counted + estimate + reserve > budget:
            return "REFUSED-NEXT"
    return "ok"


def measure(
    steps: list[Step],
    budget: int = config.AGENT_LOOP_TOKEN_BUDGET,
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


def project(step: Step, policy: Policy) -> Projection:
    """Estimate *step* under *policy*: measured input per call, scaled by the request byte ratio."""
    overhead = overhead_tokens(step)
    sent = old = new = 0
    for index, call in enumerate(step.calls):
        measured = _payload(call, "inputTokens")
        request = request_messages(step, index)
        before, after = _bytes(request), _bytes(policy(request))
        scaled = overhead + max(0.0, measured - overhead) * (after / before if before else 1.0)
        scaled_cached = _payload(call, "cachedTokens") * (scaled / measured if measured else 1.0)
        output = _payload(call, "outputTokens")
        sent += round(scaled)
        old += round(scaled) + output
        new += round(scaled - scaled_cached) + output
    return Projection(sent, old, new)


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


def render_projection(steps: list[Step], names: list[str]) -> str:
    base = measure(steps)
    lines = []
    for name in names:
        if name not in POLICIES:
            raise SystemExit(f"unknown policy {name!r}; known: {', '.join(sorted(POLICIES))}")
        lines.append(f"policy {name} (estimate, not measured)")
        lines.append(f"{'step':<15}{'sent':>10}{'vs base':>9}{'old rule':>10}{'new rule':>10}")
        for step, row in zip(steps, base, strict=True):
            p = project(step, POLICIES[name])
            ratio = p.sent / row.sent if row.sent else 1.0
            lines.append(
                f"{step.name:<15}{p.sent:>10,}{ratio:>9.2f}{p.counted_old:>10,}{p.counted_new:>10,}"
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay recorded agent steps under a token rule.")
    ap.add_argument("directory", type=Path)
    ap.add_argument("--budget", type=int, default=config.AGENT_LOOP_TOKEN_BUDGET)
    ap.add_argument("--reserve", type=int, default=DEFAULT_RESERVE)
    ap.add_argument("--policy", action="append", default=[], metavar="NAME")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--anonymize", type=Path, metavar="OUT")
    args = ap.parse_args(argv)
    if args.anonymize:
        print("\n".join(anonymize(args.directory, args.anonymize)))
        return 0
    steps = load_steps(args.directory)
    if not steps:
        print(f"no *.session.json in {args.directory}", file=sys.stderr)
        return 2
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
