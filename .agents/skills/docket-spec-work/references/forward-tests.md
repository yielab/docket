# Evaluator-only spec-work rubric

The evaluation coordinator may read this to prepare an isolated fixture before the run, but must
never include it in the evaluated agent's context. Apply the required outcomes only after an
independent `docket-spec-work` candidate finishes. Keep ordinary implementation context smaller by
leaving it unloaded.

## Independent evaluation protocol

Use a fresh worktree per case. Give the evaluated agent the request, this skill, and the minimum raw
fixture, but not the expected answer or suspected bug. Afterward inspect the diff, test execution,
exit codes, persisted artifacts, and handoff status. Do not grade exact prose.

| Case | Minimum fixture and request | Required observable outcome |
| --- | --- | --- |
| Free-form CLI input | A real CLI command accepting text plus an adjacent option; request parity between one argv item and split positional words | RED test invokes both argv shapes without literal quote delimiters, preserves the option, and asserts the exact dispatched/persisted value and absence of extra records |
| Persisted v1 to v2 | Handwritten supported v1 JSON plus empty state; add a v2 field while preserving v1 homes | Tests new writes and the real load-modify-write-read path for v1, retain unaffected data, and prove a failed write/migration leaves the original intact |
| Documentation claim only | README clarification of behavior that already works and is contracted | Verify the live command or existing behavioral test behind the claim; avoid fabricated RED/spec version churn; run only additive gates for touched claim surfaces |
| Helper versus shipped feature | An isolated helper exists but the request claims automatic behavior | Test from the default caller before calling it shipped; if the request explicitly asks only for scaffolding, keep scope internal and report the product capability unshipped |
| Final gate failure | Focused test passes while a required full gate has a deterministic failure outside the diff | Preserve and name the failure, compare with baseline, avoid unrelated repair or validator edits, and report `partial` unless an explicit contract waiver exists |

Add cases for retries, concurrency, idempotency, rollback, packaging, or platform differences only
when the affected contract exposes those risks. Do not turn every unit change into a maximal
end-to-end suite.
