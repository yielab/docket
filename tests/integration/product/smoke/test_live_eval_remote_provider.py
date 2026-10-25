"""The live evaluation passes the new smoke flags through and keeps a remote key out of --out."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest
from tests.support.smoke_script import (
    CANARY_KEY,
    REMOTE_KEY_ENV,
)

SUBJECT = "docket.__main__"

_PATH = Path(__file__).resolve().parents[4] / "scripts" / "maint" / "live_eval.py"
_spec = importlib.util.spec_from_file_location("docket_live_eval", _PATH)
assert _spec is not None and _spec.loader is not None
live_eval = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = live_eval
_spec.loader.exec_module(live_eval)

CANARY = CANARY_KEY
KEY_ENV = REMOTE_KEY_ENV

# Stands in for the smoke: it leaves the key everywhere a real run could.
_FAKE_SMOKE = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path

    world = Path(sys.argv[sys.argv.index("--workdir") + 1])
    key = "@KEY@"
    home = world / ".docket"
    (home / "traces" / "smoke").mkdir(parents=True)
    event = {"ts": "2026-01-01T00:00:00Z", "event_type": "hop_finished", "payload": {"ok": True}}
    event["payload"]["leak"] = key
    (home / "traces" / "smoke" / "t.jsonl").write_text(json.dumps(event) + "\\n")
    (home / "secrets.json").write_text(json.dumps({"ANTHROPIC_API_KEY": key}))
    (world / "note.txt").write_text("bearer " + key)
    print("argv", sys.argv[1:])
    print("provider said " + key, file=sys.stderr)
    sys.exit(1)
    """
)


def test_dry_run_prints_both_new_flags_for_every_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = live_eval.main(
        [
            "-n",
            "2",
            "--out",
            str(tmp_path / "out"),
            "--dry-run",
            "--consult-mode",
            "decide",
            "--provider",
            "anthropic",
            "--allow-remote",
            "--model",
            "claude-haiku-4-5",
        ]
    )

    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(lines) == 2
    for line in lines:
        assert "--consult-mode decide" in line
        assert "--provider anthropic --allow-remote" in line
        assert "--model claude-haiku-4-5" in line


def test_default_command_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live_eval.main(["--out", str(tmp_path / "out"), "--dry-run", "-n", "1"])

    line = capsys.readouterr().out
    assert "--consult-mode" not in line and "--provider" not in line
    assert "--allow-remote" not in line and "--live-model" in line


def test_provider_without_allow_remote_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        live_eval.main(["--out", str(tmp_path / "o"), "--provider", "anthropic", "--model", "m"])

    assert raised.value.code == 2
    assert "--allow-remote" in capsys.readouterr().err


def test_no_file_under_out_holds_the_key_even_with_kept_worlds(
    operator_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "fake_smoke.py"
    fake.write_text(_FAKE_SMOKE.replace("@KEY@", CANARY), encoding="utf-8")
    monkeypatch.setattr(live_eval, "SMOKE", fake)
    out = tmp_path / "out"

    live_eval.main(
        [
            "-n",
            "2",
            "--out",
            str(out),
            "--keep-worlds",
            "--provider",
            "anthropic",
            "--allow-remote",
            "--model",
            "claude-haiku-4-5",
        ]
    )

    files = [p for p in out.rglob("*") if p.is_file()]
    assert any(p.name == "t.jsonl" for p in files), "the kept world must still be there"
    assert files and all(CANARY not in p.read_text(errors="replace") for p in files)
    assert not any(p.name.startswith("secrets") for p in files)
    assert "[redacted]" in (out / "run-01.log").read_text()


def test_a_missing_key_is_refused_before_any_run(
    keyless_operator_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = live_eval.main(
        ["--out", str(tmp_path / "o"), "--provider", "anthropic", "--allow-remote", "--model", "m"]
    )

    assert code == 2 and not (tmp_path / "o").exists()
    assert KEY_ENV in capsys.readouterr().err


def test_dry_run_passes_the_sandbox_choice_to_every_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = live_eval.main(
        ["-n", "2", "--out", str(tmp_path / "out"), "--dry-run", "--sandbox", "on"]
    )

    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(lines) == 2
    assert all("--sandbox on" in line for line in lines)


def test_default_command_has_no_sandbox_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live_eval.main(["--out", str(tmp_path / "out"), "--dry-run", "-n", "1"])

    assert "--sandbox" not in capsys.readouterr().out


def test_sandbox_must_be_on_or_off(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        live_eval.main(["--out", str(tmp_path / "o"), "--sandbox", "maybe"])

    assert raised.value.code == 2
    assert "--sandbox" in capsys.readouterr().err
