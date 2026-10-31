"""`docket pod update` on a `workdir` pod: a folder pod never prepares, so it asks for no install.

See pod-blueprints.spec.md "Pod manifests: apply" requirement 13.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.cli import pod_cli as _pod_cli

from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.teams.apply.review"


def _workdir_pod_repo(tmp_path: Path, pod_yaml: str) -> Path:
    """A `workdir` pod `ops` and a repository whose root has a lockfile; returns its `.docket/`."""
    _pod.build_pod_from_blueprint("ops", "operate", location=str(tmp_path / "work"))
    config = tmp_path / "repo" / ".docket"
    config.mkdir(parents=True)
    (tmp_path / "repo" / "package-lock.json").write_text("{}")
    (config / "pod.yaml").write_text(f"kind: pod\nname: ops\n{pod_yaml}", encoding="utf-8")
    return config


def test_pod_update_on_a_workdir_pod_lists_no_prepare_to_review(tmp_path: Path) -> None:
    """A folder pod never prepares, so the repository's lockfile asks nothing of the operator."""
    with use_home(Home(tmp_path / ".docket")):
        config = _workdir_pod_repo(tmp_path, "")
        result = _pod_cli("update", str(config), "--pod", "ops", "--json")
        assert result.exit_code == 0, result.output
        assert "needs_review" not in result.output


def test_pod_update_on_a_workdir_pod_refuses_a_prepare_command(tmp_path: Path) -> None:
    with use_home(Home(tmp_path / ".docket")):
        config = _workdir_pod_repo(tmp_path, "prepare: npm ci\n")
        result = _pod_cli("update", str(config), "--pod", "ops", "--json")
        assert result.exit_code != 0
        assert (
            "prepare: pod 'ops' works in a folder (workspaceKind workdir); "
            "a prepare command applies only to a pod with a codebase"
        ) in " ".join(result.output.split())
        assert _pod_settings.PodSettings.load_for("ops").prepare == ""
