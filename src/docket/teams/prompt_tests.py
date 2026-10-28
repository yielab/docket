"""A prompt's ``tests`` file: its cases and assertions, the run against one model, and the record
of the result per model and prompt hash.

The file format is specs/functional/config-format.spec.md, "The ``prompt`` kind" requirement 8;
the record and the floor that reads it are specs/functional/model-profiles.spec.md, "Prompt
variants and the floor". ``run_cases`` sends each case as one exchange through whatever
``ChatBackend`` it is given, so the caller decides which model answers. The record is written only
by ``platform/store.py``, under ``Home.prompt_tests_file``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from docket.agent.ports import ChatBackend, ToolSpec, estimate_tokens, system, user
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.platform import read_json, read_modify_write

ASSERTIONS = ("contains", "matchesSchema", "calledHandoff", "underTokens")
HANDOFF_TOOL = "handoff"
PASS = "pass"
FAIL = "fail"

_HANDOFF_SPEC = ToolSpec(
    name=HANDOFF_TOOL,
    description="Hand your work to the next hop and finish. Call this once, as your last action.",
    parameters={"type": "object", "properties": {}},
)
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "null": (type(None),),
}


class PromptTestsError(InvalidInput):
    """The tests file is not valid, or a run could not be made."""


@dataclass(frozen=True)
class Assertion:
    kind: str
    value: Any


@dataclass(frozen=True)
class PromptCase:
    name: str
    input: str
    assertions: tuple[Assertion, ...]


@dataclass(frozen=True)
class PromptTestResult:
    """``result`` is ``pass`` only when every assertion of every case held; ``failed`` names the
    cases that did not pass."""

    result: str
    cases: int
    failed: tuple[str, ...]
    lines: tuple[str, ...] = ()


def _refuse(path: Path, where: str, message: str) -> PromptTestsError:
    return PromptTestsError(f"{path}: {where}: {message}")


def _assertion(path: Path, where: str, raw: Any) -> Assertion:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise _refuse(path, where, "an assertion is a mapping with one key")
    ((kind, value),) = raw.items()
    if kind not in ASSERTIONS:
        raise _refuse(path, where, f"unknown assertion {kind!r}; valid: {', '.join(ASSERTIONS)}")
    ok = {
        "contains": isinstance(value, str) and bool(value),
        "matchesSchema": isinstance(value, dict),
        "calledHandoff": isinstance(value, bool),
        "underTokens": isinstance(value, int) and not isinstance(value, bool) and value > 0,
    }[kind]
    if not ok:
        raise _refuse(path, where, f"{kind} has a value of the wrong type")
    return Assertion(kind, value)


def load_cases(path: str | Path) -> list[PromptCase]:
    """The cases of the tests file *path*; ``PromptTestsError`` names the file and the case."""
    file = Path(path)
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptTestsError(f"{file}: cannot read tests: {exc}") from exc
    cases = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(cases, list) or not cases:
        raise _refuse(file, "cases", "a non-empty list is required")
    result: list[PromptCase] = []
    for index, case in enumerate(cases, start=1):
        where = f"case {index}"
        if not isinstance(case, dict) or not isinstance(case.get("input"), str):
            raise _refuse(file, where, "a case has an `input` string")
        where = f"case {case.get('name') or index}"
        asserts = case.get("assert")
        if not isinstance(asserts, list) or not asserts:
            raise _refuse(file, where, "`assert` is a non-empty list")
        result.append(
            PromptCase(
                str(case.get("name") or f"case {index}"),
                case["input"],
                tuple(_assertion(file, where, a) for a in asserts),
            )
        )
    return result


def _schema_problem(value: Any, schema: Mapping[str, Any], at: str = "$") -> str | None:
    """Why *value* does not satisfy *schema* (``type``, ``properties``, ``required``, ``items``,
    ``enum``), or ``None``."""
    kind = schema.get("type")
    if kind is not None:
        types = _JSON_TYPES.get(str(kind), ())
        wrong_bool = isinstance(value, bool) and kind in ("number", "integer")
        if not isinstance(value, types) or wrong_bool:
            return f"{at} is not of type {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{at} is not one of {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{at}.{key} is required"
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                problem = _schema_problem(value[key], sub, f"{at}.{key}")
                if problem:
                    return problem
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problem = _schema_problem(item, schema["items"], f"{at}[{index}]")
            if problem:
                return problem
    return None


def _check(assertion: Assertion, text: str, called: list[str], tokens: int) -> str | None:
    """The failure message of *assertion* against one reply, or ``None`` when it holds."""
    if assertion.kind == "contains":
        return None if assertion.value in text else f"reply lacks {assertion.value!r}"
    if assertion.kind == "calledHandoff":
        did = HANDOFF_TOOL in called
        return (
            None
            if did == assertion.value
            else f"calledHandoff is {did}, expected {assertion.value}"
        )
    if assertion.kind == "underTokens":
        return (
            None if tokens < assertion.value else f"{tokens} output tokens, limit {assertion.value}"
        )
    try:
        document = json.loads(text)
    except ValueError:
        return "reply is not a JSON document"
    return _schema_problem(document, assertion.value)


def run_cases(
    text: str, cases: list[PromptCase], backend: ChatBackend, *, handoff: bool = False
) -> PromptTestResult:
    """Send each case as one exchange (*text* as the system message, the case's input as the user
    message; a ``handoff`` tool is offered when *handoff*) and check its assertions."""
    failed: list[str] = []
    lines: list[str] = []
    for case in cases:
        response = backend.complete(
            [system(text), user(case.input)], tools=[_HANDOFF_SPEC] if handoff else ()
        )
        if not response.ok:
            problems = [f"model call failed: {response.error or response.failure_kind}"]
        else:
            reply = response.message.content
            tokens = response.usage.output_tokens or estimate_tokens(reply)
            called = [call.name for call in response.tool_calls]
            problems = [
                p for a in case.assertions if (p := _check(a, reply, called, tokens)) is not None
            ]
        if problems:
            failed.append(case.name)
        lines.append(
            f"{FAIL if problems else PASS}  {case.name}" + "".join(f"\n      {p}" for p in problems)
        )
    return PromptTestResult(FAIL if failed else PASS, len(cases), tuple(failed), tuple(lines))


def recorded(model: str, sha256: str) -> dict[str, Any] | None:
    """The record of *model* on the prompt hash *sha256*, or ``None`` when it was never run."""
    results = read_json(current_home().prompt_tests_file).get("results", {})
    found = results.get(model, {}).get(sha256) if isinstance(results, dict) else None
    return found if isinstance(found, dict) else None


def record(model: str, sha256: str, prompt: str, outcome: PromptTestResult) -> dict[str, Any]:
    """Store *outcome* for *model* and *sha256*, replacing an earlier record, and return it."""
    entry = {
        "prompt": prompt,
        "result": outcome.result,
        "cases": outcome.cases,
        "failed": list(outcome.failed),
    }

    def _apply(doc: dict[str, Any]) -> dict[str, Any]:
        doc.setdefault("results", {}).setdefault(model, {})[sha256] = entry
        return doc

    read_modify_write(current_home().prompt_tests_file, _apply)
    return entry
