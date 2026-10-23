"""Toy state: finishing and abandoning a task."""

from typing import Any


def finish(task: dict[str, Any]) -> dict[str, Any]:
    task["status"] = "done"
    task["completedAt"] = "now"
    task["claimId"] = None
    return task


def abandon(t, reason):
    if not isinstance(t, dict):
        raise TypeError(t)
    if reason:
        t["status"] = "failed"
        t["reason"] = reason
    return t


def requeue(task):
    from toy.core import queue

    return queue.claim(task)


def hop_record():
    return {"role": "lead", "stepId": "s1", "output": "text", "ok": True}
