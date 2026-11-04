"""What a recipe's work still needs once it is applied: the ``needs:`` list in ``pod.yaml`` and the
readiness lines computed from facts the pod report already serves (``effective_fetch_domains``,
``jail_enforces``). Informational: nothing here writes a setting or fails an apply."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.platform.fetch import host_allowed
from docket.teams import fleet as _fleet
from docket.teams import network_posture as _network_posture
from docket.teams import pod_settings as _pod_settings
from docket.teams import services as _services
from docket.teams.apply.model import PodApplyError

FETCH_HOSTS = "fetch-hosts"
SEARCH_HOST = "search-host"
ISOLATION = "isolation"
NEEDS = (FETCH_HOSTS, SEARCH_HOST, ISOLATION)

# Search sites a researcher can read through `fetch`; the first is what the command suggests.
SEARCH_HOSTS = ("html.duckduckgo.com", "lite.duckduckgo.com", "www.bing.com", "www.google.com")


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


def _declares_search(project: str) -> bool:
    """True when a declared service (the pod's own or the operator's) is for search: its name or
    one of its operations' names contains ``search``."""
    for service in _services.load_services(project):
        names = (service.name, *(op.name for op in service.operations))
        if any("search" in name.lower() for name in names):
            return True
    return False


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


def _search_line(project: str, hosts: tuple[str, ...]) -> NeedLine:
    if any(host_allowed(site, hosts) for site in SEARCH_HOSTS) or _declares_search(project):
        return NeedLine(SEARCH_HOST, SEARCH_HOST, True, "ready")
    value = ",".join((*hosts, SEARCH_HOSTS[0]))
    return NeedLine(
        SEARCH_HOST,
        SEARCH_HOST,
        False,
        "no search site is allowed",
        f"docket pod set fetchDomains '{value}' --pod {project}",
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
        SEARCH_HOST: lambda: _search_line(project, reach.hosts),
        ISOLATION: _isolation_line,
    }
    return tuple(builders[need]() for need in needs)
