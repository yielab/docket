"""A recipe says what its work still needs when it is applied, from `init` and from `pod update`.

The block is informational: it comes from the readers the pod report uses
(``effective_fetch_domains``, ``jail_enforces``) and never writes a setting.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.cli import pod_cli as _pod_cli
from tests.support.loopback import recording_service
from tests.support.pods import seed_empty_home as _seed_empty_home
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod
from typer.testing import CliRunner

import docket.kernel.templates as _templates
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.kernel.service import ServiceConfig
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings
from docket.teams import services as _services
from docket.teams.apply import model as _model
from docket.teams.apply import needs as _needs
from docket.teams.apply import plan as _pod_apply

SUBJECT = "docket.teams.apply.needs"

RECIPES_DIR = _templates.RECIPES_DIR
runner = CliRunner()

FETCH_NOT_READY = "needs fetch-hosts: the researchers cannot read the web -> docket pod set fetchDomains <host> --pod demo"
SEARCH_FIX = "docket setup search searxng --pod demo"
SEARCH_NOT_READY = (
    "needs search-host: no search service: SearXNG is free and runs in Docker, or use a Brave "
    f"Search API key (see the recipe README) -> {SEARCH_FIX}"
)
SEARCH_NOT_ANSWERING = f"needs search-host: the search service 'search' does not answer at http://127.0.0.1:8888 -> {SEARCH_FIX}"
ISOLATION_OFF = "needs isolation: PDFs, and the web on a folder team, are not read: isolation is off -> docket setup sandbox on"
NO_BACKEND = "needs isolation: PDFs, and the web on a folder team, are not read: no sandbox backend -> docket setup sandbox backend docker"


def _needs_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("needs ")]


def _init_web_research(tmp_path: Path) -> tuple[int, str]:
    code = tmp_path / "code"
    code.mkdir()
    result = runner.invoke(app, ["init", "demo", str(code), "--recipe", "web-research"])
    return result.exit_code, result.output


def _declare_search(project: str, base_url: str, name: str = "search") -> None:
    """Write a pod-scoped search service document that points at *base_url*."""
    folder = _services.pod_services_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "search.yaml").write_text(
        f"kind: service\nname: {name}\nbaseUrl: {base_url}\nhosts: [127.0.0.1]\n"
        "operations:\n  - name: search\n    method: GET\n    path: /search\n",
        encoding="utf-8",
    )


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def _search_only_recipe(tmp_path: Path) -> Path:
    """A directory that asks for `search-host` and declares no service."""
    return _recipe_dir(tmp_path, "searchless", "needs: [search-host]\n")


@pytest.fixture(autouse=True)
def _port_8888_is_not_the_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped service names this machine's port 8888: no test asks it. A stub answers for itself."""
    real = _needs.service_answers

    def guarded(config: ServiceConfig) -> bool:
        return False if config.baseUrl == "http://127.0.0.1:8888" else real(config)

    monkeypatch.setattr(_needs, "service_answers", guarded)


@pytest.fixture
def no_backend(bind_launcher: Callable[..., Launcher]) -> None:
    bind_launcher(landlock=False, seatbelt=False, docker=False)


def test_init_on_a_fresh_home_lists_three_not_ready_lines_and_writes_no_setting(
    tmp_path: Path, no_backend: None
) -> None:
    """Isolation off, no fetchDomains and nothing answering the shipped search: one command each."""
    code, output = _init_web_research(tmp_path)

    assert code == 0, output
    assert _needs_lines(output) == [FETCH_NOT_READY, SEARCH_NOT_ANSWERING, ISOLATION_OFF]
    assert _fleet.get_isolation_state() == "off (default)"
    assert _pod_settings.effective_fetch_domains("demo") == ()


def test_init_reports_isolation_after_it_turns_isolation_on_where_a_backend_exists(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """Init records isolation on when a backend is detected, so the block must not say it is off."""
    bind_launcher(landlock=True)
    code, output = _init_web_research(tmp_path)

    assert code == 0, output
    assert _needs_lines(output) == [FETCH_NOT_READY, SEARCH_NOT_ANSWERING, "needs isolation: ready"]


def test_the_block_prints_once_per_apply(tmp_path: Path, no_backend: None) -> None:
    """One function prints the block: a single `needs fetch-hosts` line per init."""
    _, output = _init_web_research(tmp_path)

    assert output.count("needs fetch-hosts") == 1


def test_pod_update_prints_the_same_block(tmp_path: Path, no_backend: None) -> None:
    """The `pod update` path reports the same three lines after its plan."""
    with _seed_fixture_pod(tmp_path, "demo"):
        result = _pod_cli("update", "web-research", "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _needs_lines(result.output) == [FETCH_NOT_READY, SEARCH_NOT_ANSWERING, ISOLATION_OFF]


def test_everything_ready_after_hosts_isolation_and_an_answering_search_service(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """A fetch list, a jail that runs and a search service that answers report all three ready."""
    bind_launcher(landlock=True)
    with _seed_fixture_pod(tmp_path, "demo"), recording_service() as (base, seen):
        assert _pod_cli("set", "fetchDomains", "*.wikipedia.org", "--pod", "demo").exit_code == 0
        _fleet.apply_workspace_isolation()
        assert _pod_cli("update", "web-research", "--pod", "demo").exit_code == 0
        _declare_search("demo", base)

        result = runner.invoke(app, ["pod", "show", "--pod", "demo"])

        assert _needs_lines(result.output) == [
            "needs fetch-hosts: ready (1 host)",
            "needs search-host: ready",
            "needs isolation: ready",
        ]
        assert seen and {(r["method"], r["path"]) for r in seen} == {("GET", "/")}
        assert all("authorization" not in r["headers"] for r in seen)


def test_a_search_site_among_the_fetch_hosts_does_not_meet_the_need(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """DuckDuckGo allowed to `fetch` is no search service: only the search line is not ready."""
    bind_launcher(landlock=True)
    with _seed_fixture_pod(tmp_path, "demo"):
        assert (
            _pod_cli(
                "set", "fetchDomains", "html.duckduckgo.com,*.wikipedia.org", "--pod", "demo"
            ).exit_code
            == 0
        )
        _fleet.apply_workspace_isolation()

        result = _pod_cli("update", str(_search_only_recipe(tmp_path)), "--pod", "demo")

        assert _needs_lines(result.output) == [SEARCH_NOT_READY]


def test_open_read_without_the_service_leaves_the_search_need_unmet(
    tmp_path: Path, bind_launcher: Callable[..., Launcher]
) -> None:
    """A folder pod under the jail reads any public host; that is not a search: both options named."""
    bind_launcher(landlock=True)
    with _seed_empty_home(tmp_path):
        _pp.provision_pod("demo", "respond")
        _fleet.set_sandbox_isolation()
        recipe = _recipe_dir(tmp_path, "both", "needs: [fetch-hosts, search-host]\n")

        result = _pod_cli("update", str(recipe), "--pod", "demo")

        assert _needs_lines(result.output) == [
            "needs fetch-hosts: ready (any public host)",
            SEARCH_NOT_READY,
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


def test_a_search_service_that_does_not_answer_is_named_with_its_address_and_never_fails_the_apply(
    tmp_path: Path, no_backend: None
) -> None:
    """A declared service on a closed port: the line says where, points at `setup service list`, exit 0."""
    with _seed_fixture_pod(tmp_path, "demo"):
        base = f"http://127.0.0.1:{_closed_port()}"
        _declare_search("demo", base)

        result = _pod_cli("update", str(_search_only_recipe(tmp_path)), "--pod", "demo")

        assert result.exit_code == 0, result.output
        assert _needs_lines(result.output) == [
            f"needs search-host: the search service 'search' does not answer at {base} "
            "-> docket setup service list"
        ]


def test_a_service_that_answers_with_an_error_status_still_answers(
    tmp_path: Path, no_backend: None
) -> None:
    """Any HTTP status means a server is there: the base URL of an API often answers 404."""
    with _seed_fixture_pod(tmp_path, "demo"), recording_service() as (base, _):
        _declare_search("demo", f"{base}/missing/")

        result = _pod_cli("update", str(_search_only_recipe(tmp_path)), "--pod", "demo")

        assert _needs_lines(result.output) == ["needs search-host: ready"]


def test_a_service_with_a_search_operation_but_another_name_is_not_the_search(
    tmp_path: Path, no_backend: None
) -> None:
    """Only the service named `search` is the pod's search: a site-specific `hn` is not."""
    with _seed_fixture_pod(tmp_path, "demo"), recording_service() as (base, seen):
        _declare_search("demo", base, name="hn")

        result = _pod_cli("update", str(_search_only_recipe(tmp_path)), "--pod", "demo")

        assert _needs_lines(result.output) == [SEARCH_NOT_READY]
        assert seen == []


def test_the_operators_service_named_search_counts_when_it_answers(
    tmp_path: Path, no_backend: None
) -> None:
    """The operator's `services.json` is a scope of the same name: it satisfies the need too."""
    with _seed_fixture_pod(tmp_path, "demo"), recording_service() as (base, _):
        registry = Path(current_home().services_file)
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(
            json.dumps({"services": [{"name": "search", "baseUrl": base, "hosts": ["127.0.0.1"]}]}),
            encoding="utf-8",
        )

        result = _pod_cli("update", str(_search_only_recipe(tmp_path)), "--pod", "demo")

        assert _needs_lines(result.output) == ["needs search-host: ready"]


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
    """The recipe declares `needs:`; its README leads with the search command, not a search site."""
    manifest = (RECIPES_DIR / "web-research" / "pod.yaml").read_text(encoding="utf-8")
    readme = (RECIPES_DIR / "web-research" / "README.md").read_text(encoding="utf-8")

    assert "needs: [fetch-hosts, search-host, isolation]" in manifest
    assert "docket pod set fetchDomains" in readme
    assert "FETCH_ALLOWED_DOMAINS" not in readme
    assert "setup mcp add" not in readme
    assert "docket setup search searxng" in readme
    assert "html.duckduckgo.com" not in readme
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
            "fix": SEARCH_FIX,
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

    assert _needs_lines(result.output) == [FETCH_NOT_READY, SEARCH_NOT_ANSWERING, ISOLATION_OFF]


def test_pod_show_json_recomputes_satisfaction_and_keeps_the_recorded_list(
    tmp_path: Path, no_backend: None
) -> None:
    """A host meets fetch-hosts alone; a search service that answers meets search-host."""
    _init_web_research(tmp_path)
    before = _fleet.meta_get("demo-lead", "needs", "")

    assert _pod_cli("set", "fetchDomains", "html.duckduckgo.com", "--pod", "demo").exit_code == 0

    by_kind = {entry["kind"]: entry for entry in _show_needs()}
    assert (by_kind["fetch-hosts"]["satisfied"], by_kind["fetch-hosts"]["fix"]) == (True, "")
    assert (by_kind["search-host"]["satisfied"], by_kind["search-host"]["fix"]) == (
        False,
        SEARCH_FIX,
    )
    assert by_kind["isolation"]["satisfied"] is False
    with recording_service() as (base, _):
        _declare_search("demo", base)
        by_kind = {entry["kind"]: entry for entry in _show_needs()}
        assert (by_kind["search-host"]["satisfied"], by_kind["search-host"]["fix"]) == (True, "")
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


def test_the_recipe_applies_its_service_and_leaves_the_searxng_asset_alone(
    tmp_path: Path, no_backend: None
) -> None:
    """`init --recipe` copies `services/search.yaml` into the pod and writes nothing for `searxng/`."""
    code, output = _init_web_research(tmp_path)
    assert code == 0, output
    overlay = current_home().pod_config_dir("demo")

    shipped = RECIPES_DIR / "web-research"
    assert (overlay / "services" / "search.yaml").read_bytes() == (
        shipped / "services" / "search.yaml"
    ).read_bytes()
    assert not (overlay / "searxng").exists()
    assert list(overlay.rglob("settings.yml")) == []
    assert (shipped / "searxng" / "settings.yml").is_file()
    again = _pod_cli("update", "web-research", "--pod", "demo")
    assert again.exit_code == 0, again.output


def test_the_shipped_search_service_is_a_read_get_the_researchers_read_the_hits_of() -> None:
    """One `search` service on the loopback; its pipeline steps name the tool, not a search site."""
    shipped = RECIPES_DIR / "web-research"
    service = _services.load_service_document(shipped / "services" / "search.yaml")
    pipeline = (shipped / "pipeline.yaml").read_text(encoding="utf-8")

    assert (service.name, service.baseUrl, service.hosts) == (
        "search",
        "http://127.0.0.1:8888",
        ["127.0.0.1"],
    )
    (operation,) = service.operations
    assert (operation.name, operation.method, operation.path) == ("search", "GET", "/search")
    assert operation.access == "read"
    assert {p.name for p in operation.params} == {"q", "format"}
    assert "format=json" in operation.description and "fetch" in operation.description
    assert pipeline.count("svc__search__search") == 2
    assert "search site" not in pipeline
