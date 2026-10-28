"""A fresh home after ``docket init`` holds authored configuration beside state, and nothing else.

The whole product runs for real as ``python -m docket`` subprocesses over a real git repo; only
the model is faked.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support.e2e import World
from tests.support.model_server import FakeModel

PIPELINE = """name: layout
steps:
  - implement: implementer
"""


def test_a_fresh_home_after_init_has_only_config_and_state(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    w = world(fake_model(script={}))
    w.make_pod(PIPELINE)

    assert sorted(p.name for p in w.home.iterdir()) == ["config", "state"]
    assert (w.home / "state" / "workspaces" / "projects").is_dir()
    assert (w.home / "state" / "fleet.json").is_file()
    assert w.docket("status").code == 0
