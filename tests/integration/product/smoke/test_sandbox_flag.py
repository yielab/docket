"""The workflow smoke: --sandbox picks the jail the run is measured under, and refuses a host with none."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.support.git import init_repo
from tests.support.smoke_script import _SMOKE_PATH, _smoke

SUBJECT = "docket.__main__"


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["smoke_workflow.py", *argv])
    return int(_smoke.main())


class _Recorder:
    """Stands in for the docket subprocess: records argv, answers the sandbox probe, stops at the run."""

    def __init__(self, world: Path, backend: str = "landlock") -> None:
        self.world = world
        self.backend = backend
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, repo: Path, env: dict[str, str], *args: str, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        out = (
            json.dumps({"backend": self.backend})
            if args[:3] == ("setup", "sandbox", "status")
            else ""
        )
        if args[:1] == ("init",):
            home = self.world / ".docket"
            home.mkdir(parents=True, exist_ok=True)
            agents = [{"id": f"smoke-{role}"} for role in ("lead", "implementer", "r", "t")]
            (home / "fleet.json").write_text(json.dumps({"agents": agents}), encoding="utf-8")
        if args[:1] == ("run",):
            raise _smoke.SmokeFailure("stopped at the pipeline run")
        return subprocess.CompletedProcess(args, 0, out, "")


def _local_model() -> Any:
    return _smoke._LiveModel("http://127.0.0.1:8081/v1", "local-model")


def _drive_run(monkeypatch: pytest.MonkeyPatch, world: Path, **kwargs: Any) -> _Recorder:
    recorder = _Recorder(world)
    monkeypatch.setattr(_smoke, "_run_cli", recorder)
    with pytest.raises(_smoke.SmokeFailure, match="stopped at the pipeline run"):
        _smoke._run(world, Path.cwd(), _local_model(), _smoke._BASIC_SCENARIO, **kwargs)
    return recorder


def _pipeline_run(world: Path) -> tuple[str, ...]:
    return ("run", "--pod", "smoke", "--pipeline", str(world / "smoke.pipeline.yaml"))


def test_sandbox_on_runs_setup_sandbox_on_after_init_and_before_the_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _drive_run(monkeypatch, tmp_path, sandbox="on")

    calls = recorder.calls
    assert ("setup", "sandbox", "on") in calls and ("setup", "sandbox", "off") not in calls
    assert calls.index(("init", "--from", str(tmp_path / "pod.json"))) < calls.index(
        ("setup", "sandbox", "on")
    )
    assert calls.index(("setup", "sandbox", "on")) < calls.index(_pipeline_run(tmp_path))


def test_sandbox_off_is_the_default_and_runs_setup_sandbox_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    default = _drive_run(monkeypatch, tmp_path / "a")
    explicit = _drive_run(monkeypatch, tmp_path / "b", sandbox="off")

    for recorder in (default, explicit):
        assert ("setup", "sandbox", "off") in recorder.calls
        assert ("setup", "sandbox", "on") not in recorder.calls


@pytest.mark.parametrize("sandbox", ["on", "off"])
def test_the_banner_says_whether_the_jail_is_on(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    sandbox: str,
) -> None:
    _drive_run(monkeypatch, tmp_path, sandbox=sandbox)

    assert f"Sandbox: {sandbox}" in capsys.readouterr().out


def test_sandbox_on_without_a_backend_exits_2_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorder = _Recorder(tmp_path, backend="none")
    monkeypatch.setattr(_smoke, "_run_cli", recorder)
    reached: list[str] = []

    def reach(*_args: Any, **_kwargs: Any) -> None:
        reached.append("model or run")
        raise AssertionError("a refused invocation reached the model")

    monkeypatch.setattr(_smoke, "_discover_live_model", reach)
    monkeypatch.setattr(_smoke, "_run", reach)

    code = _run_main(monkeypatch, "--live-model", "--sandbox", "on")

    err = capsys.readouterr().err
    assert code == 2 and reached == []
    assert recorder.calls == [("setup", "sandbox", "status", "--json")]
    assert len(err.strip().splitlines()) == 1
    assert err.startswith("SMOKE FAIL") and "--sandbox off" in err


def test_sandbox_on_with_a_backend_reaches_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(_smoke, "_run_cli", _Recorder(tmp_path))
    monkeypatch.setattr(_smoke, "_discover_live_model", lambda *_a, **_k: _local_model())
    monkeypatch.setattr(_smoke, "_run", lambda *_a, **kwargs: seen.update(kwargs))

    code = _run_main(
        monkeypatch, "--live-model", "--sandbox", "on", "--workdir", str(tmp_path / "w")
    )

    assert code == 0 and seen["sandbox"] == "on"


def test_default_run_never_asks_the_machine_for_a_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    recorder = _Recorder(tmp_path)
    monkeypatch.setattr(_smoke, "_run_cli", recorder)
    monkeypatch.setattr(_smoke, "_discover_live_model", lambda *_a, **_k: _local_model())
    monkeypatch.setattr(_smoke, "_run", lambda *_a, **kwargs: seen.update(kwargs))

    code = _run_main(monkeypatch, "--live-model", "--workdir", str(tmp_path / "w"))

    assert code == 0 and recorder.calls == [] and seen["sandbox"] == "off"


def test_sandbox_accepts_only_on_or_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        _run_main(monkeypatch, "--live-model", "--sandbox", "maybe")

    assert raised.value.code == 2
    assert "--sandbox" in capsys.readouterr().err


def test_smoke_script_help_names_the_flag() -> None:
    result = subprocess.run(
        [sys.executable, str(_SMOKE_PATH), "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0 and "--sandbox" in result.stdout


def _forbid_any_run(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make a model request, a docket run or a sandbox probe fail the test; the list stays empty."""
    reached: list[str] = []

    def reach(*_args: Any, **_kwargs: Any) -> None:
        reached.append("model, run or probe")
        raise AssertionError("a refused invocation went on")

    for name in ("_discover_live_model", "_run", "_run_cli"):
        monkeypatch.setattr(_smoke, name, reach)
    return reached


def test_a_workdir_inside_a_git_work_tree_exits_2_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    enclosing = tmp_path / "enclosing"
    init_repo(enclosing)
    world = enclosing / "deep" / "world"
    reached = _forbid_any_run(monkeypatch)

    code = _run_main(monkeypatch, "--live-model", "--sandbox", "on", "--workdir", str(world))

    err = capsys.readouterr().err
    assert code == 2 and reached == [] and not world.exists()
    assert len(err.strip().splitlines()) == 1
    assert err.startswith(f"SMOKE FAIL \u2014 {world.resolve()} is inside a git work tree (")
    assert f"({enclosing.resolve()})" in err and "outside any repository" in err


def test_a_workdir_that_is_a_repository_itself_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    subprocess.run(["git", "init", "--quiet", str(world)], check=True)
    reached = _forbid_any_run(monkeypatch)

    code = _run_main(monkeypatch, "--live-model", "--workdir", str(world))

    assert code == 2 and reached == []
    assert "is inside a git work tree" in capsys.readouterr().err


def test_a_workdir_outside_any_repository_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(_smoke, "_discover_live_model", lambda *_a, **_k: _local_model())
    monkeypatch.setattr(_smoke, "_run", lambda *args, **_kwargs: seen.update(world=args[0]))

    code = _run_main(monkeypatch, "--live-model", "--workdir", str(tmp_path / "plain" / "w"))

    assert code == 0 and seen["world"] == (tmp_path / "plain" / "w").resolve()


def test_the_default_temporary_world_is_not_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_smoke, "_enclosing_work_tree", lambda _path: pytest.fail("checked"))
    monkeypatch.setattr(_smoke, "_discover_live_model", lambda *_a, **_k: _local_model())
    monkeypatch.setattr(_smoke, "_run", lambda *_a, **_k: None)

    assert _run_main(monkeypatch, "--live-model") == 0
