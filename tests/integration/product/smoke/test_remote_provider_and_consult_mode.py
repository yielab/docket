"""The workflow smoke: a remote provider needs consent, the key never lands on disk, consultMode."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.support.smoke_script import (
    _SMOKE_PATH,
    CANARY_KEY,
    REMOTE_KEY_ENV,
    _smoke,
)

SUBJECT = "docket.__main__"

CANARY = CANARY_KEY
KEY_ENV = REMOTE_KEY_ENV


def _main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["smoke_workflow.py", *argv])
    return int(_smoke.main())


def _no_run(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Make any attempt to reach a model or start a run fail the test loudly."""
    started: list[tuple[Any, ...]] = []

    def run(*args: Any, **_kwargs: Any) -> None:
        started.append(args)

    def discover(*args: Any, **_kwargs: Any) -> None:
        started.append(args)
        raise AssertionError("a refused invocation reached the model")

    monkeypatch.setattr(_smoke, "_run", run)
    monkeypatch.setattr(_smoke, "_discover_live_model", discover)
    return started


def test_remote_provider_without_allow_remote_exits_2_before_any_request(
    operator_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started = _no_run(monkeypatch)

    code = _main(monkeypatch, "--live-model", "--provider", "anthropic", "--model", "m")

    err = capsys.readouterr().err
    assert code == 2 and started == []
    assert len(err.strip().splitlines()) == 1 and "--allow-remote" in err
    assert CANARY not in err


@pytest.mark.parametrize(
    "extra",
    [
        ["--endpoint", "http://127.0.0.1:8081/v1"],
        [],
    ],
    ids=["with-endpoint", "without-model"],
)
def test_remote_provider_refuses_an_ambiguous_invocation(
    operator_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    started = _no_run(monkeypatch)
    argv = ["--live-model", "--provider", "anthropic", "--allow-remote", *extra]
    if extra:
        argv += ["--model", "m"]

    code = _main(monkeypatch, *argv)

    assert code == 2 and started == []
    assert "SMOKE FAIL" in capsys.readouterr().err


def test_remote_provider_must_be_a_supported_one(
    operator_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started = _no_run(monkeypatch)

    code = _main(
        monkeypatch, "--live-model", "--provider", "nowhere", "--allow-remote", "--model", "m"
    )

    assert code == 2 and started == []
    assert "anthropic" in capsys.readouterr().err


def test_remote_provider_without_a_key_exits_2_and_names_where_to_put_it(
    keyless_operator_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = _no_run(monkeypatch)

    code = _main(
        monkeypatch, "--live-model", "--provider", "anthropic", "--allow-remote", "--model", "m"
    )

    assert code == 2 and started == []
    assert KEY_ENV in capsys.readouterr().err


def test_default_run_stays_loopback_and_parks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def discover(endpoint: str, model: str | None) -> Any:
        seen["endpoint"] = endpoint
        return _smoke._LiveModel("http://127.0.0.1:8081/v1", "local-model")

    def run(world: Path, repo: Path, live: Any, scenario: str, *rest: Any, **_kwargs: Any) -> None:
        seen.update(live=live, scenario=scenario, rest=rest)

    monkeypatch.setattr(_smoke, "_discover_live_model", discover)
    monkeypatch.setattr(_smoke, "_run", run)

    assert _main(monkeypatch, "--live-model", "--workdir", str(tmp_path / "w")) == 0

    assert seen["endpoint"] == "http://127.0.0.1:8081/v1"
    assert seen["live"].remote is False
    assert "decide" not in map(str, seen["rest"])
    with pytest.raises(_smoke.SmokeFailure, match="loopback"):
        _smoke._loopback_endpoint("https://api.anthropic.com/v1")


class _Recorder:
    """Stands in for the docket subprocess: records argv and env, stops at the pipeline run."""

    def __init__(self, world: Path) -> None:
        self.world = world
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(
        self, repo: Path, env: dict[str, str], *args: str, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        self.envs.append(dict(env))
        if args[:1] == ("init",):
            home = self.world / ".docket"
            home.mkdir(parents=True, exist_ok=True)
            agents = [{"id": f"smoke-{role}"} for role in ("lead", "implementer", "reviewer")]
            (home / "state").mkdir(parents=True, exist_ok=True)
            (home / "state" / "fleet.json").write_text(
                json.dumps({"agents": agents}), encoding="utf-8"
            )
        if args[:1] == ("run",):
            raise _smoke.SmokeFailure("stopped at the pipeline run")
        return subprocess.CompletedProcess(args, 0, "", "")


def _drive_run(
    monkeypatch: pytest.MonkeyPatch,
    world: Path,
    live: Any,
    *rest: Any,
    **kwargs: Any,
) -> _Recorder:
    recorder = _Recorder(world)
    monkeypatch.setattr(_smoke, "_run_cli", recorder)
    with pytest.raises(_smoke.SmokeFailure, match="stopped at the pipeline run"):
        _smoke._run(world, Path.cwd(), live, _smoke._BASIC_SCENARIO, *rest, **kwargs)
    return recorder


def _local() -> Any:
    return _smoke._LiveModel("http://127.0.0.1:8081/v1", "local-model")


def test_consult_mode_decide_reaches_pod_set_before_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _drive_run(monkeypatch, tmp_path, _local(), "decide")

    set_call = ("pod", "set", "consultMode", "decide", "--pod", "smoke")
    assert set_call in recorder.calls
    assert recorder.calls.index(set_call) > recorder.calls.index(
        ("init", "--from", str(tmp_path / "pod.json"))
    )
    assert recorder.calls.index(set_call) < recorder.calls.index(
        ("run", "--pod", "smoke", "--pipeline", str(tmp_path / "smoke.pipeline.yaml"))
    )


def test_consult_mode_park_is_the_default_and_runs_no_pod_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    default = _drive_run(monkeypatch, tmp_path / "a", _local())
    park = _drive_run(monkeypatch, tmp_path / "b", _local(), "park")

    for recorder in (default, park):
        assert not any(call[:2] == ("pod", "set") for call in recorder.calls)


def test_local_run_registers_the_loopback_provider_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _drive_run(monkeypatch, tmp_path, _local())

    assert (
        "setup",
        "provider",
        "add",
        "smoke-local",
        "http://127.0.0.1:8081/v1",
        "--model",
        "local-model",
        "--no-preset",
    ) in recorder.calls
    assert "(loopback only)" in capsys.readouterr().out


def test_remote_run_registers_the_builtin_provider_with_the_key_only_in_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _smoke._LiveModel("", "claude-haiku-4-5", provider="anthropic", remote=True)

    recorder = _drive_run(monkeypatch, tmp_path, live, "decide", CANARY)

    assert ("setup", "provider", "add", "anthropic", "--no-preset") in recorder.calls
    assert ("setup", "model", "set", "lead", "anthropic/claude-haiku-4-5") in recorder.calls
    assert all(CANARY not in " ".join(call) for call in recorder.calls)
    assert all(env.get(KEY_ENV) == CANARY for env in recorder.envs)
    out = capsys.readouterr()
    assert "remote: anthropic" in out.out and "(loopback only)" not in out.out
    assert CANARY not in out.out + out.err


def test_a_declared_output_cap_travels_to_the_remote_provider_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live = _smoke._LiveModel(
        "", "claude-haiku-4-5", provider="anthropic", remote=True, max_output_tokens=4096
    )

    recorder = _drive_run(monkeypatch, tmp_path, live, "decide", CANARY)

    assert (
        "setup",
        "provider",
        "add",
        "anthropic",
        "--no-preset",
        "--model",
        "claude-haiku-4-5",
        "--max-tokens",
        "4096",
    ) in recorder.calls


def test_a_named_exporter_is_enabled_at_full_privacy_in_the_world_before_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _drive_run(monkeypatch, tmp_path, _local(), exporters=("langfuse",))

    enable = ("setup", "export", "enable", "langfuse", "--privacy", "full", "--yes")
    assert enable in recorder.calls
    assert recorder.calls.index(enable) < recorder.calls.index(
        ("run", "--pod", "smoke", "--pipeline", str(tmp_path / "smoke.pipeline.yaml"))
    )


def test_main_leaves_no_key_in_a_kept_world(
    operator_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = tmp_path / "kept"

    def run(
        w: Path, repo: Path, live: Any, scenario: str, consult: str, key: str, sandbox: str
    ) -> None:
        assert key == CANARY and live.remote and live.provider == "anthropic"
        (w / ".docket" / "state").mkdir(parents=True, exist_ok=True)
        (w / ".docket" / "state" / "secrets.json").write_text(
            json.dumps({KEY_ENV: key}), encoding="utf-8"
        )
        (w / ".docket" / "state" / "audit.log").write_text(f"auth bearer {key}\n", encoding="utf-8")
        raise _smoke.SmokeFailure(f"the provider rejected {key}")

    monkeypatch.setattr(_smoke, "_run", run)

    code = _main(
        monkeypatch,
        "--live-model",
        "--provider",
        "anthropic",
        "--allow-remote",
        "--model",
        "claude-haiku-4-5",
        "--consult-mode",
        "decide",
        "--workdir",
        str(world),
    )

    assert code == 1
    leaked = [p for p in world.rglob("*") if p.is_file() and CANARY in p.read_text()]
    assert leaked == [] and not (world / ".docket" / "state" / "secrets.json").exists()
    assert (world / ".docket" / "state" / "audit.log").read_text() == "auth bearer [redacted]\n"


def test_smoke_script_help_names_the_new_flags() -> None:
    result = subprocess.run(
        [sys.executable, str(_SMOKE_PATH), "--help"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0
    for flag in ("--consult-mode", "--provider", "--allow-remote"):
        assert flag in result.stdout
