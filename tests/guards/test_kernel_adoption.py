"""Ratchet: code that does by hand what a ``kernel/`` module owns may only shrink.

``scripts/maint/measure_kernel_adoption.py`` counts each rule's sites outside ``kernel/``;
``kernel_adoption_baseline.txt`` records the counts. A count above its baseline is new code
reaching past the kernel. A count below it is a migration that forgot to lower the baseline,
which would leave room for a regression to hide, so both fail.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

SUBJECT = "docket.kernel"

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "measure_kernel_adoption.py"


def _load_measure_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_measure_kernel_adoption_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MEASURE = _load_measure_module()
_BASELINE = _MEASURE.read_baseline()


def _hits(rule: str, source: str, rel: str = "src/docket/core/sample.py") -> list[str]:
    detector = _MEASURE.RULES[rule][0]
    return [what for _, what in detector(ast.parse(source), rel)]


def test_the_baseline_names_every_rule() -> None:
    assert set(_BASELINE) == set(_MEASURE.RULES)


@pytest.mark.parametrize("rule", list(_MEASURE.RULES))
def test_count_equals_the_baseline(rule: str) -> None:
    count, baseline = len(_MEASURE.scan(rule)), _BASELINE[rule]
    see = f"see: python3 scripts/maint/measure_kernel_adoption.py {rule} --list"
    assert count <= baseline, f"{rule} grew to {count}, above baseline {baseline}; {see}"
    assert count >= baseline, (
        f"{rule} fell to {count}, below baseline {baseline}; record it with "
        f"`python3 scripts/maint/measure_kernel_adoption.py {rule} --write`"
    )


def test_kernel_is_never_scanned() -> None:
    # Every rule reads its modules through `_parsed`, the one place `kernel/` is left out, so
    # checking what it returns covers every rule without running the detectors a second time.
    parsed = {(root, needle) for _, root, needle in _MEASURE.RULES.values()}
    assert not [rel for key in parsed for rel, _ in _MEASURE._parsed(*key) if "/kernel/" in rel]


# Each rule must see the shapes it exists for, through any import spelling, and stay quiet on
# their look-alikes. Without these a detector that matched nothing would hold any baseline.
BITES = {
    "clock": [
        "import datetime as _dt\n_dt.datetime.now(_dt.UTC)",
        "from datetime import datetime\ndatetime.now()",
        "from datetime import date\ndate.today()",
        "import time as _time\n_time.monotonic()",
        "from time import perf_counter\nperf_counter()",
        "import time\nSink(clock=time.monotonic)",
    ],
    "ids": ["import uuid\nuuid.uuid4()", "from uuid import uuid4 as u\nu().hex"],
    "text": [
        "def f(t):\n    return t if len(t) < 9 else t[:8] + '…'",
        "def f(t):\n    if len(t) > 9:\n        return f'{t[:9]}…[truncated {len(t) - 9} chars]'",
        "' '.join(t.split())",
    ],
    "error-classes": ["class PodError(ValueError): ...", "class RunError(Exception): ..."],
    "error-raises": ["raise ValueError('bad')", "raise RuntimeError"],
    "environ": [
        "import os\nos.environ.get('X')",
        "import os\nos.getenv('X')",
        "from os import environ\nenviron['X']",
    ],
    "config-reads": [
        "from docket import config as _cfg\n_cfg.DOCKET_HOME",
        "from .. import config as cfg\ncfg.AUDIT_LOG",
        "from docket.config import DOCKET_HOME",
    ],
    "config-patches": [
        "from docket import config as _cfg\nmonkeypatch.setattr(_cfg, 'AUDIT_LOG', p)",
        "import docket.config\nm.delattr(docket.config, 'AUDIT_LOG')",
        "monkeypatch.setattr('docket.config.AUDIT_LOG', p)",
    ],
    "repointers": [
        "repoint_docket_home(monkeypatch, tmp_path)",
        "conftest.repoint_docket_home(m, p)",
    ],
}
QUIET = {
    "clock": ["import time\ntime.sleep(1)", "from docket.kernel import clock\nclock.now()"],
    "ids": [
        "import secrets\nsecrets.token_hex(8)",
        "from docket.kernel.ids import new_id\nnew_id('a')",
    ],
    "text": [
        "def f(digest):\n    return f'hash {digest[:12]}...'",
        "def f(t):\n    return t[:8] + '…'",
        "' '.join(t.split(','))",
    ],
    "error-classes": [
        "class ApprovalNoop(Exception): ...",
        "class _Internal(ValueError): ...",
        "from docket.kernel.errors import InvalidInput\nclass PodError(InvalidInput): ...",
    ],
    "error-raises": ["raise", "raise TypeError('wrong type')", "raise InvalidInput('bad')"],
    "environ": ["environ = {}\nenviron['X']", "import os\nos.path.join('a')"],
    "config-reads": ["from docket import ui\nui.error('x')", "config = {}\nconfig['DOCKET_HOME']"],
    "config-patches": [
        "from docket.core import secrets\nmonkeypatch.setattr(secrets, 'SECRETS_FILE', p)",
        "monkeypatch.setattr('docket.core.secrets.SECRETS_FILE', p)",
        "use_home(dataclasses.replace(current_home(), fleet_file_override=p))",
    ],
    "repointers": ["use_home(Home(tmp_path))"],
}


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in BITES.items() for s in ss])
def test_rule_bites(rule: str, source: str) -> None:
    assert _hits(rule, source), f"{rule} missed:\n{source}"


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in QUIET.items() for s in ss])
def test_rule_stays_quiet_on_a_look_alike(rule: str, source: str) -> None:
    assert not _hits(rule, source), f"{rule} flagged:\n{source}"
