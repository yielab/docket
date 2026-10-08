# tdd

**Practice:** test-driven development (red -> green -> refactor).

**Source idea:** write a failing test first, then the smallest change that makes it pass (Kent
Beck's red-green-refactor cycle).

**What docket's gates make structural:** `check-red` is not advice — it is a `run` command step
that actually executes the test suite and fails the whole task if the new test does not fail, so
an Implementer cannot skip "red" and go straight to "green". `green`'s own verify command is a
second, independent mechanical gate, and the Tester's PASS/FAIL verdict is a third; nothing here
counts as done on an agent's own say-so.

## Apply it

For a new pod, or onto one that already has its `lead` and `implementer`:

```bash
docket init --recipe tdd          # a new pod for the current repository
docket pod apply tdd    # onto an existing pod
```

`pod.yaml` names the one member this recipe adds (`tester`); `apply` validates the roster and
`pipeline.yaml` before writing anything, and is safe to run again (a second run plans every item
`skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` — what `apply` reads: `kind: pod`, `name: tdd`, `members: [tester]`.
- `pipeline.yaml` — `red` (Implementer writes exactly one failing test) -> `check-red` (a `run`
  command step, routed `on: {pass: fail, fail: green}` so the task fails outright if the new test
  does not actually fail) -> `green` (Implementer, gated on its own verify command) -> `test`
  (Tester, PASS/FAIL verdict). `check-red`'s command is the literal `python3 -m pytest -q` — the
  pipeline format's `run` field carries no `${var}`-style interpolation (only a step's
  `instructions` does), so edit this line by hand if the project's test runner is something else.
- `skills/test-first/SKILL.md` -- how to write the one failing test and make it pass without widening scope; listed in the prompt, read on demand with the `skill` tool.

## Undo

```bash
docket pod <project> config unset pipeline
docket pod <project> remove <project>-tester
```
