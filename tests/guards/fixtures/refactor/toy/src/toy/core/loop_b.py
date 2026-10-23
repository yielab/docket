"""Toy cycle, member two: one edge hides in a function."""

from toy.core import loop_a


def b():
    from toy.core import loop_c

    return loop_a.a, loop_c.c
