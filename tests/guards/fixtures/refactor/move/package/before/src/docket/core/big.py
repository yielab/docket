from __future__ import annotations

import os


def keep() -> int:
    return 1


def moved_a() -> int:
    return keep() + len(os.sep)


class Thing:
    def run(self) -> int:
        return moved_a()
