"""`docket setup --fix` — system-wide health checks + JSON health probe.

Calls `run_check()` in-process with `DOCKET_HOME`/`FLEET_FILE`
monkeypatched to a temp seed. stdout is captured to assert on the human
report; the return value is the process exit code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from docket.interfaces.cli.commands import setup_check as _setup_check
from docket.interfaces.cli.commands import setup_check_providers as _setup_check_providers
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store

SUBJECT = "docket.interfaces.cli.commands.setup_check_providers"


@contextmanager
def _point_config_at(
    home: Path,
) -> Iterator[None]:
    """Repoint the already-imported config module at a temp DOCKET_HOME."""
    with use_home(Home(home)):
        yield


class TestProviderCatalog:
    """A malformed global provider document (docket-providers.json) is named, not
    silently skipped -- model-profiles.spec.md, "Provider catalog" requirement 7."""

    def test_no_file_is_healthy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with _point_config_at(tmp_path / ".docket"):
            assert _setup_check_providers._check_provider_catalog() == 0

    def test_broken_auth_type_is_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / ".docket"
        with _point_config_at(home):
            home.mkdir(parents=True, exist_ok=True)
            _store.write_json(
                current_home().providers_file,
                {
                    "providers": {
                        "broken": {
                            "name": "broken",
                            "baseUrl": "https://example.com/v1",
                            "auth": {"type": "oauth"},
                        }
                    }
                },
            )
            issues = _setup_check_providers._check_provider_catalog()
            out = capsys.readouterr().out
            assert issues == 1
            assert str(current_home().providers_file) in out
            assert "auth.type" in out

            json_issues, problems = _setup_check._check_json_provider_catalog()
            assert json_issues == 1
            assert problems == [{"name": "broken", "reason": problems[0]["reason"]}]
            assert "auth.type" in problems[0]["reason"]
