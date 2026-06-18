# Cost Tracking Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines how docket reports token usage and dollar cost per agent, enforces
per-agent budget caps, and detects runaway spend.

## Scope

This specification covers:

- Reporting usage and cost (`docket cost`)
- Per-agent budget caps (`docket profile --budget`)
- Pausing an agent when its cap is reached and runaway detection (`docket doctor`)

This specification does NOT cover the role→model policy or pricing table (see model-profiles.spec.md).

## Requirements

### Cost reporting (docket cost)

1. `docket cost [agent-id]` **MUST** report token usage and dollar cost; with no id it
   **MUST** aggregate across all agents.
2. Costs **MUST** be derived from session data under `~/.openclaw/agents/*/sessions/*.jsonl`.
3. Cost **MUST** be computed from the agent's model pricing
   (`input:output:cacheWrite:cacheRead` per MTok).

### Budget caps

1. `docket profile <id> --budget <USD>` **MUST** store a `budgetUsd` cap in `.docket-meta.json`.
2. A cap of `0` **MUST** mean "no cap" and **MUST** clear any existing cap.
3. Setting a non-zero budget **MUST** clear a prior `paused` state.
4. The budget value **MUST** be a non-negative number.

### Runaway and pause

1. `docket doctor` **MUST** include a budget-and-runaway check across agents.
2. When an agent's accumulated cost reaches its cap, the agent **SHOULD** be marked
   `paused` with a human-readable `pausedReason`.
3. A paused agent **MUST** record why it was paused so the operator can act.

## Interface Contracts

### CLI Command Signatures

```bash
docket cost [agent-id] [--period <days>] [--by-model] [--csv]   # Usage and cost
docket profile <agent-id> --budget <USD>                        # Set/clear a cap (0 = none)
docket doctor                                                   # Includes budget/runaway check
```

### Return Codes

- `0`: Success
- `2`: Agent not found
- `4`: Invalid budget value

## Examples

### Reporting cost and setting a cap

```bash
$ docket cost mywebsite
  Input tokens:   50,000
  Output tokens:  25,000
                              Total:  $0.5300

$ docket profile mywebsite --budget 5
[SUCCESS] Budget cap set to $5 for 'mywebsite'.
```

## Validation

### Pre-conditions

- For `--budget`, the value **MUST** parse as a non-negative number.

### Post-conditions

- After `--budget <n>` with n>0, `.docket-meta.json` **MUST** contain `budgetUsd = n` and no
  `paused` flag.
- After `--budget 0`, no active cap **MUST** remain.

### Invariants

- Reported cost **MUST** be consistent with the agent's model pricing.
- A `paused` agent **MUST** always carry a `pausedReason`.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial cost-tracking specification
- Defined reporting, budget caps, and runaway/pause behavior
