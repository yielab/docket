"""Every `docket ...` invocation in the docs, specs, templates and help examples is live.

The removed-name guard proves old names are gone; this one runs
scripts/maint/lint_cli_invocations.py in process against the live Click tree.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "maint" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rcn = _load("rewrite_cli_names")
lint = _load("lint_cli_invocations")

ROOTS: tuple[str, ...] = (
    "README.md",
    "CONTRIBUTING.md",
    "docs",
    "specs",
    "src/docket/templates",
)


def findings(roots: tuple[str, ...] = ROOTS) -> list[str]:
    hits: list[str] = []
    for path in rcn.iter_files(roots):
        text = rcn.read_text(path)
        if text is None:
            continue
        hits += lint.lint_text(rcn._rel(path), text)
    return hits


class TestRoots:
    def test_every_documented_invocation_is_live(self) -> None:
        start = time.monotonic()
        hits = findings() + lint.lint_examples()
        assert hits == [], "invocations the live tree does not have:\n" + "\n".join(hits)
        assert time.monotonic() - start < 2.0

    def test_the_linter_catches_its_planted_lines(self) -> None:
        assert lint.self_check() == []

    def test_every_leaf_has_an_example_line(self) -> None:
        assert len(list(lint.leaf_examples())) > 40


class TestPlanted:
    def test_an_option_the_leaf_lacks_is_found(self, tmp_path: Path) -> None:
        doc = tmp_path / "x.md"
        doc.write_text("Run `docket task list --retry` to see.\n", encoding="utf-8")
        assert len(lint.lint([doc])) == 1

    def test_a_false_example_line_is_found(self, monkeypatch) -> None:
        monkeypatch.setattr(
            lint, "leaf_examples", lambda: iter([("docket x", "docket status <a>")])
        )
        assert len(lint.lint_examples()) == 1


# Scripts drive the CLI as argv lists, which the text linter cannot see, so the verb after a
# literal "task" is checked against the live group.
DRIVER_ROOTS: tuple[str, ...] = ("scripts", "examples")
DRIVER_SKIP: tuple[str, ...] = ()
DRIVER_SUFFIXES = {".py", ".sh", ".md", ".yaml", ".yml"}
# Yaml comments narrate retired dialects in prose, so only the field check reads them.
INVOCATION_SUFFIXES = {".py", ".sh", ".md"}
RETIRED_FIELDS = re.compile(r"approvalToken|consultAnswer|gateOverridePipelineIndex")
TASK_ARGV = re.compile(r"""["']task["'],\s*["']([a-z][a-z-]*)["']""")
# Prose naming a removed verb without the word docket, and a verb held in a variable the guard
# cannot read: both hide a call the argv check would miss.
RETIRED_PHRASE = re.compile(r"\btask (?:approve|deny)\b")
VARIABLE_VERB = re.compile(r"""["']task["'],\s*[a-z_]\w*\s*[,)]""")
AFTER_A_LITERAL = re.compile(r"""["']\s*,\s*$""")


def argv_verbs(line: str) -> list[str]:
    """Verbs after a literal "task" that starts an argv, not one more member of a list of names."""
    return [
        m.group(1)
        for m in TASK_ARGV.finditer(line)
        if not AFTER_A_LITERAL.search(line[: m.start()])
    ]


def driver_findings() -> list[str]:
    task_verbs = set(lint.ROOT_CMD.commands["task"].commands)
    hits: list[str] = []
    for path in rcn.iter_files(DRIVER_ROOTS, skip=DRIVER_SKIP):
        if path.suffix not in DRIVER_SUFFIXES:
            continue
        text = rcn.read_text(path)
        if text is None:
            continue
        label = rcn._rel(path)
        if path.suffix in INVOCATION_SUFFIXES:
            hits += lint.lint_text(label, text)
        for n, line in enumerate(text.splitlines(), 1):
            if RETIRED_PHRASE.search(line) or VARIABLE_VERB.search(line):
                hits.append(f"{label}:{n}: a removed or unreadable task verb: {line.strip()[:80]}")
            if RETIRED_FIELDS.search(line):
                hits.append(f"{label}:{n}: retired task field: {line.strip()[:80]}")
            for verb in argv_verbs(line):
                if verb not in task_verbs:
                    hits.append(f"{label}:{n}: 'task {verb}' is not a verb of 'task'")
    return hits


class TestDrivers:
    def test_scripts_examples_and_benchmarks_call_only_live_verbs_and_fields(self) -> None:
        start = time.monotonic()
        hits = driver_findings()
        assert hits == [], "callers of removed commands or fields:\n" + "\n".join(hits)
        assert time.monotonic() - start < 2.0

    def test_a_removed_verb_and_a_retired_field_are_found(self, tmp_path: Path) -> None:
        planted = tmp_path / "p.py"
        planted.write_text('run("task", "approve", t)\nx = task["approvalToken"]\n')
        text = planted.read_text()
        assert argv_verbs(text.splitlines()[0]) == ["approve"]
        assert argv_verbs('GROUPS = ["inbox", "task", "run"]') == []
        assert RETIRED_FIELDS.search(text)
        assert RETIRED_PHRASE.search("`task approve`, `task deny` and `task show`.")
        assert VARIABLE_VERB.search('_public_cli(home, workspace, "task", command, token)')
