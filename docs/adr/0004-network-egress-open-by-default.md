# ADR 0004 (D-23): Network egress stays open, and the docs say so

**Question:** Network egress for agent tool calls: open by default, or closed with an allowlisted `fetch` tool?

**Where decided:** Phase 19 P19-11

## Decision

**Open by default, lockdown opt-in** (integrator's call, reversible config; say so if you disagree). Measured 2026-07-31: `curl`/`wget` correctly ask, but `python3 -c "import urllib..."`, `node`, and `git clone <url>` are all **allowed unattended** — `python3` and `node` are universal escape hatches on the curated allowlist, so **network egress is effectively ungated today**, and P19-9's sandbox does not close it either (both backends leave the network reachable). Closing egress by default breaks `npm install`, `pip` and `git clone`, which is why the default stays open; P19-11 ships an always-available, domain-allowlisted `fetch` tool so there is an inspectable path that does not require the escape hatch. **Re-scoped 2026-07-31 (prioritization ruling; Phase 19 record in `docs/cycles-ended/roadmap-phases.md`):** P19-11 ships **the `fetch` tool only**. The opt-in lockdown mechanism (`--network none` / `--unshare-net`) is **deferred** — it is a knob that is off by default, that breaks the three commands agents use most when turned on, and that no measured need has asked for. It buys a *config option*, not a guarantee. **Say the true thing in the docs instead**: egress is open, `fetch` is the inspectable path, and the escape hatches are known and named. An honestly-open gate beats a gate that reads as closed. Re-open when a product needs an actually-network-isolated agent.
