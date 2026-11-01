"""The generated operator-v1.1 schemas exist and `gen_operator_schemas.py --check` passes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SUBJECT = "docket.kernel.operator_contract"

ROOT = Path(__file__).resolve().parents[3]


def test_v11_files_exist_and_check_passes() -> None:
    for name in ("question", "answer"):
        assert (ROOT / "docs/contracts/operator-v1.1" / f"{name}.schema.json").exists()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen_operator_schemas.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_the_published_v2_inbox_schema_names_the_turn_kind() -> None:
    schema = json.loads((ROOT / "docs/contracts/operator-v2/inbox.schema.json").read_text())
    assert "turn" in schema["$defs"]["EscalationView"]["properties"]["kind"]["enum"]
