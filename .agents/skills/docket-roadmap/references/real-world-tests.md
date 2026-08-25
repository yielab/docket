# Real-world roadmap tests

Read this when a card needs executable acceptance evidence rather than a generic test label.

Build the smallest repository fixture that contains the decision signals: current board marker,
selected and active-card ownership, relevant Git status, named trigger evidence, and the bounded
spec or roadmap decision. Keep historical text only when history confusion is the risk under test.

For each case, state:

- initial board and worktree state;
- user action, including whether a claim or board mutation was requested;
- sources the decision is allowed to consult;
- expected mutation boundary or byte-identical no-op;
- evidence that makes scheduling, refusal, or parallelism correct;
- one nearby counterexample, such as unrelated dirty work or measured versus estimated evidence.

Exercise degraded Git, clear/ambiguous boards, ownership collision, and trigger quality when those
conditions can change the decision. Test `context_snapshot.py` through `--root` for integration and
its pure helpers for failure injection. Assert state, selected card, diff, and output cap; do not
assert whole prose snapshots.

Skill maintainers performing an independent behavioral evaluation use `forward-tests.md` as the
hidden post-run rubric. Do not give that file to the evaluated agent.
