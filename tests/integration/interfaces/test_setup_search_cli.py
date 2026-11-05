"""``docket setup search searxng``: the settings file under the home, the pod's ``search`` service
document and the one ``docker run`` line, written again without change."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import pytest
import yaml
from tests.support import pods as _support_pods
from tests.support.pods import build_pod
from typer.testing import CliRunner

import docket.kernel.templates as _templates
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.teams import pod
from docket.teams import services as _services

SUBJECT = "docket.interfaces.cli.commands.setup_search"

_runner = CliRunner()
_SHIPPED = _templates.RECIPES_DIR / "web-research" / "services" / "search.yaml"


pod_home = _support_pods.pod_home


@pytest.fixture(autouse=True)
def _two_pods(pod_home: Path) -> None:
    for project in ("shop", "other"):
        build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


def _search(*args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    result = _runner.invoke(app, ["setup", "search", "searxng", *args], env=env)
    return result.exit_code, result.output


def _settings() -> Path:
    return current_home().config_dir / "searxng" / "settings.yml"


def _service_file(project: str = "shop") -> Path:
    return _services.pod_services_dir(project) / "search.yaml"


def _docker_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("docker run")]


def test_it_writes_the_settings_the_service_and_prints_one_docker_line() -> None:
    """The settings turn JSON on and the limiter off, the service is the shipped one, the line names the path."""
    code, out = _search("--pod", "shop")

    assert code == 0, out
    settings = yaml.safe_load(_settings().read_text(encoding="utf-8"))
    assert settings["server"]["limiter"] is False
    assert "json" in settings["search"]["formats"]
    assert re.fullmatch(r"[0-9a-f]{32}", settings["server"]["secret_key"])
    assert _service_file().read_bytes() == _SHIPPED.read_bytes()
    (line,) = _docker_lines(out)
    assert str(_settings().parent) in line
    assert "127.0.0.1:8888:8080" in line and "searxng/searxng" in line


def test_the_service_it_writes_is_a_declared_read_search_on_the_loopback() -> None:
    """The pod resolves a service `search` with one read operation on 127.0.0.1:8888."""
    assert _search("--pod", "shop")[0] == 0

    (service,) = [s for s in _services.load_services("shop") if s.name == "search"]

    assert service.baseUrl == "http://127.0.0.1:8888"
    assert service.hosts == ["127.0.0.1"]
    (operation,) = service.operations
    assert (operation.method, operation.path, str(operation.access)) == ("GET", "/search", "read")
    assert "fetch" in operation.description


def test_a_second_run_changes_nothing_and_prints_the_line_again() -> None:
    """The settings (and so the key) and the service document are kept byte for byte."""
    _, first = _search("--pod", "shop")
    settings = _settings().read_bytes()
    service = _service_file().read_bytes()

    code, second = _search("--pod", "shop")

    assert code == 0, second
    assert _settings().read_bytes() == settings
    assert _service_file().read_bytes() == service
    assert _docker_lines(second) == _docker_lines(first)


def test_the_settings_are_shared_between_pods_and_each_pod_gets_its_service() -> None:
    """One settings file for the machine's container; one service document per pod."""
    assert _search("--pod", "shop")[0] == 0
    key = _settings().read_bytes()

    assert _search("--pod", "other")[0] == 0

    assert _settings().read_bytes() == key
    assert _service_file("other").read_bytes() == _SHIPPED.read_bytes()


def test_the_pod_comes_from_the_environment_when_no_option_is_given() -> None:
    """DOCKET_POD names the pod the service lands in."""
    code, out = _search(env={"DOCKET_POD": "other"})

    assert code == 0, out
    assert _service_file("other").is_file() and not _service_file("shop").exists()


def test_a_different_search_document_is_replaced_by_the_shipped_one() -> None:
    """The command sets the pod's search up as SearXNG, whatever the file held."""
    _service_file().parent.mkdir(parents=True)
    _service_file().write_text(
        "kind: service\nname: search\nbaseUrl: http://127.0.0.1:9999\nhosts: [127.0.0.1]\n",
        encoding="utf-8",
    )

    code, out = _search("--pod", "shop")

    assert code == 0, out
    assert _service_file().read_bytes() == _SHIPPED.read_bytes()


def test_the_settings_file_is_readable_by_the_container() -> None:
    """The container user is not the host user: the file is world-readable, never executable."""
    assert _search("--pod", "shop")[0] == 0

    assert stat.S_IMODE(_settings().stat().st_mode) == 0o644


def test_an_operator_service_named_search_refuses_and_writes_nothing() -> None:
    """A pod's service never shadows the operator's: exit 1, no settings, no document."""
    operator = Path(current_home().services_file)
    operator.parent.mkdir(parents=True, exist_ok=True)
    operator.write_text(
        json.dumps({"services": [{"name": "search", "baseUrl": "https://api.example.com"}]}),
        encoding="utf-8",
    )

    code, out = _search("--pod", "shop")

    assert code == 1
    assert "search" in out and "operator service" in out
    assert not _settings().exists() and not _service_file().exists()


def test_no_pod_to_choose_exits_1_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside every registered codebase, with no option and no environment, no pod is chosen."""
    monkeypatch.delenv("DOCKET_POD", raising=False)
    monkeypatch.chdir(tmp_path)

    code, out = _search()

    assert code == 1
    assert "--pod" in out
    assert not _settings().exists()


def test_a_pod_that_does_not_exist_exits_1_and_writes_nothing() -> None:
    """A name that is no pod is refused before any file is written."""
    code, out = _search("--pod", "ghost")

    assert code == 1
    assert "No pod named 'ghost'" in out
    assert not _settings().exists() and not _service_file("ghost").exists()
