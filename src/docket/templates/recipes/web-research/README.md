# web-research

Lead -> (Researcher A | Researcher B | Researcher C, in parallel) -> Analyst -> Writer.

The Lead splits the question into sub-questions. Three Researchers run on the cheap model
class (`model: cheap` on each child step) with disjoint instructions: two work the web, the
third works the repository with `grep` and `read`. docket has no search tool: a search site is
a host. Each web Researcher fetches a search page from an allowed search site (for example
`https://html.duckduckgo.com/html/?q=...`) and then reads the pages it picks with `fetch`. A PDF
among them is read by docket's own interpreter inside the jail. The pages stay in the
Researcher's own session; only its reply reaches the Analyst as a handoff. The Analyst and the
Writer are the built-in `analyst` and `writer` roles.

## Prerequisites

Three things must be in place before the web Researchers can work. All are set by the operator,
not by this recipe, and `pod.yaml` declares them as `needs:` so `docket init --recipe` and
`docket pod update` print which are still missing, each with the one command that fixes it.

1. The hosts whose pages the Researchers may read, and a search site among them (ADR 0036
   decision 17). `fetchDomains` replaces the pod's list, so give the whole list:

   ```bash
   docket pod set fetchDomains 'html.duckduckgo.com,*.wikipedia.org'
   ```

   `*.wikipedia.org` covers every subdomain but not the apex. A search API with a key is a
   declared service instead (`kind: service`, added with `docket setup service add`), which also satisfies the
   search check.

2. Isolation on, which PDFs need because docket reads them in the jail:

   ```bash
   docket setup sandbox on
   ```

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

- `pod.yaml` - what `apply` reads: `members: [researcher, analyst, writer]` and
  `needs: [fetch-hosts, search-host, isolation]`.
- `pipeline.yaml` - `lead` (Lead) -> `research` (parallel group: `web-a`, `web-b` and `repo`,
  all Researchers on `model: cheap`) -> `analyst` -> `writer`.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-analyst
docket pod remove <project>-writer
```
