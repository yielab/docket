"""``docket setup search brave``: the key from stdin into the secret store, the pod's `search`
service document for Brave, and the key nowhere else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import build_pod
from typer.testing import CliRunner

import docket.kernel.templates as _templates
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.teams import pod
from docket.teams import services as _services

SUBJECT = "docket.interfaces.cli.commands.setup_search"

_runner = CliRunner()
_KEY = "BSA-test-key-0123456789abcdef"
_BRAVE = _templates.RECIPES_DIR / "web-research" / "brave" / "services" / "search.yaml"
_SEARXNG = _templates.RECIPES_DIR / "web-research" / "services" / "search.yaml"

pod_home = _support_pods.pod_home


@pytest.fixture(autouse=True)
def _a_pod(pod_home: Path) -> None:
    build_pod("shop", pod.DEFAULT_POD_ROLES, codebase="/src/shop")


def _brave(*args: str, key: str | None = _KEY) -> tuple[int, str]:
    result = _runner.invoke(app, ["setup", "search", "brave", *args], input=key)
    return result.exit_code, result.output


def _searxng(*args: str) -> tuple[int, str]:
    result = _runner.invoke(app, ["setup", "search", "searxng", *args])
    return result.exit_code, result.output


def _stored() -> str | None:
    return _secrets.secret_value("brave-search")


def _search_document(project: str = "shop") -> Path:
    return _services.pod_services_dir(project) / "search.yaml"


def test_it_stores_the_key_and_writes_the_pods_search_service() -> None:
    """The key comes from stdin, lands in the secret `brave-search`, the pod's document is Brave's."""
    code, out = _brave("--pod", "shop", "--stdin")

    assert code == 0, out
    assert _stored() == _KEY
    assert _search_document().read_bytes() == _BRAVE.read_bytes()
    assert _KEY not in out


def test_the_service_it_writes_is_a_declared_read_search_with_the_key_as_a_reference() -> None:
    """Host pinned to Brave, the header carries the secret reference, the call resolves the stored key."""
    assert _brave("--pod", "shop", "--stdin")[0] == 0

    (service,) = [s for s in _services.load_services("shop") if s.name == "search"]
    headers, values = _services.resolve_auth(service)

    assert service.baseUrl == "https://api.search.brave.com/res/v1/web"
    assert service.hosts == ["api.search.brave.com"]
    assert service.auth is not None and service.auth.value == "${secret:brave-search}"
    assert headers == {"X-Subscription-Token": _KEY} and values == (_KEY,)
    (operation,) = service.operations
    assert (operation.method, operation.path, str(operation.access)) == ("GET", "/search", "read")
    assert [p.name for p in operation.params] == ["q", "count"]
    assert "fetch" in operation.description
    assert _KEY not in _search_document().read_text(encoding="utf-8")


def test_a_key_given_as_an_argument_is_refused_and_never_echoed() -> None:
    """Exit 2 as `setup secret set`: nothing is stored, nothing written, the value is not repeated."""
    code, out = _brave("--pod", "shop", _KEY, key=None)

    assert code == 2
    assert _KEY not in out
    assert _stored() is None and not _search_document().exists()


def test_without_a_terminal_and_without_stdin_it_exits_1_and_writes_nothing() -> None:
    """No hidden prompt is possible off a TTY: the message says to pipe the key."""
    code, out = _brave("--pod", "shop", key=None)

    assert code == 1
    assert "--stdin" in out
    assert _stored() is None and not _search_document().exists()


def test_an_empty_key_exits_1_and_writes_nothing() -> None:
    """A blank stdin stores nothing and writes no document."""
    code, out = _brave("--pod", "shop", "--stdin", key="  \n")

    assert code == 1
    assert "empty" in out.lower()
    assert _stored() is None and not _search_document().exists()


def test_a_pod_that_does_not_exist_stores_nothing() -> None:
    """The pod is checked before the key is stored."""
    code, out = _brave("--pod", "ghost", "--stdin")

    assert code == 1
    assert "No pod named 'ghost'" in out
    assert _stored() is None and not _search_document("ghost").exists()


def test_an_operator_service_named_search_refuses_before_the_key_is_stored() -> None:
    """A pod service never shadows the operator's: exit 1, no secret, no document."""
    operator = Path(current_home().services_file)
    operator.parent.mkdir(parents=True, exist_ok=True)
    operator.write_text(
        json.dumps({"services": [{"name": "search", "baseUrl": "https://api.example.com"}]}),
        encoding="utf-8",
    )

    code, out = _brave("--pod", "shop", "--stdin")

    assert code == 1
    assert "operator service" in out
    assert _stored() is None and not _search_document().exists()


def test_brave_and_searxng_replace_each_other_in_the_same_file_and_the_key_stays() -> None:
    """One service named `search` per pod, whichever provider was set last."""
    assert _searxng("--pod", "shop")[0] == 0
    assert _search_document().read_bytes() == _SEARXNG.read_bytes()

    assert _brave("--pod", "shop", "--stdin")[0] == 0
    assert _search_document().read_bytes() == _BRAVE.read_bytes()
    assert [p.name for p in _search_document().parent.iterdir()] == ["search.yaml"]

    assert _searxng("--pod", "shop")[0] == 0
    assert _search_document().read_bytes() == _SEARXNG.read_bytes()
    assert _stored() == _KEY


def test_a_second_run_reports_the_document_unchanged() -> None:
    """Idempotent: the same bytes stay, and the output says so."""
    _, first = _brave("--pod", "shop", "--stdin")
    document = _search_document().read_bytes()

    code, second = _brave("--pod", "shop", "--stdin")

    assert code == 0, second
    assert "unchanged" in second and "unchanged" not in first
    assert _search_document().read_bytes() == document


def test_the_audit_names_the_pod_and_provider_never_the_key() -> None:
    """`search.setup` carries pod and provider; the stored key appears in no audit line."""
    assert _brave("--pod", "shop", "--stdin")[0] == 0

    entries = [e for e in _audit.read_audit() if e.get("action") == "search.setup"]

    assert entries and "brave" in str(entries[-1]) and "shop" in str(entries[-1])
    assert _KEY not in (_audit.read_audit_text() or "")
