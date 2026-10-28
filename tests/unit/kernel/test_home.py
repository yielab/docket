"""``kernel.home`` -- paths follow the root, and the current Home is set per block and per
context, never per process."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.kernel import templates
from docket.kernel.home import Home, current_home, reset_default, use_home

SUBJECT = "docket.kernel.home"


@pytest.fixture(autouse=True)
def _fresh_default() -> Iterator[None]:
    reset_default()
    yield
    reset_default()


def test_every_unset_path_follows_the_root(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    state = tmp_path / "state"
    assert home.audit_log == state / "audit.log"
    assert home.traces_dir == state / "traces"
    assert home.meta_path("a") == state / "workspaces" / "projects" / "a" / ".docket-meta.json"
    assert home.pod_scratch_dir("p") == state / "workspaces" / "pods" / "p" / ".scratch"


def test_authored_paths_are_under_config_and_runtime_paths_under_state(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    config, state = tmp_path / "config", tmp_path / "state"
    assert home.config_dir == config
    assert home.state_dir == state
    for authored in (
        home.policies_dir,
        home.plugins_dir,
        home.skills_dir,
        home.user_recipes_dir,
        home.model_registry_file,
        home.mcp_servers_file,
        home.pod_config_dir("p"),
    ):
        assert authored.is_relative_to(config)
    for runtime in (home.sessions_dir, home.audit_log, home.escalations_dir, home.secrets_file):
        assert runtime.is_relative_to(state)
    assert home.pod_config_dir("p") == config / "pods" / "p"


def test_an_old_layout_home_is_read_in_place(tmp_path: Path) -> None:
    (tmp_path / "policies").mkdir()
    home = Home(root=tmp_path)
    assert home.policies_dir == tmp_path / "policies"
    assert home.audit_log == tmp_path / "audit.log"
    assert home.pod_config_dir("p") == tmp_path / "workspaces" / "pods" / "p" / "config"


def test_an_override_wins_over_the_root(tmp_path: Path) -> None:
    home = Home(root=tmp_path, traces_dir_override=tmp_path / "elsewhere")
    assert home.traces_dir == tmp_path / "elsewhere"
    assert home.sessions_dir == tmp_path / "state" / "sessions"


def test_skills_scopes_run_repository_pod_operator_shipped(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    repo = tmp_path / "repo"
    scopes = home.scopes("skills", "p", repo)
    assert scopes == [
        repo / ".docket" / "skills",
        tmp_path / "config" / "pods" / "p" / "skills",
        tmp_path / "config" / "skills",
        templates.TEMPLATES_DIR / "skills",
    ]


def test_a_scope_without_a_pod_or_repository_leaves_those_entries_out(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    assert home.scopes("prompts") == [
        tmp_path / "config" / "prompts",
        templates.TEMPLATES_DIR / "prompts",
    ]


@pytest.mark.parametrize("kind", ["roles", "policies", "plugins", "pipelines"])
def test_a_kind_that_grants_or_runs_something_has_no_repository_entry(
    tmp_path: Path, kind: str
) -> None:
    home = Home(root=tmp_path)
    repo = tmp_path / "repo"
    assert not any(repo in scope.parents for scope in home.scopes(kind, "p", repo))


def test_policies_and_plugins_scopes_are_the_pod_then_the_operator(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    assert home.scopes("policies", "p", tmp_path / "repo") == [
        tmp_path / "config" / "pods" / "p" / "policies",
        tmp_path / "config" / "policies",
    ]
    assert home.scopes("plugins") == [tmp_path / "config" / "plugins"]


def test_roles_scopes_are_the_pod_then_the_operator(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    assert home.scopes("roles", "p") == [
        tmp_path / "config" / "pods" / "p" / "roles",
        tmp_path / "config" / "roles",
    ]
    assert home.scopes("roles") == [home.roles_dir]


def test_an_unknown_scope_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Home(root=tmp_path).scopes("recipes")


def test_a_home_is_hashable(tmp_path: Path) -> None:
    assert hash(Home(root=tmp_path)) == hash(Home(root=tmp_path))


def test_retries_per_role_fall_back_to_the_default() -> None:
    home = Home.from_environ({"DISPATCH_RETRIES_DEFAULT": "4", "DISPATCH_RETRIES_LEAD": "0"})
    assert home.dispatch_retries_per_role == {
        "lead": 0,
        "implementer": 4,
        "reviewer": 4,
        "tester": 4,
    }


def test_two_homes_nest_and_restore(tmp_path: Path) -> None:
    a, b = Home(root=tmp_path / "a"), Home(root=tmp_path / "b")
    with use_home(a):
        assert current_home() is a
        with use_home(b):
            assert current_home() is b
        assert current_home() is a
    assert current_home() not in (a, b)


def test_a_thread_sees_the_home_only_through_a_copied_context(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    seen: dict[str, Home] = {}

    def record(key: str) -> None:
        seen[key] = current_home()

    with use_home(home):
        plain = threading.Thread(target=record, args=("plain",))
        ctx = contextvars.copy_context()
        copied = threading.Thread(target=ctx.run, args=(record, "copied"))
        for t in (plain, copied):
            t.start()
            t.join()
    assert seen["copied"] is home
    assert seen["plain"] is not home


def test_the_default_reads_the_environment_once_until_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("docket.kernel.home._DEFAULT", None)

    def check() -> None:
        monkeypatch.setenv("DOCKET_HOME", str(tmp_path / "first"))
        assert current_home().root == tmp_path / "first"
        monkeypatch.setenv("DOCKET_HOME", str(tmp_path / "second"))
        assert current_home().root == tmp_path / "first"
        reset_default()
        assert current_home().root == tmp_path / "second"

    # A fresh context has no use_home() active, which is where the process default shows.
    contextvars.Context().run(check)


def test_the_secrets_files_follow_the_root(tmp_path: Path) -> None:
    home = Home(root=tmp_path)
    assert home.secrets_file == tmp_path / "state" / "secrets.json"
    assert home.secrets_meta_file == tmp_path / "state" / "secrets.meta.json"


def test_a_bare_thread_sees_the_test_home_not_the_users(tmp_path: Path) -> None:
    """A thread started without the test's context falls back to the process default home,
    which must be the test's, or a server thread writes pods into the developer's ~/.docket."""
    seen: list[Path] = []
    thread = threading.Thread(target=lambda: seen.append(current_home().root))
    thread.start()
    thread.join()

    assert seen == [tmp_path / "_autouse_docket_home"]
    assert Path.home() / ".docket" not in seen
