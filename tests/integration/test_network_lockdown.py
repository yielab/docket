"""Network lockdown for the exec jail: `gates network none|open`, the pod `network` setting.

Pins: both argv builders cut the network only when asked (default argv unchanged); a real bwrap
jail under `none` cannot reach the network while `open` gets past the network namespace; the pod
setting only ever narrows the global mode; `none` with isolation off refuses the turn before any
model call. See specs/functional/security-gates.spec.md (Network egress, requirement 6).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home

import docket.config as _cfg
from docket.cli import _gates
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core.audit import read_audit
from docket.core.dispatch import DispatchError
from docket.edges import store as _store
from docket.edges.adapters import system, toolbox
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.edges.adapters.system"

BWRAP_UP = system.bwrap_available()
needs_bwrap = pytest.mark.skipif(
    not BWRAP_UP, reason="bwrap not installed, or this host disallows unprivileged user namespaces"
)

# Prints the errno name when the connect fails at the network layer; never needs a real peer.
_PROBE = (
    "import socket, errno\n"
    "try:\n"
    "    s = socket.socket(); s.settimeout(2); s.connect(('1.1.1.1', 53))\n"
    "    print('CONNECTED')\n"
    "except OSError as e:\n"
    "    print('ERR', errno.errorcode.get(e.errno, e.errno))\n"
)


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repoint_docket_home(monkeypatch, tmp_path / "docket")
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)


class TestArgv:
    def test_bwrap_default_shares_net(self, tmp_path: Path) -> None:
        argv = system.bwrap_argv((tmp_path,), "true")
        assert "--share-net" in argv

    def test_bwrap_none_omits_share_net_but_keeps_unshare_all(self, tmp_path: Path) -> None:
        argv = system.bwrap_argv((tmp_path,), "true", network=False)
        assert "--share-net" not in argv
        assert "--unshare-all" in argv

    def test_docker_default_has_no_network_flag(self, tmp_path: Path) -> None:
        assert "--network" not in system.docker_run_argv("c", (tmp_path,), "true", None)

    def test_docker_none_adds_network_none(self, tmp_path: Path) -> None:
        argv = system.docker_run_argv("c", (tmp_path,), "true", None, network=False)
        i = argv.index("--network")
        assert argv[i + 1] == "none"
        assert i < argv.index("sh")


@needs_bwrap
class TestRealBwrap:
    def _run(self, tmp_path: Path, network: bool) -> str:
        script = tmp_path / "probe.py"
        script.write_text(_PROBE)
        out = toolbox.run_bash((tmp_path,), f"python3 {script}", 30, None, "auto", network=network)
        assert out.ok, out.error
        return out.content

    def test_none_cannot_connect(self, tmp_path: Path) -> None:
        content = self._run(tmp_path, network=False)
        assert "CONNECTED" not in content
        assert "ERR" in content

    def test_open_gets_past_the_network_namespace(self, tmp_path: Path) -> None:
        content = self._run(tmp_path, network=True)
        if "ENETUNREACH" in content:
            probe = subprocess.run(["ip", "route"], capture_output=True, text=True)
            if "default" not in probe.stdout:
                pytest.skip("host has no default route, so open cannot be told from none")
        assert "ENETUNREACH" not in content


class TestResolution:
    def _lead(self, project: str, **meta: str) -> None:
        lead = _pod.member_id(project, "lead")
        path = _cfg.meta_path(lead)
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            path, {"schemaVersion": 1, "kind": "project", "role": "lead", "pod": project, **meta}
        )

    @pytest.mark.parametrize(
        ("glob", "pod_value", "mode", "scope"),
        [
            ("open", "", "open", "default"),
            ("open", "open", "open", "default"),
            ("open", "none", "none", "pod"),
            ("none", "", "none", "global"),
            ("none", "open", "none", "global"),
            ("none", "none", "none", "global"),
        ],
    )
    def test_pod_only_narrows(self, glob: str, pod_value: str, mode: str, scope: str) -> None:
        if glob == "none":
            _fleet.set_network_mode("none")
        self._lead("shop", **({"network": pod_value} if pod_value else {}))
        assert _pod.effective_network("shop") == (mode, scope)

    def test_non_pod_agent_follows_global(self) -> None:
        assert _pod.effective_network(None) == ("open", "default")
        _fleet.set_network_mode("none")
        assert _pod.effective_network(None) == ("none", "global")

    def test_unreadable_pod_settings_fail_closed(self) -> None:
        self._lead("shop", network="bogus")
        assert _pod.effective_network("shop")[0] == "none"

    def test_pod_setting_validates(self) -> None:
        assert _pod.PodSettings.coerce("network", "none") == "none"
        with pytest.raises(_pod.PodSettingsError):
            _pod.PodSettings.coerce("network", "maybe")


class TestGatesCommand:
    def test_network_none_is_recorded_and_audited(self) -> None:
        assert _gates.run_gates("network", want="none") == 0
        assert _fleet.get_network_mode() == "none"
        assert [e for e in read_audit() if e["action"] == "gates.network"][-1]["detail"] == "none"
        assert _gates.run_gates("network", want="open") == 0
        assert _fleet.get_network_mode() == "open"

    def test_bad_value_is_usage_error(self) -> None:
        assert _gates.run_gates("network", want="sideways") == 2

    def test_status_names_the_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        _fleet.set_network_mode("none")
        _gates.run_gates("status")
        assert "Network: none (global)" in capsys.readouterr().out


class TestRefusal:
    def test_none_with_isolation_off_refuses_before_any_model_call(self) -> None:
        ws = _cfg.workspace_dir("solo-agent")
        ws.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            _cfg.meta_path("solo-agent"), {"kind": "project", "role": "implementer", "model": "t/m"}
        )
        record_isolation_off(_cfg.DOCKET_HOME)
        _fleet.set_network_mode("none")

        def _never(model: str) -> object:
            raise AssertionError("the model backend must not be reached")

        with pytest.raises(DispatchError) as excinfo:
            DocketDriver(backend_factory=_never).run_turn(  # type: ignore[arg-type]
                "solo-agent", "agent:solo-agent:default", "go", 30
            )

        assert "docket gates network" in str(excinfo.value)
        assert "docket gates isolate" in str(excinfo.value)
        assert [e for e in read_audit() if e["action"] == "network.refused"]
