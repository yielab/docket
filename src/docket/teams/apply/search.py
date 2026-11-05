"""The pod's web search as a declared service: the ``search`` service document the ``web-research``
recipe ships, the SearXNG settings file under the home and the ``docker run`` line that serves it.
docket writes the files and starts nothing."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

import docket.kernel.templates as _templates
from docket.kernel.home import current_home
from docket.platform import mkdir_private
from docket.teams import services as _services
from docket.teams.apply.external import plan_services, write_services
from docket.teams.apply.model import ApplyAction

RECIPE = "web-research"
CONTAINER = "docket-searxng"
SEARXNG_IMAGE = "searxng/searxng"

_KEY_PLACEHOLDER = "__SECRET_KEY__"
_PUBLISHED = "127.0.0.1:8888:8080"


@dataclass(frozen=True)
class SearxngSetup:
    """What ``setup_searxng`` did: the settings file, whether this call wrote it (``False`` when
    it was kept), and the pod's service document with what happened to it."""

    settings: Path
    settings_written: bool
    service: Path
    service_action: ApplyAction


def searxng_settings_path() -> Path:
    """Where the SearXNG settings live: ``<home>/config/searxng/settings.yml``."""
    return current_home().config_dir / "searxng" / "settings.yml"


def docker_run_line(settings: Path) -> str:
    """The one command that serves *settings* on the loopback port the service names. The settings
    directory is mounted whole: the image keeps its own files next to the settings."""
    return (
        f"docker run -d --name {CONTAINER} --restart unless-stopped -p {_PUBLISHED} "
        f"-v {settings.parent}:/etc/searxng {SEARXNG_IMAGE}"
    )


def _write_settings(path: Path) -> bool:
    """Write the shipped settings with a random secret key unless *path* exists; True when written.
    The file is world-readable: the container's user is not the host's."""
    if path.is_file():
        return False
    template = (_templates.RECIPES_DIR / RECIPE / "searxng" / "settings.yml").read_text(
        encoding="utf-8"
    )
    mkdir_private(path.parent)
    path.parent.chmod(0o755)
    path.write_text(template.replace(_KEY_PLACEHOLDER, secrets.token_hex(16)), encoding="utf-8")
    path.chmod(0o644)
    return True


def setup_searxng(project: str) -> SearxngSetup:
    """Write the settings (kept when present) and the recipe's ``search.yaml`` into *project*'s
    ``services/`` (replaced when it differs). Raises ``PodApplyError``, writing nothing, when an
    operator service or an MCP server is named ``search``."""
    items, writes = plan_services(_templates.RECIPES_DIR / RECIPE, project)
    written = _write_settings(searxng_settings_path())
    write_services(project, tuple(writes))
    return SearxngSetup(
        settings=searxng_settings_path(),
        settings_written=written,
        service=_services.pod_services_dir(project) / "search.yaml",
        service_action=items[0].action,
    )
