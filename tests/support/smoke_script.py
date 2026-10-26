"""The workflow smoke script loaded as a module, and the fixture writer its oracle tests share."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SMOKE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "smoke_workflow.py"


_SMOKE_SPEC = importlib.util.spec_from_file_location("docket_smoke_workflow", _SMOKE_PATH)


assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None


_smoke = importlib.util.module_from_spec(_SMOKE_SPEC)


sys.modules[_SMOKE_SPEC.name] = _smoke


_SMOKE_SPEC.loader.exec_module(_smoke)


REMOTE_KEY_ENV = "ANTHROPIC_API_KEY"
CANARY_KEY = "sk-ant-canary-0123456789abcdef"
