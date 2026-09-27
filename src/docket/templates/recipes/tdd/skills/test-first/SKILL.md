---
name: test-first
description: How to write the one failing test that defines the change before any implementation exists, and how to make it pass without widening scope.
---

# Test first

Use this on the `red` and `green` steps of the `tdd` pipeline.

## Red: one failing test, nothing else

- Read the task and name the single observable behaviour it asks for. If it asks for two,
  pick the first and say so in your reply; the second is another task.
- Find the existing test module for the code the task names (the file that already imports
  it). Add one test there, or create the module the project's layout expects. Do not touch
  production code.
- The test asserts the behaviour through the public interface a caller would use, not
  through internals. Name it after the behaviour, not after the function.
- Run the test runner once and confirm the new test fails for the right reason: the
  behaviour is missing, not an import error, a typo or a fixture problem. Paste the failing
  line into your reply.
- Stop. The `check-red` step re-runs the suite and fails the task if the test already passes:
  a test that cannot fail proves nothing.

## Green: the smallest change that passes

- Make the failing test pass with the smallest change you can defend. Resist refactoring
  unrelated code; note it for a later task instead.
- Run the whole suite, not only the new test. A previously green test turning red is part
  of your change to fix.
- Keep the test you wrote unchanged unless it was wrong; if you must change it, say why.
- End your reply with what you changed, the test you added, and the suite's final line.
