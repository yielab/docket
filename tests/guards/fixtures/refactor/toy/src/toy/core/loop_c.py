"""Toy cycle, member three: reachable only through a local import."""

from toy.core import loop_a


def c():
    return loop_a.a
