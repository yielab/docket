# ADR 0003 (D-20): A factory for agentic products, and the substrate it outputs

**Question:** **The company will ship agentic products, and wants docket as its main orchestrator. Is docket (a) the factory that builds those products, (b) the runtime the products themselves ship on, or both?**

**Where decided:** Phase 20/21 (blocks their scope)

## Decision

**ANSWERED 2026-07-31 — both, in a stated order, by the user's goal statement: "a factory for agentic products."** The reasoning is short and load-bearing: *if every product is agentic, the runtime is the common part of every product*, so the factory's highest-value output is not agent-written code, it is a **reusable substrate**. Order: **(a) factory first** — it exists today and Phase 19 finishes it; **(b) substrate second** — Phase 21 packaging (D-21), which each product *embeds as a library*. **What this answer explicitly does NOT buy:** the hosted-SaaS half of (b). Multi-tenancy, authn/authz for external callers, queues/workers, streaming and per-customer quota stay **out of scope** — an embedding product owns its own serving layer, and docket owns the gated loop inside it. That distinction is what keeps this answer cheap; conflating "embeddable library" with "hosted product runtime" is the failure mode this decision exists to prevent, and it is why D-22 and P21-2/P21-3 are cut rather than unblocked. Measured fact that makes the packaging cheap: the whole runtime slice (`core/llm`, `core/tools`, `core/session`, `core/agent_loop`, `core/policy`, `core/approval`, `core/security`, `core/audit`, `core/trace`, their adapters and `edges/store`) imports exactly **two** third-party packages, `pydantic` and `filelock` — no typer, no rich, no `ui`. The layering discipline already paid for the extraction.
