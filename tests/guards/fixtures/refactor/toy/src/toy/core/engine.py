"""Toy engine: two call groups, one hub and one loner."""

LIMIT = 3


class Shared:
    """Used by one group only."""


def _log(message):
    return message


def _lock(task):
    _log("lock")
    return task


def _pick(tasks):
    _log("pick")
    return tasks[:LIMIT]


def claim_next(tasks):
    _log("claim")
    task = _pick(tasks)
    return _lock(task)


def _fmt(task):
    _log("fmt")
    return Shared


def render(task):
    _log("render")
    return _fmt(task)


def solo():
    return 1
