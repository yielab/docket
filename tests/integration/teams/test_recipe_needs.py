"""A recipe says what its work still needs when it is applied, from `init` and from `pod update`.

The block is informational: it comes from the readers the pod report uses
(``effective_fetch_domains``, ``jail_enforces``) and never writes a setting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

FETCH_NOT_READY = "needs fetch-hosts: the researchers cannot read the web -> docket pod set fetchDomains <host> --pod demo"
SEARCH_NOT_READY = "needs search-host: no search site is allowed -> docket pod set fetchDomains 'html.duckduckgo.com' --pod demo"
ISOLATION_OFF = "needs isolation: PDFs, and the web on a folder team, are not read: isolation is off -> docket setup sandbox on"
NO_BACKEND = "needs isolation: PDFs, and the web on a folder team, are not read: no sandbox backend -> docket setup sandbox backend docker"


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


def _show_needs(project: str = "demo") -> list[dict[str, Any]]:
    result = runner.invoke(app, ["pod", "show", "--pod", project, "--json"])
    assert result.exit_code == 0, result.output
    needs: list[dict[str, Any]] = json.loads(result.stdout)["needs"]
    return needs


def _recipe_dir(tmp_path: Path, name: str, extra: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    (directory / "pod.yaml").write_text(f"kind: pod\nname: {name}\n{extra}", encoding="utf-8")
    return directory


def test_pod_show_json_carries_the_three_needs_the_recipe_declared(
    tmp_path: Path, no_backend: None
) -> None:
    """A fresh home: `init --recipe web-research` leaves three unsatisfied needs, each with its fix."""
    code, output = _init_web_research(tmp_path)
    assert code == 0, output

    assert _show_needs() == [
        {
            "kind": "fetch-hosts",
            "name": "fetch-hosts",
            "fix": "docket pod set fetchDomains <host> --pod demo",
            "satisfied": False,
            "blocking": True,
        },
        {
            "kind": "search-host",
            "name": "search-host",
            "fix": "docket pod set fetchDomains 'html.duckduckgo.com' --pod demo",
            "satisfied": False,
            "blocking": False,
        },
        {
            "kind": "isolation",
            "name": "isolation",
            "fix": "docket setup sandbox on",
            "satisfied": False,
            "blocking": False,
        },
    ]


def test_pod_show_prints_one_line_per_need_in_the_apply_words(
    tmp_path: Path, no_backend: None
) -> None:
    """`pod show` repeats the three lines `init` printed, byte for byte."""
    _init_web_research(tmp_path)

    result = runner.invoke(app, ["pod", "show", "--pod", "demo"])

    assert _needs_lines(result.output) == [FETCH_NOT_READY, SEARCH_NOT_READY, ISOLATION_OFF]


def test_pod_show_json_recomputes_satisfaction_and_keeps_the_recorded_list(
    tmp_path: Path, no_backend: None
) -> None:
    """Setting a search host satisfies two needs with an empty fix; the recorded list is unchanged."""
    _init_web_research(tmp_path)
    before = _fleet.meta_get("demo-lead", "needs", "")

    assert _pod_cli("set", "fetchDomains", "html.duckduckgo.com", "--pod", "demo").exit_code == 0

    by_kind = {entry["kind"]: entry for entry in _show_needs()}
    assert (by_kind["fetch-hosts"]["satisfied"], by_kind["fetch-hosts"]["fix"]) == (True, "")
    assert (by_kind["search-host"]["satisfied"], by_kind["search-host"]["fix"]) == (True, "")
    assert by_kind["isolation"]["satisfied"] is False
    assert (
        _fleet.meta_get("demo-lead", "needs", "") == before == "fetch-hosts,search-host,isolation"
    )


def test_pod_show_json_has_no_needs_for_a_pod_whose_recipes_declared_none(
    tmp_path: Path, no_backend: None
) -> None:
    """Nothing recorded: the key is present and empty, and `pod show` prints no needs line."""
    with _seed_fixture_pod(tmp_path, "demo"):
        assert _show_needs() == []
        assert _needs_lines(runner.invoke(app, ["pod", "show", "--pod", "demo"]).output) == []


def test_a_later_directory_without_needs_keeps_the_recorded_three(
    tmp_path: Path, no_backend: None
) -> None:
    """Applying a recipe that declares no `needs` leaves the recorded list as it was."""
    with _seed_fixture_pod(tmp_path, "demo"):
        assert _pod_cli("update", "web-research", "--pod", "demo").exit_code == 0

        assert _pod_cli("update", "secure-build", "--pod", "demo").exit_code == 0

        assert [e["kind"] for e in _show_needs()] == ["fetch-hosts", "search-host", "isolation"]


def test_a_later_directory_naming_a_need_already_recorded_adds_no_duplicate(
    tmp_path: Path, no_backend: None
) -> None:
    """The union is first-seen order with no repeat; a new name lands after the recorded ones."""
    with _seed_fixture_pod(tmp_path, "demo"):
        first = _recipe_dir(tmp_path, "first", "needs: [isolation]\n")
        assert _pod_cli("update", str(first), "--pod", "demo").exit_code == 0
        assert _fleet.meta_get("demo-lead", "needs", "") == "isolation"

        assert _pod_cli("update", "web-research", "--pod", "demo").exit_code == 0

        assert _fleet.meta_get("demo-lead", "needs", "") == "isolation,fetch-hosts,search-host"
        again = _recipe_dir(tmp_path, "again", "needs: [isolation]\n")
        assert _pod_cli("update", str(again), "--pod", "demo").exit_code == 0
        assert _fleet.meta_get("demo-lead", "needs", "") == "isolation,fetch-hosts,search-host"


def test_needs_is_recorded_not_settable(tmp_path: Path) -> None:
    """`pod set needs` and a `pod.yaml` `settings.needs` are refused naming the key."""
    with _seed_fixture_pod(tmp_path / "home", "demo"):
        result = _pod_cli("set", "needs", "isolation", "--pod", "demo")
        assert result.exit_code == 1
        assert "needs is written by update" in result.output

        recipe = _recipe_dir(tmp_path, "bad", "settings:\n  needs: [isolation]\n")
        with pytest.raises(_model.PodApplyError, match="needs"):
            _pod_apply.plan_apply("demo", recipe)
