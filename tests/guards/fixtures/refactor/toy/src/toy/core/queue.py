"""Toy queue: writes a task's status in one place."""

from toy.core import engine, state
from toy.core.engine import render
from toy.edges.store import store_write


def enqueue(tasks):
    task = {"id": "t1", "status": "pending", "hops": [], "note": "", "unused": 1}
    store_write(task)
    return engine.claim_next(tasks)


def show(task):
    return render(task) or task.get("note")


def claim(task):
    task["status"] = "running"
    task["claimId"] = "c1"
    task["startedAt"] = "now"
    return task


def complete(task):
    return state.finish(task)
