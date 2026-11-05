"""The pod's search provider as the plan of record sees it: `search` in the pod report, the
provider switched by applying a directory, and the key kept out of every report and file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod
from typer.testing import CliRunner

import docket.kernel.templates as _templates
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.hops.application import report as _pod_report
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.kernel.service import ServiceConfig
from docket.teams import services as _services
from docket.teams.apply import plan as _plan
from docket.teams.apply import search_probe as _probe

SUBJECT = "docket.teams.apply.search_state"

_RECIPE = _templates.RECIPES_DIR / "web-research"
_KEY = "BSA-test-key-0123456789abcdef"
_BRAVE_SECRET_FIX = "docket setup secret set brave-search --stdin"
_runner = CliRunner()


@pytest.fixture(autouse=True)
def _searxng_answers_on_demand(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No test asks the machine's port 8888; a SearXNG document answers, any other probe is recorded."""
    asked: list[str] = []

    def answers(config: ServiceConfig) -> bool:
        asked.append(config.baseUrl)
        return config.baseUrl == _services.SEARXNG_URL

    monkeypatch.setattr(_probe, "service_answers", answers)
    return asked


def _declare(project: str, source: Path) -> None:
    folder = _services.pod_services_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "search.yaml").write_bytes(source.read_bytes())


def _searxng_doc() -> Path:
    return _RECIPE / "services" / "search.yaml"


def _brave_doc() -> Path:
    return _RECIPE / "brave" / "services" / "search.yaml"


def _search(project: str = "demo") -> dict[str, Any]:
    search: dict[str, Any] = _pod_report.pod_report(project)["search"]
    return search


def _store_key() -> None:
    _secrets.store_secret("brave-search", _KEY)


def test_a_pod_with_no_search_service_reports_none_and_the_searxng_command(tmp_path: Path) -> None:
    """No `search` service: provider none, not ready, the fix is the default provider's command."""
    with _seed_fixture_pod(tmp_path, "demo"):
        search = _search()

    assert (search["provider"], search["ready"]) == ("none", False)
    assert search["fix"] == "docket setup search searxng --pod demo"
    assert "no search service" in search["reason"]


def test_the_options_list_each_provider_with_its_one_command_and_the_secret_it_needs(
    tmp_path: Path,
) -> None:
    """Tack renders these: SearXNG needs no secret, Brave names the stored secret."""
    with _seed_fixture_pod(tmp_path, "demo"):
        options = _search()["options"]

    assert options == [
        {
            "provider": "searxng",
            "command": "docket setup search searxng --pod demo",
            "secret": "",
        },
        {
            "provider": "brave",
            "command": "docket setup search brave --pod demo",
            "secret": "brave-search",
        },
    ]


def test_a_pod_on_the_shipped_searxng_document_reports_searxng_ready(tmp_path: Path) -> None:
    """The base URL `setup search searxng` writes is the provider; the stub answers, so it is ready."""
    with _seed_fixture_pod(tmp_path, "demo"):
        _declare("demo", _searxng_doc())

        search = _search()

    assert (search["provider"], search["ready"], search["fix"]) == ("searxng", True, "")


def test_a_searxng_that_does_not_answer_is_not_ready_and_names_its_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container is not running: provider searxng, not ready, the command that prints the docker line."""
    monkeypatch.setattr(_probe, "service_answers", lambda config: False)
    with _seed_fixture_pod(tmp_path, "demo"):
        _declare("demo", _searxng_doc())

        search = _search()

    assert (search["provider"], search["ready"]) == ("searxng", False)
    assert search["fix"] == "docket setup search searxng --pod demo"
    assert _services.SEARXNG_URL in search["reason"]


def test_any_other_declared_search_service_is_custom(tmp_path: Path) -> None:
    """A search service on another base URL is `custom`; its fix is to look at the services."""
    with _seed_fixture_pod(tmp_path, "demo"):
        folder = _services.pod_services_dir("demo")
        folder.mkdir(parents=True)
        (folder / "search.yaml").write_text(
            "kind: service\nname: search\nbaseUrl: http://127.0.0.1:9999\nhosts: [127.0.0.1]\n",
            encoding="utf-8",
        )

        search = _search()

    assert (search["provider"], search["ready"]) == ("custom", False)
    assert search["fix"] == "docket setup service list"


def test_brave_with_its_secret_stored_is_ready_and_no_call_goes_to_brave(
    tmp_path: Path, _searxng_answers_on_demand: list[str]
) -> None:
    """Readiness is `resolve_auth`: the probe, which would spend the operator's quota, never runs."""
    with _seed_fixture_pod(tmp_path, "demo"):
        _declare("demo", _brave_doc())
        _store_key()

        search = _search()

    assert (search["provider"], search["ready"], search["fix"]) == ("brave", True, "")
    assert _searxng_answers_on_demand == []


def test_brave_without_its_secret_is_not_ready_and_the_fix_is_the_command_to_run_here(
    tmp_path: Path, _searxng_answers_on_demand: list[str]
) -> None:
    """The key is never sent over HTTP: the report names the machine-side command and nothing else."""
    with _seed_fixture_pod(tmp_path, "demo"):
        _declare("demo", _brave_doc())

        search = _search()

    assert (search["provider"], search["ready"]) == ("brave", False)
    assert search["fix"] == _BRAVE_SECRET_FIX
    assert "brave-search" in search["reason"]
    assert _searxng_answers_on_demand == []


def test_applying_a_directory_with_the_other_document_switches_the_provider(
    tmp_path: Path,
) -> None:
    """`apply_directory` replaces the pod's `services/search.yaml` by bytes; nothing else changes."""
    brave_dir = tmp_path / "brave-dir"
    (brave_dir / "services").mkdir(parents=True)
    (brave_dir / "services" / "search.yaml").write_bytes(_brave_doc().read_bytes())
    searxng_dir = tmp_path / "searxng-dir"
    (searxng_dir / "services").mkdir(parents=True)
    (searxng_dir / "services" / "search.yaml").write_bytes(_searxng_doc().read_bytes())
    with _seed_fixture_pod(tmp_path, "demo"):
        _declare("demo", _searxng_doc())
        assert _search()["provider"] == "searxng"
        _store_key()

        to_brave = _plan.apply_directory(
            "demo", brave_dir, tmp_path, accept=None, dry_run=False, channel="test"
        )
        on_brave = _search()
        names_after_brave = sorted(p.name for p in _services.pod_services_dir("demo").iterdir())
        to_searxng = _plan.apply_directory(
            "demo", searxng_dir, tmp_path, accept=None, dry_run=False, channel="test"
        )
        back = _search()

    assert (to_brave.status, to_searxng.status) == ("applied", "applied")
    assert [(i.kind, i.name, i.action) for i in to_brave.items] == [
        ("service", "search", "replace")
    ]
    assert (on_brave["provider"], on_brave["ready"]) == ("brave", True)
    assert names_after_brave == ["search.yaml"]
    assert (back["provider"], back["ready"]) == ("searxng", True)


def _search_line(project: str = "demo") -> str:
    result = _runner.invoke(app, ["pod", "show", "--pod", project])
    return next(
        ln.strip()
        for ln in result.output.splitlines()
        if ln.strip().startswith("needs search-host")
    )


def test_the_need_line_names_the_provider_it_is_met_by(tmp_path: Path) -> None:
    """`ready (searxng at host:port)` and `ready (brave)`: the same function the report uses."""
    with _seed_fixture_pod(tmp_path, "demo"):
        assert (
            _runner.invoke(app, ["pod", "update", "web-research", "--pod", "demo"]).exit_code == 0
        )
        on_searxng = _search_line()
        _declare("demo", _brave_doc())
        _store_key()
        on_brave = _search_line()

    assert on_searxng == "needs search-host: ready (searxng at 127.0.0.1:8888)"
    assert on_brave == "needs search-host: ready (brave)"


def test_the_brave_need_line_without_the_key_names_the_secret_command(tmp_path: Path) -> None:
    """Not ready: the line says which secret is missing and the one command to store it."""
    with _seed_fixture_pod(tmp_path, "demo"):
        assert (
            _runner.invoke(app, ["pod", "update", "web-research", "--pod", "demo"]).exit_code == 0
        )
        _declare("demo", _brave_doc())

        line = _search_line()

    assert line == (
        "needs search-host: the Brave Search key is not stored: no secret named 'brave-search' "
        f"-> {_BRAVE_SECRET_FIX}"
    )


def test_no_report_and_no_file_but_the_secret_store_holds_the_key(tmp_path: Path) -> None:
    """The report, `pod show --json`, the service document, the audit log: the key is in none of them."""
    with _seed_fixture_pod(tmp_path, "demo"):
        code = _runner.invoke(
            app, ["setup", "search", "brave", "--pod", "demo", "--stdin"], input=_KEY
        )
        assert code.exit_code == 0, code.output
        shown = _runner.invoke(app, ["pod", "show", "--pod", "demo", "--json"])
        plain = _runner.invoke(app, ["pod", "show", "--pod", "demo"])
        report = json.dumps(_pod_report.pod_report("demo"))
        audit = _audit.read_audit_text() or ""
        home = current_home().root
        others = [
            p.read_text(encoding="utf-8", errors="replace")
            for p in home.rglob("*")
            if p.is_file() and p != current_home().secrets_file
        ]

        assert _search()["ready"] is True
        stored = _secrets.secret_value("brave-search")

    assert stored == _KEY
    for text in (code.output, shown.output, plain.output, report, audit, *others):
        assert _KEY not in text
