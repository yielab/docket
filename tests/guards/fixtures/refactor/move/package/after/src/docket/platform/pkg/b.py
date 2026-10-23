from __future__ import annotations

import os

from docket.platform import big as _big
from docket.platform.big import keep


def fb() -> int:
    return len(os.sep) + _big.keep()


def moved_a() -> int:
    return keep() + len(os.sep)


class Thing:
    def run(self) -> int:
        return moved_a()
