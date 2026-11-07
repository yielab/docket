"""Production watched by window: the work figures of a docket home, with Wilson intervals.

A home is read, never written. The pods come from `docket status --all --json`; the task records
(hops, models, prompt manifests, completion times, which no command prints whole) are read from
each pod's queue file, the way `World.stored_task` reads it. Every figure is a proportion, so it
carries its `k/n` and a Wilson 95% interval, by pod, role, model id and prompt hash. The trend sets
the last 7 days against the 28 before and marks a change only when the two intervals do not
overlap. Tokens only; no price appears anywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.kernel.clock import parse_epoch
from docket.kernel.home import Home
from docket.tasks.domain.state import Status
from evals.evaluator.metrics import wilson

DAY_S = 86400
RECENT_DAYS = 7
PRIOR_DAYS = 28
MIN_N = 5
QUEUE_FILE = "TASK_LIST.json"
_NO_HASH = "-"


class HomeError(RuntimeError):
    """A home that cannot be read; the message is one line for the operator."""


@dataclass(frozen=True)
class Pod:
    name: str
    lead: str
    codebase: str


@dataclass(frozen=True)
class Group:
    """What a figure is split by."""

    pod: str
    role: str
    model: str
    prompt: str


@dataclass(frozen=True)
class Observation:
    """One counted event of one figure: whether it was a hit, when, and for which group."""

    figure: str
    group: Group
    at: float
    hit: bool


@dataclass(frozen=True)
class Rate:
    hits: int
    n: int

    @property
    def value(self) -> float:
        return self.hits / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.value, self.n)

    def render(self) -> str:
        low, high = self.interval
        shown = (
            f"{self.hits}/{self.n} = {self.value:.2f} (Wilson 95% {low:.2f}-{high:.2f}) n={self.n}"
        )
        return shown


@dataclass(frozen=True)
class Figure:
    """A figure's name and whether a higher value is the better direction."""

    name: str
    higher_is_better: bool
    meaning: str


FIGURES = (
    Figure("success", True, "tasks that ended done, of the tasks that reached a terminal status"),
    Figure("reviewer_rejection", False, "reviewer verdicts other than approve, of all verdicts"),
    Figure("rework", False, "tasks with at least one rework cycle, of the terminal tasks"),
)
_BY_NAME = {f.name: f for f in FIGURES}


def _env(home: Path) -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if not k.startswith("DOCKET_")}
    return {**kept, "DOCKET_HOME": str(home), "DOCKET_SERVICE_MANAGER": "none", "NO_COLOR": "1"}


def list_pods(home: Path) -> list[Pod]:
    """Every pod of the home, from `docket status --all --json`."""
    if not home.is_dir():
        raise HomeError(f"{home.name}: not a directory")
    command = [sys.executable, "-m", "docket", "status", "--all", "--json"]
    done = subprocess.run(
        command, env=_env(home), capture_output=True, text=True, check=False, timeout=120
    )
    if done.returncode != 0:
        raise HomeError(f"docket status failed: {done.stderr.strip()[-200:] or done.stdout[-200:]}")
    try:
        projects = json.loads(done.stdout)["projects"]
    except (ValueError, KeyError) as error:
        raise HomeError("docket status printed no pod list") from error
    pods = []
    for project in projects:
        leads = [m["id"] for m in project.get("members", []) if m.get("role") == "lead"]
        if leads:
            pods.append(Pod(str(project["id"]), str(leads[0]), str(project.get("path") or "")))
    return pods


def read_queue(home: Path, pod: Pod) -> list[dict[str, Any]]:
    """The pod's stored task records; an unreadable or missing queue is no tasks."""
    queue = Home(home).workspace_dir(pod.lead) / QUEUE_FILE
    try:
        raw = json.loads(queue.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    tasks = raw.get("tasks") if isinstance(raw, dict) else raw
    return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []


def prompt_key(hop: Mapping[str, Any]) -> str:
    """The first eight hex digits of the hop's identity and hop prompt layers, as docket froze them."""
    layers = (hop.get("promptManifest") or {}).get("layers", [])
    by_layer = {x.get("layer"): str(x.get("sha256", "")) for x in layers if isinstance(x, dict)}
    parts = [by_layer[k][:8] for k in ("identity", "hop") if by_layer.get(k)]
    return "/".join(parts) if parts else _NO_HASH


def _group(pod: str, hop: Mapping[str, Any] | None) -> Group:
    if hop is None:
        return Group(pod, "none", "", _NO_HASH)
    return Group(pod, str(hop.get("role") or "none"), str(hop.get("model") or ""), prompt_key(hop))


def observe(pod: str, record: Mapping[str, Any]) -> list[Observation]:
    """The observations one stored task yields; none unless it is terminal and has `completedAt`."""
    at = parse_epoch(record.get("completedAt"))
    if record.get("status") not in Status.TERMINAL or at is None:
        return []
    hops = [h for h in record.get("hops", []) if isinstance(h, dict)]
    roled = [h for h in hops if h.get("role")]
    last = _group(pod, roled[-1] if roled else None)
    reworked = any(int(h.get("cycle") or 0) > 0 for h in hops)
    found = [
        Observation("success", last, at, record.get("status") == Status.done),
        Observation("rework", last, at, reworked),
    ]
    for hop in roled:
        verdict = (hop.get("artifact") or {}).get("verdict")
        if verdict:
            found.append(
                Observation(
                    "reviewer_rejection", _group(pod, hop), at, verdict.lower() != "approve"
                )
            )
    return found


def collect(home: Path) -> list[Observation]:
    """Every observation of every pod of the home."""
    return [
        o
        for pod in list_pods(home)
        for record in read_queue(home, pod)
        for o in observe(pod.name, record)
    ]


def tally(
    observations: Iterable[Observation], since: float, until: float
) -> dict[tuple[str, Group], Rate]:
    """The rate of each (figure, group) over the observations with `since <= at < until`."""
    counts: dict[tuple[str, Group], list[int]] = {}
    for o in observations:
        if since <= o.at < until:
            cell = counts.setdefault((o.figure, o.group), [0, 0])
            cell[0] += int(o.hit)
            cell[1] += 1
    return {key: Rate(c[0], c[1]) for key, c in counts.items()}


@dataclass(frozen=True)
class Trend:
    """A figure's two windows and what they allow us to say."""

    recent: Rate
    prior: Rate
    verdict: str

    def render(self) -> str:
        return f"last {RECENT_DAYS}d {self.recent.render()} | prior {PRIOR_DAYS}d {self.prior.render()} | {self.verdict}"


def judge(figure: Figure, recent: Rate, prior: Rate) -> str:
    """`worse`, `better` or `not detectable`, from whether the two Wilson intervals overlap."""
    if recent.n < MIN_N or prior.n < MIN_N:
        return f"not detectable (fewer than {MIN_N} samples in a window)"
    (lo_r, hi_r), (lo_p, hi_p) = recent.interval, prior.interval
    if hi_r < lo_p:
        return "better" if not figure.higher_is_better else "worse"
    if lo_r > hi_p:
        return "worse" if not figure.higher_is_better else "better"
    return "not detectable (the intervals overlap)"


def _sorted(keys: Iterable[tuple[str, Group]]) -> list[tuple[str, Group]]:
    order = {f.name: i for i, f in enumerate(FIGURES)}
    return sorted(keys, key=lambda k: (order[k[0]], k[1].pod, k[1].role, k[1].model, k[1].prompt))


def _label(figure: str, g: Group) -> str:
    return f"{figure:<18} pod={g.pod} role={g.role} model={g.model or '-'} prompt={g.prompt}"


def render_report(observations: list[Observation], now: float) -> str:
    """The last 7 days, one line per figure and group."""
    rates = tally(observations, now - RECENT_DAYS * DAY_S, now + 1)
    if not rates:
        return f"no terminal tasks in the last {RECENT_DAYS} days\n"
    lines = [f"online figures, last {RECENT_DAYS} days"]
    lines += [f"{_label(f, g)}  {rates[(f, g)].render()}" for f, g in _sorted(rates)]
    return "\n".join(lines) + "\n"


def render_trend(observations: list[Observation], now: float) -> str:
    """The last 7 days against the 28 before, one line per figure and group seen in either."""
    recent = tally(observations, now - RECENT_DAYS * DAY_S, now + 1)
    prior = tally(observations, now - (RECENT_DAYS + PRIOR_DAYS) * DAY_S, now - RECENT_DAYS * DAY_S)
    keys = _sorted({*recent, *prior})
    if not keys:
        return f"no terminal tasks in the last {RECENT_DAYS + PRIOR_DAYS} days\n"
    empty = Rate(0, 0)
    lines = [f"online trend: last {RECENT_DAYS} days against the {PRIOR_DAYS} before"]
    for key in keys:
        r, p = recent.get(key, empty), prior.get(key, empty)
        lines.append(f"{_label(*key)}  {Trend(r, p, judge(_BY_NAME[key[0]], r, p)).render()}")
    lines.append("")
    lines.append(
        "A change is marked worse or better only when the two Wilson 95% intervals do not overlap;"
    )
    lines.append(
        f"otherwise it is not detectable. Tokens only, no prices. Figures: {'; '.join(f'{f.name} = {f.meaning}' for f in FIGURES)}."
    )
    return "\n".join(lines) + "\n"


def online_report(home: Path, *, trend: bool, now: float | None = None) -> str:
    """The report for a home: the last 7 days, or with `trend` the 7 against the 28 before."""
    moment = time.time() if now is None else now
    observations = collect(home)
    return render_trend(observations, moment) if trend else render_report(observations, moment)
