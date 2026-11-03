"""A recipe says what its work still needs when it is applied, from `init` and from `pod update`.

The block is informational: it comes from the readers the pod report uses
(``effective_fetch_domains``, ``jail_enforces``) and never writes a setting.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.cli import pod_cli as _pod_cli
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod
from typer.testing import CliRunner

import docket.kernel.templates as _templates
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply

SUBJECT = "docket.teams.apply.needs"

RECIPES_DIR = _templates.RECIPES_DIR
runner = CliRunner()

FETCH_NOT_READY = "needs fetch-hosts: the researchers cannot read the web -> docket pod set fetchDomains <hosts> --pod demo"
SEARCH_NOT_READY = "needs search-host: no search site is allowed -> docket pod set fetchDomains 'html.duckduckgo.com' --pod demo"
ISOLATION_OFF = "needs isolation: PDFs are not read, isolation is off -> docket setup sandbox on"
NO_BACKEND = (
    "needs isolation: PDFs are not read, no sandbox backend -> docket setup sandbox backend docker"
)


def _needs_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("needs ")]


def _init_web_research(tmp_path: Path) -> tuple[int, str]:
    code = tmp_path / "code"
    code.mkdir()
    result = runner.invoke(app, ["init", "demo", str(code), "--recipe", "web-research"])
    return result.exit_code, result.output


@pytest.fixture
def no_backend(bind_launcher: Callable[..., Launcher]) -> None:
    bind_launcher(landlock=False, seatbelt=False, docker=False)


def test_init_on_a_fresh_home_lists_three_not_ready_lines_and_writes_no_setting(
    tmp_path: Path, no_backend: None
) -> None:
    """Isolation off and no fetchDomains: three lines, one command each, no setting written."""
    code, output = _init_web_research(tmp_path)

    assert code == 0, output
    assert _needs_lines(output) == [FETCH_NOT_READY, SEARCH_NOT_READY, ISOLATION_OFF]
    assert _fleet.get_isolation_state() == "off (default)"
    assert _pod_settings.effective_fetch_domains("demo") == ()


def test_init_reports_isolation_after_it_turns_isolation_on_where_a_backend_exists(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """Init records isolation on when a backend is detected, so the block must not say it is off."""
    bind_launcher(landlock=True)
    code, output = _init_web_research(tmp_path)

    assert code == 0, output
    assert _needs_lines(output) == [FETCH_NOT_READY, SEARCH_NOT_READY, "needs isolation: ready"]


def test_the_block_prints_once_per_apply(tmp_path: Path, no_backend: None) -> None:
    """One function prints the block: a single `needs fetch-hosts` line per init."""
    _, output = _init_web_research(tmp_path)

    assert output.count("needs fetch-hosts") == 1


def test_pod_update_prints_the_same_block(tmp_path: Path, no_backend: None) -> None:
    """The `pod update` path reports the same three lines after its plan."""
    with _seed_fixture_pod(tmp_path, "demo"):
        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _needs_lines(result.output) == [FETCH_NOT_READY, SEARCH_NOT_READY, ISOLATION_OFF]


def test_everything_ready_after_fetch_domains_and_isolation_on(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """A search site in fetchDomains and a jail that runs report all three ready."""
    bind_launcher(landlock=True)
    with _seed_fixture_pod(tmp_path, "demo"):
        assert (
            _pod_cli(
                "set", "fetchDomains", "html.duckduckgo.com,*.wikipedia.org", "--pod", "demo"
            ).exit_code
            == 0
        )
        _fleet.apply_workspace_isolation()

        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _needs_lines(result.output) == [
            "needs fetch-hosts: ready (2 hosts)",
            "needs search-host: ready",
            "needs isolation: ready",
        ]


def test_hosts_without_a_search_site_name_the_search_command_with_the_current_hosts(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """Only the search line is not ready, and its command keeps the hosts already allowed."""
    bind_launcher(landlock=True)
    with _seed_fixture_pod(tmp_path, "demo"):
        assert _pod_cli("set", "fetchDomains", "*.wikipedia.org", "--pod", "demo").exit_code == 0
        _fleet.apply_workspace_isolation()

        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert _needs_lines(result.output) == [
            "needs fetch-hosts: ready (1 host)",
            "needs search-host: no search site is allowed -> docket pod set fetchDomains "
            "'*.wikipedia.org,html.duckduckgo.com' --pod demo",
            "needs isolation: ready",
        ]


def test_isolation_recorded_on_with_no_backend_names_the_backend_command(
    tmp_path: Path, no_backend: None
) -> None:
    """Isolation on but no backend: the missing half is the backend, not `setup sandbox on`."""
    with _seed_fixture_pod(tmp_path, "demo"):
        _fleet.apply_workspace_isolation()

        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert NO_BACKEND in _needs_lines(result.output)
        assert ISOLATION_OFF not in _needs_lines(result.output)


def test_a_declared_search_service_counts_as_a_search_host(
    tmp_path: Path, no_backend: None
) -> None:
    """A `kind: service` document naming a search operation satisfies `search-host`."""
    with _seed_fixture_pod(tmp_path, "demo"):
        services = current_home().pod_config_dir("demo") / "services"
        services.mkdir(parents=True)
        (services / "brave.yaml").write_text(
            "kind: service\nname: brave\nbaseUrl: https://api.search.example/\n"
            "operations:\n  - name: web_search\n    method: GET\n    path: /search\n"
        )

        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert "needs search-host: ready" in _needs_lines(result.output)


def test_a_recipe_without_needs_prints_no_block(tmp_path: Path, no_backend: None) -> None:
    """Only a recipe that declares `needs:` gets a block."""
    with _seed_fixture_pod(tmp_path, "demo"):
        result = _pod_cli("update", "secure-build", "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _needs_lines(result.output) == []


def test_a_need_outside_the_three_names_is_refused_naming_needs(tmp_path: Path) -> None:
    """Planning rejects a `needs` entry that is not one of the three facts."""
    recipe = tmp_path / "bad"
    recipe.mkdir()
    (recipe / "pod.yaml").write_text("kind: pod\nname: bad\nneeds: [wifi]\n")
    with (
        _seed_fixture_pod(tmp_path / "home", "demo"),
        pytest.raises(_model.PodApplyError, match="needs"),
    ):
        _pod_apply.plan_apply("demo", recipe)


def test_web_research_declares_the_three_needs_and_its_text_is_not_stale() -> None:
    """The recipe declares `needs:`; its README speaks of fetchDomains, not the old env var."""
    manifest = (RECIPES_DIR / "web-research" / "pod.yaml").read_text(encoding="utf-8")
    readme = (RECIPES_DIR / "web-research" / "README.md").read_text(encoding="utf-8")

    assert "needs: [fetch-hosts, search-host, isolation]" in manifest
    assert "docket pod set fetchDomains" in readme
    assert "FETCH_ALLOWED_DOMAINS" not in readme
    assert "setup mcp add" not in readme
    assert "poppler" not in readme.lower() and "pdftotext" not in readme.lower()
