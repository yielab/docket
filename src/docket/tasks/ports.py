"""What ``tasks`` asks of the contexts above it, bound once per entry (``bootstrap.bind_adapters``).

Settling a parked question reopens the task on the route of the pipeline step it was parked at,
and the pipeline is the business of ``hops``, which sits above ``tasks``: resolving an escalation
names only the shape of that step.
"""

from __future__ import annotations

from typing import Any, Protocol

from docket.kernel.ports import Binding


class QuestionAnswers(Protocol):
    def answer_question(
        self,
        project: str,
        task_id: str,
        action: str,
        content: dict[str, Any] | None,
        *,
        channel: str,
        actor: str,
    ) -> None:
        """Answer the question *task_id* is parked on and resume it; raises the errors of
        ``tasks.domain.resolution`` and writes nothing then."""
        ...


question_answers_port: Binding[QuestionAnswers] = Binding("question_answers")
question_answers: QuestionAnswers = question_answers_port.proxy()


def bind_question_answers(adapter: QuestionAnswers) -> None:
    question_answers_port.bind(adapter)
