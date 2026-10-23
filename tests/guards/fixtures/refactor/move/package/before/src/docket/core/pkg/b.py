from __future__ import annotations

import os

from docket.core import big as _big


def fb() -> int:
    return len(os.sep) + _big.keep()
