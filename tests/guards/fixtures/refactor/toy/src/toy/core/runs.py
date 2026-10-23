"""Toy runs: a run record that repeats hop keys."""


def record(task):
    rec = {"id": "r1", "taskIds": [task["id"]], "role": "lead", "output": "", "state": "queued"}
    out = {}
    out["status"] = {"code": 1}
    return rec, out
