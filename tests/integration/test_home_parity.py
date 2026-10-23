"""``Home.from_environ`` resolves every value ``docket.config`` resolves, one fresh process per
environment because config.py reads the environment at import. Delete with config.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SUBJECT = "docket.kernel.home"

_PROBE = """
import json, os
import docket.config as c
from docket.kernel.home import Home

h = Home.from_environ(os.environ)
packaged = {"PROVIDER_TEMPLATES_DIR", "EXPORTER_TEMPLATES_DIR", "CHANNEL_TEMPLATES_DIR"}
bad, missing = [], []
for name in sorted(n for n in dir(c) if n.isupper() and n not in packaged):
    attr = "root" if name == "DOCKET_HOME" else name.lower()
    if not hasattr(h, attr):
        missing.append(name)
        continue
    mine, theirs = getattr(h, attr), getattr(c, name)
    if mine != theirs or type(mine) is not type(theirs):
        bad.append(f"{name}: config={theirs!r} home={mine!r}")
for fn in ("workspace_dir", "meta_path", "pod_scratch_dir", "pod_cache_dir",
           "pod_memory_path", "pod_config_dir", "pod_work_dir"):
    if getattr(h, fn)("x") != getattr(c, fn)("x"):
        bad.append(fn)
if h.user_recipes_dir != c.user_recipes_dir():
    bad.append("user_recipes_dir")
print(json.dumps({"bad": bad, "missing": missing}))
"""

_SCENARIOS = {
    "unset": {},
    "set": {
        "DOCKET_HOME": "/srv/dk-home",
        "TRACES_DIR": "/srv/traces",
        "FLEET_FILE": "/srv/fleet.json",
        "SESSION_TIMEOUT": "7",
        "AUDIT_LOG_MAX_BYTES": "123",
        "CONTEXT_TOKEN_BUDGET": "999",
        "CONTEXT_BYTES_PER_TOKEN": "0",
        "DISPATCH_RETRY_BACKOFF_S": "0.5",
        "DISPATCH_RETRIES_DEFAULT": "9",
        "DISPATCH_RETRIES_REVIEWER": "1",
        "DISPATCH_TURN_TIMEOUT_S": "77",
        "DISPATCH_VERIFY_TIMEOUT_S": "",
        "DOCKET_KEY_MAX_AGE_DAYS": "5",
        "DOCKET_SANDBOX_IMAGE": "busybox",
        "FETCH_ALLOWED_DOMAINS": " A.test, b.test ,",
    },
    "empty-path": {"TRACES_DIR": "", "DOCKET_HOME": "/srv/other"},
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_home_matches_config(scenario: str, tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **_SCENARIOS[scenario]}
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE], env=env, capture_output=True, text=True, check=True
    )
    result = json.loads(proc.stdout)
    assert result == {"bad": [], "missing": []}
