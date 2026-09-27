---
name: writing-a-spec
description: The shape of a specification that a Critic can approve and an Implementer can build from without asking, and the checks the Critic applies to it.
---

# Writing a specification

Use this on the `spec` step (Writer) and the `approve-spec` step (Critic) of the `spec-first`
pipeline. The spec is a file next to the code; a reply that only describes it is not a spec.

## What the Writer produces

One Markdown file with these sections, in this order:

1. **Problem.** What is wrong or missing today, in the user's terms, with the observable
   symptom. No solution language here.
2. **Behaviour.** Numbered requirements a test can check, each with a fixture, an action and
   an observable result. Use MUST for what the change guarantees and MAY for what it allows.
3. **Out of scope.** What this change deliberately does not do, so the Implementer does not
   drift into it.
4. **Interfaces.** Every function, command, file or field the change adds or alters, with
   its name, inputs, outputs and failure behaviour.
5. **Acceptance.** The exact commands or tests that prove the requirements, and what their
   output must contain.

Write it so that someone who has never spoken to you could implement it. If you cannot state
a requirement as something a test checks, it is not a requirement yet: say what is unknown.

## What the Critic checks

Answer `APPROVE` only when every item holds; otherwise `REJECT` and name the failing item.

- Every requirement in Behaviour has a fixture, an action and an observable result.
- Nothing in Behaviour depends on a decision the spec leaves open.
- Out of scope is non-empty and names the nearest tempting extension.
- Interfaces list every public name the change touches, including error cases.
- Acceptance commands exist in this repository, or the spec says which one to add.
