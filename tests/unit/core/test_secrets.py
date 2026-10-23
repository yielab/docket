"""The secrets store keeps its two files in the current Home, read at call time."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from docket.core import secrets as _secrets
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.core.secrets"


def test_the_store_follows_the_current_home(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with use_home(dataclasses.replace(current_home(), root=first)):
        _secrets.save_secrets({"A_KEY": "one"})
        _secrets.touch_meta("A_KEY", "added")
    with use_home(dataclasses.replace(current_home(), root=second)):
        assert _secrets.load_secrets() == {}
        assert _secrets.load_secrets_meta() == {}
        _secrets.save_secrets({"B_KEY": "two"})
    assert (first / "secrets.json").exists() and (first / "secrets.meta.json").exists()
    assert (second / "secrets.json").exists() and not (second / "secrets.meta.json").exists()
    with use_home(dataclasses.replace(current_home(), root=first)):
        assert _secrets.secret_value("A_KEY") == "one"
