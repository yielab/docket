# Model Profiles Specification

**Version**: 1.0.0
**Status**: Complete
**Last Updated**: 2026-06-09

## Purpose

This specification defines the tiered model profiles that let an operator trade cost against
capability per agent, and how a profile maps to a concrete model id and pricing.

## Scope

This specification covers:

- The three profile tiers and the models they resolve to
- Setting and showing an agent's profile (`rack profile`)
- The pricing table used for cost estimation

This specification does NOT cover cost accumulation or budget caps (see cost-tracking.spec.md).

## Requirements

### Profile tiers

1. Exactly three tiers **MUST** be supported, each mapping to one model id:
   - `economy` → `anthropic/claude-haiku-4-5`
   - `standard` → `anthropic/claude-sonnet-4-6` (default)
   - `premium` → `anthropic/claude-opus-4-6`
2. Each model **MUST** have a pricing entry in USD per million tokens, expressed as
   `input:output:cacheWrite:cacheRead`.
3. A model that is not one of the three profile models **MUST** be reported as `custom`.

### Setting a profile (rack profile)

1. `rack profile <id> <tier>` **MUST** set the agent's model to the tier's model id and
   restart the gateway.
2. `rack profile <id>` with no tier **MUST** display the current model, profile, and budget.
3. An invalid tier **MUST** fail with return code 4.

## Interface Contracts

### CLI Command Signatures

```bash
rack profile <agent-id> [economy|standard|premium]   # Set or show profile
rack profile <agent-id> --budget <USD>               # Set a spend cap (see cost-tracking)
```

### Pricing Table (USD per MTok)

| Tier | Model | Input | Output |
|------|-------|-------|--------|
| economy | claude-haiku-4-5 | 0.80 | 4.00 |
| standard | claude-sonnet-4-6 | 3.00 | 15.00 |
| premium | claude-opus-4-6 | 15.00 | 75.00 |

### Return Codes

- `0`: Success
- `2`: Agent not found
- `4`: Invalid tier

## Examples

### Setting and showing a profile

```bash
$ rack profile mywebsite economy
[SUCCESS] Profile set to 'economy' (claude-haiku-4-5) for 'mywebsite'

$ rack profile mywebsite
  Model:       anthropic/claude-haiku-4-5
  Profile:     economy
  Budget cap:  none
```

## Validation

### Pre-conditions

- The target agent **MUST** exist.

### Post-conditions

- After setting a tier, `.rack-meta.json` `model` **MUST** equal the tier's model id and the
  gateway **MUST** have been restarted.

### Invariants

- A tier **MUST** always resolve to exactly one model id.
- Pricing **MUST** exist for every profile model.

## Changelog

### Version 1.0.0 (2026-06-09)

- Initial model-profiles specification
- Defined the three tiers, their models, and the pricing table
