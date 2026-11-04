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
    """One need: whether it is met and, when not, the one command that meets it. ``wire()`` is the
    shape ``docket pod show --json`` serves; ``render()`` is the line ``init``/``pod update``/
    ``pod show`` print."""

    kind: str
    name: str
    satisfied: bool
    text: str
    fix: str = ""

    def wire(self) -> dict[str, Any]:
        """``{kind, name, fix, satisfied}``: ``name`` equals ``kind`` until a need is named per host."""
        return {
            "kind": self.kind,
            "name": self.name,
            "fix": self.fix,
            "satisfied": self.satisfied,
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


def _fetch_line(project: str, hosts: tuple[str, ...]) -> NeedLine:
    if hosts:
        noun = "host" if len(hosts) == 1 else "hosts"
        return NeedLine(FETCH_HOSTS, FETCH_HOSTS, True, f"ready ({len(hosts)} {noun})")
    return NeedLine(
        FETCH_HOSTS,
        FETCH_HOSTS,
        False,
        "the researchers cannot read the web",
        f"docket pod set fetchDomains <hosts> --pod {project}",
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
    if not _fleet.get_isolation_enabled():
        return NeedLine(
            ISOLATION,
            ISOLATION,
            False,
            "PDFs are not read, isolation is off",
            "docket setup sandbox on",
        )
    return NeedLine(
        ISOLATION,
        ISOLATION,
        False,
        "PDFs are not read, no sandbox backend",
        "docket setup sandbox backend docker",
    )


def readiness(project: str, needs: tuple[str, ...]) -> tuple[NeedLine, ...]:
    """One line per name in *needs*, in the order given, for pod *project* as it is now."""
    hosts = _pod_settings.effective_fetch_domains(project)
    builders = {
        FETCH_HOSTS: lambda: _fetch_line(project, hosts),
        SEARCH_HOST: lambda: _search_line(project, hosts),
        ISOLATION: _isolation_line,
    }
    return tuple(builders[need]() for need in needs)
