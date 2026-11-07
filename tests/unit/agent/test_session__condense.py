"""History condensation (`agent/session.py::condense_history`).

Covers which tool results are condensed, in batches, and the notice a condensed result carries.
"""

from tests.support import home as _support_home

from docket.agent import ports as _ports
from docket.agent import session as _sess
from docket.agent.ports import (
    ChatMessage,
    ToolCall,
    assistant,
    user,
)
from docket.kernel import untrusted
from docket.kernel.home import current_home

_isolate_sessions_dir = _support_home.isolate_sessions_dir

SUBJECT = "docket.agent.session"


def tool_result(call: ToolCall, content: str) -> ChatMessage:
    """A tool message holding *content* as given: the size rules here count whatever it holds."""
    return ChatMessage(role="tool", content=content, tool_call_id=call.id, name=call.name)


def _framed_exchange(n: int, body: str) -> list[ChatMessage]:
    """A read whose result is framed as the loop frames it."""
    call = ToolCall(id=f"c{n}", name="read", arguments=f'{{"path":"src/f{n}.py"}}')
    return [assistant("", tool_calls=[call]), _ports.tool_result(call, body)]


def _read_exchange(n: int, body: str | None = None) -> list[ChatMessage]:
    call = ToolCall(id=f"c{n}", name="read", arguments=f'{{"path":"src/f{n}.py"}}')
    content = body if body is not None else "\n".join(f"{i}\tline {n}-{i}" for i in range(1, 41))
    return [assistant("", tool_calls=[call]), tool_result(call, content)]


def _history(count: int) -> list[ChatMessage]:
    out: list[ChatMessage] = [user("the task")]
    for n in range(count):
        out.extend(_read_exchange(n))
    return out


class TestCondenseHistory:
    """The built request names old tool results in one line; the stored history is untouched."""

    def test_keeps_k_whole_results_and_notices_for_the_rest(self) -> None:
        """Six read results with K=2 leave two whole and four one-line notices."""
        messages = _history(6)
        out = _sess.condense_history(messages, keep=2, budget=0)
        results = [m for m in out if m.role == "tool"]
        whole = [m for m in results if m.content.count("\n") > 5]
        notices = [m for m in results if m.content.startswith("[read src/f")]
        assert (len(whole), len(notices)) == (2, 4)
        assert [m.tool_call_id for m in results] == [f"c{n}" for n in range(6)]
        assert results[0].content == (
            "[read src/f0.py: 40 lines, 501 characters. You read this earlier in this session; "
            "its text is no longer in this view. Call read again only for text you still need.]"
        )
        assert all(m.content.count("\n") > 5 for m in results[-2:])

    def test_input_is_never_mutated_and_the_task_stays_whole(self) -> None:
        """The projection returns new messages; user messages and the input list stay as given."""
        messages = _history(5)
        before = list(messages)
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert messages == before
        assert out[0] == user("the task")

    def test_is_deterministic_and_prefix_stable_between_requests(self) -> None:
        """Two consecutive requests agree byte for byte up to the newly condensed message."""
        first = _sess.condense_history(_history(5), keep=2, budget=0)
        second = _sess.condense_history(_history(6), keep=2, budget=0)
        assert _sess.condense_history(_history(6), keep=2, budget=0) == second
        shared = next(i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b)
        assert first[:shared] == second[:shared]
        assert second[shared].role == "tool"
        assert second[shared].tool_call_id == "c3"

    def test_a_short_result_is_left_alone(self) -> None:
        """A result no longer than its notice is not rewritten."""
        messages = [user("t"), *_read_exchange(0, "ok"), *_read_exchange(1), *_read_exchange(2)]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[2].content == "ok"
        assert out[4].content.startswith("[read src/f1.py")

    def test_errors_stay_short_and_whole_inside_their_frame(self) -> None:
        """A short error is kept verbatim and a long one keeps only its head, frame and all."""
        short = "ERROR: not a file: src/f0.py"
        long = "ERROR: " + "x" * 3000
        messages = [
            user("t"),
            *_framed_exchange(0, short),
            *_framed_exchange(1, long),
            *_read_exchange(2),
        ]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[2] == messages[2]
        cut = untrusted.unframe(out[4].content)
        assert cut is not None and cut[0] == "result of read"
        assert cut[2].startswith("ERROR: xxx")
        assert len(out[4].content) < 700
        assert "more characters" in cut[2]

    def test_a_framed_plain_result_becomes_a_notice_that_counts_the_output_not_the_frame(
        self,
    ) -> None:
        body = "\n".join(["x" * 100] * 50)
        messages = [user("t"), *_framed_exchange(0, body), *_read_exchange(1), *_read_exchange(2)]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[2].content.startswith("[read src/f0.py: 50 lines, 5,049 characters.")

    def test_large_write_arguments_in_old_messages_become_a_count(self) -> None:
        """An old write keeps valid JSON arguments with the large string replaced."""
        body = "w" * 5000
        args = f'{{"path":"content/x.md","content":"{body}"}}'
        call = ToolCall(id="w1", name="write", arguments=args)
        messages = [
            user("t"),
            assistant("", tool_calls=[call]),
            tool_result(call, "wrote 5000 characters to content/x.md"),
            *_read_exchange(1),
            *_read_exchange(2),
        ]
        out = _sess.condense_history(messages, keep=2, budget=0)
        import json

        sent = json.loads(out[1].tool_calls[0].arguments)
        assert sent == {"path": "content/x.md", "content": "[wrote content/x.md: 5,000 characters]"}
        assert out[1].tool_calls[0].id == "w1"
        assert _sess.condense_history(messages, keep=3, budget=0)[1] == messages[1]

    def test_unparseable_arguments_are_left_untouched(self) -> None:
        """Arguments that are not a JSON object are never rewritten."""
        call = ToolCall(id="w1", name="write", arguments="{not json" + "x" * 900)
        messages = [
            user("t"),
            assistant("", tool_calls=[call]),
            tool_result(call, "r" * 900),
            *_read_exchange(1),
        ]
        assert _sess.condense_history(messages, keep=1, budget=0)[1] == messages[1]

    def test_small_results_stay_whole_within_the_budget(self) -> None:
        """Results that fit the character budget together are never condensed, whatever K is."""
        messages = _history(6)
        out = _sess.condense_history(messages, keep=1, budget=10_000)
        assert out == messages

    def test_the_budget_condenses_from_the_first_result_that_does_not_fit(self) -> None:
        """Newest first, results stay whole while they fit; that one and every older one go."""
        messages = _history(6)
        size = len(messages[-1].content)
        out = _sess.condense_history(messages, keep=1, budget=3 * size)
        results = [m for m in out if m.role == "tool"]
        assert [m.content.startswith("[read src/f") for m in results] == [True] * 3 + [False] * 3

    def test_a_condensed_result_stays_condensed_as_results_arrive(self) -> None:
        """Under the budget a result only moves from whole to notice, so the prefix stays stable."""
        size = len(_history(1)[-1].content)
        seen: set[str] = set()
        for count in range(1, 9):
            out = _sess.condense_history(_history(count), keep=2, budget=3 * size)
            condensed = {m.tool_call_id for m in out if m.role == "tool" and m.content[0] == "["}
            assert seen <= condensed
            seen = condensed
        assert seen


class TestCondenseHistoryUnansweredRound:
    """A tool result the model has not answered yet is never condensed."""

    @staticmethod
    def _round(count: int, size: int) -> list[ChatMessage]:
        calls = [
            ToolCall(id=f"p{n}", name="fetch", arguments=f'{{"url":"https://h{n}.example/page"}}')
            for n in range(count)
        ]
        return [assistant("", tool_calls=calls), *(tool_result(c, "x" * size) for c in calls)]

    def test_a_round_of_parallel_results_stays_whole_before_the_model_reads_it(self) -> None:
        """Five large results after the last assistant message are all sent whole."""
        messages = [user("the task"), *_read_exchange(0, "y" * 2_000), *self._round(5, 4_000)]
        out = _sess.condense_history(messages, keep=2, budget=6_000)
        unanswered = [m for m in out if m.tool_call_id.startswith("p")]
        assert [m.content for m in unanswered] == ["x" * 4_000] * 5
        assert out[2].content.startswith("[read src/f0.py: 1 lines")

    def test_the_same_round_is_condensed_once_the_model_has_answered(self) -> None:
        """After an assistant message follows, the older results of the round become notices."""
        messages = [user("the task"), *self._round(5, 4_000), assistant("noted"), user("go on")]
        out = _sess.condense_history(messages, keep=2, budget=6_000)
        results = [m for m in out if m.role == "tool"]
        assert [m.content.startswith("[fetch https://h") for m in results] == [True] * 3 + [
            False
        ] * 2
        assert "You read this earlier in this session" in results[0].content

    def test_the_call_of_an_unanswered_write_keeps_its_body(self) -> None:
        """A write whose result is unanswered keeps its large argument too."""
        body = "w" * 5000
        call = ToolCall(id="w1", name="write", arguments=f'{{"path":"a.md","content":"{body}"}}')
        messages = [
            user("t"),
            *_read_exchange(0),
            *_read_exchange(1),
            assistant("", tool_calls=[call]),
            tool_result(call, "wrote 5000 characters to a.md"),
        ]
        out = _sess.condense_history(messages, keep=1, budget=0)
        assert out[-2].tool_calls[0] == call
        assert out[-1].content == "wrote 5000 characters to a.md"


class TestCondenseHistoryBatches:
    """The cut moves in batches, so the request prefix survives the calls between boundaries."""

    def test_the_prefix_is_identical_between_batch_boundaries(self) -> None:
        """With 2,000-character results the prefix moves at five of twelve steps, not nine."""

        def grown(count: int) -> list[ChatMessage]:
            out: list[ChatMessage] = [user("the task")]
            for n in range(count):
                out.extend(_read_exchange(n, body=str(n).ljust(2_000, "x")))
            return out

        previous = _sess.condense_history(grown(1))
        boundaries = 0
        for count in range(2, 13):
            current = _sess.condense_history(grown(count))
            if current[: len(previous) - 2] != previous[:-2]:
                boundaries += 1
            previous = current
        assert boundaries == 5

    def test_the_low_water_mark_leaves_room_before_the_next_cut(self) -> None:
        """After a cut the whole results fit the low-water mark, so the next few arrivals add none."""
        size = 1_000

        def grown(count: int) -> list[ChatMessage]:
            out: list[ChatMessage] = [user("the task")]
            for n in range(count):
                out.extend(_read_exchange(n, body="y" * size))
            return out

        def condensed(count: int) -> int:
            out = _sess.condense_history(grown(count), keep=1)
            return sum(1 for m in out if m.role == "tool" and m.content.startswith("[read"))

        assert [condensed(n) for n in range(5, 12)] == [0, 0, 4, 4, 4, 4, 8]


class TestCondenseHistorySmallResults:
    """A short result survives while a longer one is whole, and a notice names its artifact."""

    @staticmethod
    def _exchange(n: int, name: str, args: str, body: str) -> list[ChatMessage]:
        call = ToolCall(id=f"c{n}", name=name, arguments=args)
        return [assistant("", tool_calls=[call]), tool_result(call, body)]

    def test_one_large_grep_never_evicts_the_short_read_before_it(self) -> None:
        """The README read is 1.2 KB, the grep 20 KB: the next result must not push the read out."""
        readme = "r" * 1_200
        messages = [
            user("t"),
            *self._exchange(0, "read", '{"path":"README.md"}', readme),
            *self._exchange(1, "grep", '{"pattern":"x"}', "g" * 20_000),
            *self._exchange(2, "read", '{"path":"b.py"}', "b" * 100),
        ]

        out = _sess.condense_history(messages, keep=2, budget=0)

        results = [m for m in out if m.role == "tool"]
        assert results[0].content == readme
        assert results[1].content == "g" * 20_000
        assert results[2].content == "b" * 100

    def test_a_short_result_is_condensed_once_no_longer_result_is_whole(self) -> None:
        messages = [
            user("t"),
            *self._exchange(0, "read", '{"path":"a"}', "a" * 1_200),
            *self._exchange(1, "read", '{"path":"b"}', "b" * 1_200),
            *self._exchange(2, "read", '{"path":"c"}', "c" * 1_200),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        results = [m for m in out if m.role == "tool"]
        assert [m.content.startswith("[read") for m in results] == [True, True, False]

    def test_a_result_at_the_small_limit_is_not_protected(self) -> None:
        size = _sess.HISTORY_SMALL_RESULT_CHARS
        messages = [
            user("t"),
            *self._exchange(0, "read", '{"path":"a"}', "a" * size),
            *self._exchange(1, "grep", '{"pattern":"x"}', "g" * 20_000),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        assert next(m for m in out if m.role == "tool").content.startswith("[read a:")

    def test_a_kept_short_result_still_has_its_calls_large_arguments_condensed(self) -> None:
        body = "w" * 5_000
        call = ToolCall("w1", "write", f'{{"path":"x.md","content":"{body}"}}')
        messages = [
            user("t"),
            assistant("", tool_calls=[call]),
            tool_result(call, "wrote x.md: 5000 bytes"),
            *self._exchange(1, "grep", '{"pattern":"x"}', "g" * 20_000),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        assert out[2].content == "wrote x.md: 5000 bytes"
        assert "[wrote x.md: 5,000 characters]" in out[1].tool_calls[0].arguments

    def test_the_notice_for_a_result_with_an_artifact_names_it_instead_of_a_rerun(self) -> None:
        line = "[full output: /pod/cache/artifacts/abc.txt \u2014 read it with read(path, offset, limit)]"
        grep = "hit\n" * 600 + "\n[truncated: 9 more characters]\n\n" + line
        messages = [
            user("t"),
            *self._exchange(0, "grep", '{"pattern":"hit"}', grep),
            *self._exchange(1, "read", '{"path":"b"}', "b" * 3_000),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        notice = next(m for m in out if m.role == "tool").content
        assert "You read this earlier in this session; its text is no longer in this view" in notice
        assert "the full output is in /pod/cache/artifacts/abc.txt" in notice
        assert "read it with read(path, offset, limit)" in notice
        assert "call grep again" not in notice

    def test_no_notice_says_omitted_or_can_be_read_as_the_tool_refusing_a_repeat(self) -> None:
        """Both notices say whose view it is; neither uses a word that reads as the tool's answer."""
        line = "[full output: /pod/cache/artifacts/abc.txt \u2014 read it with read(path, offset, limit)]"
        messages = [
            user("t"),
            *self._exchange(0, "fetch", '{"url":"https://a.example/p"}', "a" * 3_000),
            *self._exchange(1, "grep", '{"pattern":"hit"}', "hit\n" * 600 + "\n" + line),
            *self._exchange(2, "read", '{"path":"b"}', "b" * 3_000),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        notices = [m.content for m in out if m.role == "tool" and m.content.startswith("[")]
        assert len(notices) == 2
        for notice in notices:
            assert "omitted" not in notice
            assert "already seen" not in notice
            assert (
                "You read this earlier in this session; its text is no longer in this view"
                in notice
            )

    def test_a_cut_error_result_keeps_the_artifact_path(self) -> None:
        line = "[full output: /pod/cache/artifacts/abc.txt \u2014 read it with read(path, offset, limit)]"
        failed = "ERROR: command exited 1\n" + "e" * 2_000 + "\n\n" + line
        messages = [
            user("t"),
            *_framed_exchange(0, failed),
            *self._exchange(1, "read", '{"path":"b"}', "b" * 3_000),
        ]

        out = _sess.condense_history(messages, keep=1, budget=0)

        cut = untrusted.unframe(next(m for m in out if m.role == "tool").content)
        assert cut is not None
        assert cut[2].endswith("\n[full output: /pod/cache/artifacts/abc.txt]")


class TestWindowResultsBudget:
    """The room a window leaves, in tokens, sets how many result characters stay whole."""

    def test_a_small_room_never_goes_below_the_default(self) -> None:
        assert _sess.window_results_budget(1_000) == _sess.HISTORY_FULL_RESULTS_CHARS == 6_000
        assert _sess.window_results_budget(-500) == 6_000

    def test_a_wide_room_keeps_every_character_it_holds(self) -> None:
        per_token = current_home().context_bytes_per_token
        assert _sess.window_results_budget(25_000) == 25_000 * per_token

    def test_the_low_water_is_half_the_budget(self) -> None:
        """Twelve 2,000-character results cross 20,000 once; the cut leaves 10,000 whole, then one more arrives."""
        budget = 20_000
        out = _sess.condense_history(_history_of(12, 2_000), keep=2, budget=budget)
        whole = [len(m.content) for m in out if m.role == "tool" and m.content[0] != "["]
        assert whole == [2_000] * 6

    def test_a_larger_budget_moves_the_cut_once_where_the_default_moves_it_often(self) -> None:
        wide = _cut_moves(12, 1_800, 18_750)
        default = _cut_moves(12, 1_800, _sess.HISTORY_FULL_RESULTS_CHARS)
        assert wide == 1
        assert default > 1


def _history_of(count: int, size: int) -> list[ChatMessage]:
    out: list[ChatMessage] = [user("the task")]
    for n in range(count):
        out.extend(_read_exchange(n, "x" * size))
    return out


def _cut_moves(count: int, size: int, budget: int) -> int:
    """How many times the set of condensed results changes as results arrive one at a time."""
    previous = 0
    moves = 0
    for n in range(1, count + 1):
        out = _sess.condense_history(_history_of(n, size), keep=2, budget=budget)
        condensed = sum(1 for m in out if m.role == "tool" and m.content[0] == "[")
        moves += condensed != previous
        previous = condensed
    return moves
