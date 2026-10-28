# web-research

Lead -> (Researcher A | Researcher B | Researcher C, in parallel) -> Analyst -> Writer.

The Lead splits the question into sub-questions. Three Researchers run on the cheap model
class (`model: cheap` on each child step) with disjoint instructions: two work the web, the
third works the repository with `grep` and `read`. Each web Researcher searches through a
search server and reads the pages it picks with `fetch`. The pages stay in the Researcher's
own session; only its reply reaches the Analyst as a handoff. The Analyst and the Writer are
the built-in `analyst` and `writer` roles.

## Prerequisites

Two things must be in place before the web Researchers can work. Both are set by the
operator, not by this recipe.

1. The hosts whose pages the Researchers may read:

   ```bash
   FETCH_ALLOWED_DOMAINS=<hosts>
   ```

2. A search server, declared through MCP with `--kind read`. docket has no built-in search. The
   example below is a self-hosted SearXNG behind its MCP server: no vendor and no key, with
   the operator's own SearXNG host on the allowlist above.

   ```bash
   docket setup mcp add searxng --kind read -- <searxng-mcp-server-command>
   ```

   A hosted search API works through the same command, with its key in the secret store.

## Apply it

For a new pod, or onto one that already has its `lead`:

```bash
docket init --recipe web-research    # a new pod for the current directory
docket pod update web-research       # onto an existing pod
```

`pod.yaml` names the three members this recipe adds: `researcher`, `analyst` and `writer`.
`apply` validates the roster and `pipeline.yaml` before writing anything, and is safe to run
again (a second run plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - what `apply` reads: `members: [researcher, analyst, writer]`.
- `pipeline.yaml` - `lead` (Lead) -> `research` (parallel group: `web-a`, `web-b` and `repo`,
  all Researchers on `model: cheap`) -> `analyst` -> `writer`.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-analyst
docket pod remove <project>-writer
```
