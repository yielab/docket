# Multi-agent roadmap delivery

Read this only when two or more agents may plan, implement, review, or integrate cards
concurrently. Ordinary single-card work does not need it.

## Coordinator contract

One coordinator owns scheduling and shared truth. Before spawning workers:

1. Run the bounded snapshot. If Git status is unknown/clipped, obtain the full read-only status.
2. Extract each candidate with `scripts/card_packet.py <CARD-ID>`; do not send the active section or
   whole board.
3. Build a conflict graph over owning spec, files/functions, persisted state, mutable endpoint,
   worktree, temp/cache paths, and central rollups.
4. Claim only cards with satisfied dependencies and disjoint ownership. Set one owner per card.
5. Keep `ROADMAP.md`, `TODO.md`, `README.md`, `specs/README.md`, generated counts/indexes, and
   release/live-environment decisions coordinator-owned unless the board explicitly says otherwise.

Unknown or clipped state is not parallel-safe. Similar card titles do not imply conflict, and
different files do not prove independence when both mutate the same registry, endpoint, or schema.

## Worker isolation

Every mutating worker gets:

- one card, branch, worktree, and base commit;
- unique `DOCKET_HOME`, temp root, cache, ports, and deterministic fake endpoint;
- exact allowed files/functions and explicit forbidden/shared paths;
- one owning spec section, neighboring tests, and live callers;
- the RED command, focused gates, full gates, dependency, and merge order.

Use a minimal-context spawn when the packet plus repository locators is self-contained. Do not send
the coordinator conversation, audit narrative, market research, unrelated card prose, or raw logs.
The worker reopens authoritative sources through the supplied locators.

A worker stops at its card boundary. An adjacent defect becomes a locator in `Later follow-ups`; it
does not silently expand scope. If implementation needs a forbidden/shared path, return the
contention rather than editing it.

## Start packet

```text
Card / owner / base commit / worktree:
Decision and trigger locators:
Goal / non-goals:
Allowed files and functions:
Forbidden/shared files and mutable state:
Owning spec section and neighboring tests:
RED command and expected pre-fix failure:
Focused gates / final gates:
Dependency and merge order:
```

This packet points to the selected TODO card; it does not copy it. If a durable phase handoff is
linked from the card, send that link and its relevant section rather than the whole file.

## Worker return

Return a delta, not a replay. Target 1,500–3,000 UTF-8 characters; exceed that only when a
correctness-critical unresolved issue cannot be located safely by path/test/artifact id.

```text
Card / owner / commit:
Outcome: complete | partial | blocked
User-visible behavior:
Changed paths and owned functions:
Spec version/status/changelog:
Acceptance oracles:
Focused tests: <command> -> <compact result>
Full gates: <command group> -> <compact result or not run>
Missing / failed:
Pending in this card:
Later follow-ups:
Merge order / contention / mutable-state note:
Next ideal action:
```

Use paths, test node ids, artifact hashes, trace/run ids, or preserved fixture locations instead of
embedded output. Include only the first actionable failure and whether it reproduces on the base.
Never claim token/byte reduction as measured without before/after evidence.

## Integration

The coordinator reviews one commit at a time:

1. Confirm declared ownership and spec-first/RED evidence.
2. Compare every acceptance, failure/no-op, side-effect, and rollback oracle with the card.
3. Merge in dependency order. Resolve central rollups by regenerating ground truth, not choosing a
   branch side.
4. Run focused cross-card tests after each merge and the full required gates once per integrated
   batch.
5. Update board/roadmap status only after merged evidence passes, then rerun the snapshot.

Stop a batch for an unexplained dirty path, ambiguous board, ownership collision, failed required
gate, incompatible persisted contract, or shared mutable endpoint. Record a blocker once and ask
for the exact missing authority; do not spend context repeatedly rediscovering it.
