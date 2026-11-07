"""Outcome graders: did the work pass? They read the verifier, the produced file or the task status."""

from __future__ import annotations

from collections.abc import Mapping

from evals.evaluator.graders.base import GradeContext, GraderInputError, GraderResult


def hidden_tests(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Do the hidden checks pass on the copy of the agent's repository?"""
    if ctx.verifier is None:
        raise GraderInputError("no verifier result")
    tail = ctx.verifier.output_tail.strip().splitlines()[-1:] or [""]
    return GraderResult(ctx.verifier.status, f"{ctx.verifier.status}: {tail[0]}")


def file_exact(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Is the produced file exactly the bytes asked for?"""
    if ctx.repo is None or not ctx.repo.is_dir():
        raise GraderInputError("the agent's repository is absent")
    wanted = params["path"]
    target = (ctx.repo / wanted).resolve()
    if not target.is_relative_to(ctx.repo.resolve()):
        return GraderResult("fail", f"{wanted} leaves the repository")
    if not target.is_file():
        return GraderResult("fail", f"{wanted} was not produced")
    if target.read_bytes() != params["content"].encode("utf-8"):
        return GraderResult("fail", f"{wanted} differs from the bytes asked for")
    return GraderResult("pass", f"{wanted} matches")


def task_status(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Did the task end in the named status?"""
    if ctx.status is None:
        raise GraderInputError("the task's final status is unknown")
    want = params["status"]
    if ctx.status == want:
        return GraderResult("pass", f"the task ended {want}")
    return GraderResult("fail", f"the task ended {ctx.status}, wanted {want}")
