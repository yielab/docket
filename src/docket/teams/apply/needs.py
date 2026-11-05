"""What a recipe's work still needs once it is applied: the ``needs:`` list in ``pod.yaml`` and the
readiness lines computed from facts the pod report already serves (``fetch_reach``,
``jail_enforces``) and from the search service the pod declares. Informational: nothing here writes
a setting or fails an apply."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.teams import fleet as _fleet
from docket.teams import network_posture as _network_posture
from docket.teams import pod_settings as _pod_settings
from docket.teams import services as _services
from docket.teams.apply.model import PodApplyError
from docket.teams.apply.search_probe import search_service, service_answers

FETCH_HOSTS = "fetch-hosts"
SEARCH_HOST = "search-host"
ISOLATION = "isolation"
NEEDS = (FETCH_HOSTS, SEARCH_HOST, ISOLATION)


@dataclass(frozen=True)
class NeedLine:
    """One need: met or not and, when not, the one command that meets it; *blocking* says an unmet
    need stops the work (``fetch-hosts``) rather than degrades it. ``wire()`` is the ``pod show
    --json`` shape, ``render()`` the line ``init``/``pod update``/``pod show`` print."""

    kind: str
    name: str
    satisfied: bool
    text: str
    fix: str = ""
    blocking: bool = False

    def wire(self) -> dict[str, Any]:
        """``{kind, name, fix, satisfied, blocking}``: ``name`` equals ``kind`` until a need is named
        per host."""
        return {
            "kind": self.kind,
            "name": self.name,
            "fix": self.fix,
            "satisfied": self.satisfied,
            "blocking": self.blocking,
        }

    def render(self) -> str:
        """``needs <name>: <text>`` and, when not satisfied, `` -> <fix>``."""
        line = f"needs {self.name}: {self.text}"
        return f"{line} -> {self.fix}" if self.fix else line


def declared_needs(manifest: dict[str, Any]) -> tuple[str, ...]:
    """The ``needs`` list of a loaded ``pod.yaml``, in written order. Raises ``PodApplyError``
    naming ``needs`` for a value that is not a list or an entry outside ``NEEDS``."""
    raw = manifest.get("needs")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PodApplyError("pod.yaml: 'needs' must be a list")
    for entry in raw:
        if entry not in NEEDS:
            raise PodApplyError(
                f"pod.yaml: 'needs' entry {entry!r} is not one of {', '.join(NEEDS)}"
            )
    return tuple(dict.fromkeys(raw))


def _fetch_line(reach: _network_posture.FetchReach) -> NeedLine:
    if reach.hosts:
        if _pod_settings.FETCH_ANY in reach.hosts:
            ready = "ready (any public host)"
        else:
            noun = "host" if len(reach.hosts) == 1 else "hosts"
            ready = f"ready ({len(reach.hosts)} {noun})"
        return NeedLine(FETCH_HOSTS, FETCH_HOSTS, True, ready, blocking=True)
    return NeedLine(
        FETCH_HOSTS,
        FETCH_HOSTS,
        False,
        "the researchers cannot read the web",
        reach.fix,
        blocking=True,
    )


def _search_line(project: str) -> NeedLine:
    command = f"docket setup search searxng --pod {project}"
    config = search_service(project)
    if config is None:
        return NeedLine(
            SEARCH_HOST,
            SEARCH_HOST,
            False,
            "no search service: SearXNG is free and runs in Docker, or use a Brave Search API key "
            "(see the recipe README)",
            command,
        )
    if service_answers(config):
        return NeedLine(SEARCH_HOST, SEARCH_HOST, True, "ready")
    fix = command if config.baseUrl == _services.SEARXNG_URL else "docket setup service list"
    return NeedLine(
        SEARCH_HOST,
        SEARCH_HOST,
        False,
        f"the search service '{config.name}' does not answer at {config.baseUrl}",
        fix,
    )


def _isolation_line() -> NeedLine:
    if _network_posture.jail_enforces():
        return NeedLine(ISOLATION, ISOLATION, True, "ready")
    why = "isolation is off" if not _fleet.get_isolation_enabled() else "no sandbox backend"
    return NeedLine(
        ISOLATION,
        ISOLATION,
        False,
        f"PDFs, and the web on a folder team, are not read: {why}",
        _network_posture.isolation_fix(),
    )


def readiness(project: str, needs: tuple[str, ...]) -> tuple[NeedLine, ...]:
    """One line per name in *needs*, in the order given, for pod *project* as it is now."""
    reach = _network_posture.fetch_reach(project)
    builders = {
        FETCH_HOSTS: lambda: _fetch_line(reach),
        SEARCH_HOST: lambda: _search_line(project),
        ISOLATION: _isolation_line,
    }
    return tuple(builders[need]() for need in needs)
