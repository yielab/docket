"""The pod's web search as one answer: which provider the service named ``search`` is, whether it is
ready and the one command that makes it so. The ``search-host`` need line and the pod report's
``search`` both read it, so they cannot disagree. Informational: nothing here writes a setting."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from docket.governance import secrets as _secrets
from docket.kernel.service import ServiceConfig, secret_names
from docket.teams import services as _services
from docket.teams.apply import search_probe as _probe

SEARXNG = "searxng"
BRAVE = "brave"
CUSTOM = "custom"
NONE = "none"

_SERVICES_FIX = "docket setup service list"


@dataclass(frozen=True)
class SearchState:
    """What a pod's search is: *provider*, whether it is *ready*, a one-sentence *reason*, the one
    *fix* command (``""`` when ready), *detail* (the words inside ``ready (...)``) and the
    *options* a plan of record can render, each ``{provider, command, secret}``."""

    provider: str
    ready: bool
    reason: str
    fix: str
    detail: str
    options: tuple[dict[str, str], ...]

    def need_text(self) -> str:
        """The ``search-host`` line's words: ``ready (<detail>)`` or the reason."""
        return f"ready ({self.detail})" if self.ready else self.reason

    def wire(self) -> dict[str, object]:
        """``{provider, ready, reason, fix, options}``: the shape ``GET /pods/<p>`` carries."""
        return {
            "provider": self.provider,
            "ready": self.ready,
            "reason": self.reason,
            "fix": self.fix,
            "options": [dict(option) for option in self.options],
        }


def searxng_command(project: str) -> str:
    """The one command that sets *project* up on SearXNG."""
    return f"docket setup search searxng --pod {project}"


def brave_command(project: str) -> str:
    """The one command that sets *project* up on Brave Search."""
    return f"docket setup search brave --pod {project}"


def provider_of(config: ServiceConfig) -> str:
    """``searxng`` or ``brave`` for the base URL docket's setup writes, else ``custom``."""
    if config.baseUrl == _services.SEARXNG_URL:
        return SEARXNG
    if config.baseUrl == _services.BRAVE_URL:
        return BRAVE
    return CUSTOM


def _options(project: str) -> tuple[dict[str, str], ...]:
    return (
        {"provider": SEARXNG, "command": searxng_command(project), "secret": ""},
        {"provider": BRAVE, "command": brave_command(project), "secret": _services.BRAVE_SECRET},
    )


def _missing_secret(config: ServiceConfig) -> str | None:
    """The first secret *config*'s ``auth`` references that is not stored, ``None`` when every one
    resolves. It reads the secret store and makes no network call."""
    try:
        _services.resolve_auth(config)
    except _services.ServiceSecretError:
        names = secret_names(config.auth.value) if config.auth else []
        return next((n for n in names if _secrets.secret_value(n) is None), _services.BRAVE_SECRET)
    return None


def _brave_state(config: ServiceConfig, options: tuple[dict[str, str], ...]) -> SearchState:
    missing = _missing_secret(config)
    if missing is None:
        return SearchState(BRAVE, True, "Web search goes through Brave.", "", BRAVE, options)
    return SearchState(
        BRAVE,
        False,
        f"the Brave Search key is not stored: no secret named '{missing}'",
        f"docket setup secret set {missing} --stdin",
        BRAVE,
        options,
    )


def search_state(project: str) -> SearchState:
    """*project*'s search as it is now. A SearXNG or custom service is probed with one ``GET``; a
    Brave one is ready when its secrets resolve, with no call to Brave (a probe spends quota)."""
    options = _options(project)
    config = _probe.search_service(project)
    if config is None:
        return SearchState(
            NONE,
            False,
            "no search service: SearXNG is free and runs in Docker, or use a Brave Search API key "
            f"({brave_command(project)})",
            searxng_command(project),
            "",
            options,
        )
    provider = provider_of(config)
    if provider == BRAVE:
        return _brave_state(config, options)
    where = urlsplit(config.baseUrl).netloc or config.baseUrl
    detail = f"{provider} at {where}"
    if _probe.service_answers(config):
        return SearchState(
            provider, True, f"Web search goes through {detail}.", "", detail, options
        )
    fix = searxng_command(project) if provider == SEARXNG else _SERVICES_FIX
    return SearchState(
        provider,
        False,
        f"the search service '{config.name}' does not answer at {config.baseUrl}",
        fix,
        detail,
        options,
    )
