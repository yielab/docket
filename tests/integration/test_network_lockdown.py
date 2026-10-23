"""Network lockdown for the exec jail: `gates network none|open`, the pod `network` setting.

Pins: the argv builders cut the network only when asked (default argv unchanged); a real landlock
jail under `none` cannot reach the network while `open` gets past the network namespace; the pod
setting only ever narrows the global mode; `none` with isolation off refuses the turn before any
model call. See specs/functional/security-gates.spec.md (Network egress, requirement 6).
"""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.conftest import record_isolation_off

from docket.agent.driver import DocketDriver
from docket.agent.tools.builtins import toolbox
from docket.governance.audit import read_audit
from docket.interfaces.cli.commands import setup_sandbox as _setup_sandbox
from docket.kernel.home import Home, current_home, use_home
from docket.platform import store as _store
from docket.sandbox import docker, landlock
from docket.tasks.domain.task import DispatchError
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

SUBJECT = "docket.sandbox.launch"

needs_landlock = pytest.mark.skipif(
    not landlock.landlock_available(), reason="landlock is not available on this host"
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
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    with use_home(Home(tmp_path / "docket")):
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        yield


class TestArgv:
    def test_landlock_default_is_open_and_none_is_explicit(self, tmp_path: Path) -> None:
        open_argv = landlock.landlock_argv((tmp_path,), "true")
        none_argv = landlock.landlock_argv((tmp_path,), "true", network=False)
        assert open_argv[open_argv.index("--net") + 1] == "open"
        assert none_argv[none_argv.index("--net") + 1] == "none"

    def test_docker_default_has_no_network_flag(self, tmp_path: Path) -> None:
        assert "--network" not in docker.docker_run_argv("c", (tmp_path,), "true", None)

    def test_docker_none_adds_network_none(self, tmp_path: Path) -> None:
        argv = docker.docker_run_argv("c", (tmp_path,), "true", None, network=False)
        i = argv.index("--network")
        assert argv[i + 1] == "none"
        assert i < argv.index("sh")


@needs_landlock
class TestRealLandlock:
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
        path = current_home().meta_path(lead)
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            path, {"schemaVersion": 1, "kind": "project", "role": "lead", "pod": project, **meta}
        )

    @pytest.mark.parametrize(
        ("glob", "pod_value", "mode", "scope"),
        [
            ("open", "", "open", "default"),
            ("open", "open", "open", "default"),
            ("unset", "", "none", "default"),
            ("unset", "open", "none", "default"),
            ("unset", "none", "none", "pod"),
            ("open", "none", "none", "pod"),
            ("none", "", "none", "global"),
            ("none", "open", "none", "global"),
            ("none", "none", "none", "global"),
        ],
    )
    def test_pod_only_narrows(self, glob: str, pod_value: str, mode: str, scope: str) -> None:
        if glob != "unset":
            _fleet.set_network_mode(glob)
        self._lead("shop", **({"network": pod_value} if pod_value else {}))
        assert _pod.effective_network("shop") == (mode, scope)

    def test_non_pod_agent_follows_global(self) -> None:
        assert _pod.effective_network(None) == ("none", "default")
        _fleet.set_network_mode("open")
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
        assert _setup_sandbox.network("none") == 0
        assert _fleet.get_network_mode() == "none"
        assert [e for e in read_audit() if e["action"] == "gates.network"][-1]["detail"] == "none"
        assert _setup_sandbox.network("open") == 0
        assert _fleet.get_network_mode() == "open"

    def test_bad_value_is_usage_error(self) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        result = CliRunner().invoke(app, ["setup", "sandbox", "network", "sideways"])
        assert result.exit_code == 2

    def test_status_names_the_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        _fleet.set_network_mode("none")
        _setup_sandbox.status()
        assert "Network: none" in capsys.readouterr().out


class TestRefusal:
    def test_the_unrecorded_default_is_not_refused_without_a_jail(self) -> None:
        from docket.agent.driver import _resolve_network

        assert _fleet.get_network_mode() == "none"
        assert _resolve_network("solo-agent", "implementer", False) == (True, None)
        assert _resolve_network("solo-agent", "implementer", True) == (False, None)

    def test_none_with_isolation_off_refuses_before_any_model_call(self) -> None:
        ws = current_home().workspace_dir("solo-agent")
        ws.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            current_home().meta_path("solo-agent"),
            {"kind": "project", "role": "implementer", "model": "t/m"},
        )
        record_isolation_off(current_home().root)
        _fleet.set_network_mode("none")

        def _never(model: str) -> object:
            raise AssertionError("the model backend must not be reached")

        with pytest.raises(DispatchError) as excinfo:
            DocketDriver(backend_factory=_never).run_turn(  # type: ignore[arg-type]
                "solo-agent", "agent:solo-agent:default", "go", 30
            )

        assert "docket setup sandbox network" in str(excinfo.value)
        assert "docket setup sandbox on" in str(excinfo.value)
        assert [e for e in read_audit() if e["action"] == "network.refused"]


def _docker_bridge_gateway() -> str | None:
    try:
        out = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                "bridge",
                "-f",
                "{{range .IPAM.Config}}{{.Gateway}}{{end}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout.strip() or None


@pytest.fixture
def host_listener() -> Iterator[tuple[str, int]]:
    """A listener on the docker bridge gateway, so a container can reach it only with a network."""
    if not docker.docker_daemon_reachable():
        pytest.skip("docker not installed or its daemon is not reachable on this host")
    ip = _docker_bridge_gateway()
    if not ip:
        pytest.skip("docker bridge gateway address not found")
    if (
        subprocess.run(
            ["docker", "image", "inspect", current_home().sandbox_docker_image], capture_output=True
        ).returncode
        != 0
    ):
        pytest.skip(
            f"{current_home().sandbox_docker_image} is not present locally (tests never pull)"
        )
    srv = socket.socket()
    try:
        srv.bind((ip, 0))
    except OSError as e:
        srv.close()
        pytest.skip(f"cannot bind the docker bridge gateway {ip}: {e}")
    srv.listen(5)
    yield ip, srv.getsockname()[1]
    srv.close()


class TestRealDockerNetwork:
    def test_network_none_cannot_reach_a_host_listener(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        host_listener: tuple[str, int],
    ) -> None:
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        ip, port = host_listener
        out = toolbox.run_bash((tmp_path,), f"nc -z -w2 {ip} {port}", sandbox="auto", network=False)
        assert not out.ok

    def test_network_open_reaches_the_same_listener(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        host_listener: tuple[str, int],
    ) -> None:
        """The positive control: without it the refusal above could be a dead listener."""
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
        ip, port = host_listener
        out = toolbox.run_bash((tmp_path,), f"nc -z -w2 {ip} {port}", sandbox="auto", network=True)
        assert out.ok, out.error or out.content
