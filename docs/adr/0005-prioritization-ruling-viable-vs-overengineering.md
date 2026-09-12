# ADR 0005 (D-24): Cutting half of Phases 20 and 21 as overengineering

**Question:** Phases 20/21 were drafted as "best practice for an agent platform". Under the answered goal (a factory for agentic products, D-20), which of those items are genuinely viable and which are overengineering?

**Where decided:** Phases 20/21, before either starts

## Decision

**Ruling 2026-07-31 — cut roughly half, and the cuts include the integrator's own earlier recommendations.** The full verdict table follows below. Headline: **OpenTelemetry (P20-1) is CUT**, having been proposed the same day as "the industry standard" — correct at platform scale, wrong at **one host and one operator** with JSONL traces and six Prometheus metrics already shipped. Also cut: **streaming (P21-2)** and the **tenant axis (P21-3)**, both of which only existed to serve the hosted-runtime reading D-20 rejected. Deferred: fleet trace query (P20-3), egress lockdown (D-23), build-agent profile (P21-4). Kept: the removal wave, per-role tool sets, the MCP CLI, the `fetch` tool, the package split, guardrail metrics, the `runs cancel` audit entry, and one new **XS** card — an `agentic-product` pod blueprint, which is *data in an existing registry*, not code. **The principle being applied is already written down** (§4.5, "we will NOT"): the test is not "is this best practice for someone", it is *"does a measured need in **this** system ask for it"*. It applies to the integrator's proposals exactly as it applies to a card's.

### Prioritization ruling — viable vs overengineering (2026-07-31, decision D-24)

**Context.** The goal was stated as **a factory for agentic products** (D-20). Phases 20 and 21 had
been drafted the same day from a generic "what a good agent platform has" reading. They were
re-scored against the answered goal and against §4.5's anti-overengineering test — *not* "is this
best practice for someone", but **"does a measured need in this system ask for it"**.

**Roughly half was cut, including items the integrator had recommended hours earlier.** That is the
point of writing the rule down: it has to bind the person applying it.

| Item | Verdict | Reason |
| --- | --- | --- |
| **P19-6 / P19-7** removal wave | **DO — first, nothing else counts until it lands** | The daemon still resolves `OpenClawDriver`. Every runtime claim is theoretical until this flips, and D-21 is explicitly forbidden before it |
| **P21-1** runtime package split | **DO — this *is* the factory's product line** | If every product is agentic, the runtime is the common part of every product. Packaging only (D-21 constraint 2) |
| **P19-12** per-role tool sets + identity | **DO** | Converts an *instruction* ("Reviewer, don't edit code") into a *guarantee* (the tool is absent). That distinction is the thing docket sells |
| **P19-13** `docket mcp servers` CLI | **DO — S** | ~30 lines of CLI over library functions P19-10 already shipped and tested. Makes browser + web search **configuration, not code** |
| **P19-11** `fetch` tool | **DO** | Table stakes for an agentic-product runtime, and the inspectable egress path |
| **P21-5** `agentic-product` blueprint | **DO — XS** | A row in `BUILTIN_BLUEPRINTS`. The scaffolding primitive a factory needs **already exists**; this is data, not machinery |
| **P20-4** `runs cancel` audit entry | ~~**DO — XS**~~ **ALREADY SHIPPED** | The gap it was written against had already been closed by W-4. Nothing to do; see the card below |
| **P20-2** guardrail + loop metrics | ☑ **SHIPPED** (2026-08-04) | Denial rate and approval wait are the two numbers an operator would actually open |
| **D-23** egress lockdown | **DEFER** | Off by default, breaks `npm`/`pip`/`git` when on, no measured need. Buys a config option, not a guarantee |
| **P20-3** fleet trace query + retention | **DEFER** | `grep` over JSONL is adequate at this fleet size. Retention returns when a disk fills, which is a fact, not a forecast |
| **P20-1 OpenTelemetry** | **CUT** | **Reversing the integrator's own recommendation.** Correct at platform scale; this is one host and one operator, with JSONL traces and six Prometheus metrics already shipped. Importing a platform-team solution into a one-operator system is textbook overengineering. Revisit at a second operator or a real dashboard |
| **P21-2** streaming | **CUT until a product asks** | Only served the hosted-runtime reading D-20 rejected. Agentic *backends* do not stream |
| **P21-3** tenant axis | **CUT — see D-22** | Same. An embedding product owns its own tenant model |
| **P21-4** build-agent profile | **DEFER** | Real the moment an Android/Unity product exists. Pre-building for a hypothetical product is the definition of speculative |
| Browser automation tooling | **NEVER BUILD** | Point MCP at Playwright. This is what "rent the protocol" was for |

**The single biggest overengineering risk in the plan as drafted** was Phase 21 read as a bundle —
packaging *plus* streaming *plus* a tenant axis. Packaging is the asset; the other two are a hosted
product nobody asked for.

---
