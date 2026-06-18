# Documentation assets

| File | What it shows | Notes |
|------|---------------|-------|
| `hero.gif` | The core loop: provision an isolated agent → list the fleet → inspect isolation → fleet health, with a budget guardrail tail | Generated from [`hero.tape`](hero.tape) via `vhs` |
| `info.png` | `docket info` — per-project isolation (session key, workspace, codebase) | |
| `maintain.png` | `docket maintain <id> check` — health check & auto-fix | |
| `models.png` | `docket models` — role→model policy | |
| `cost.png` | `docket cost` — recorded spend + budget cap (the guardrail) | |

## Positioning rule for visuals

These assets must lead with **provisioning + isolation** and keep cost as a *guardrail*, not the
headline (see `internal-docs/COST-FEATURE-AUDIT.md`). When regenerating the hero GIF, do not make a
`docket cost` dollar table the centerpiece.

## Regenerating the hero GIF

```bash
vhs docs/assets/hero.tape   # writes docs/assets/hero.gif
```

Use only anonymized agent names (webapp / api / blog) — never real client names or local paths.
