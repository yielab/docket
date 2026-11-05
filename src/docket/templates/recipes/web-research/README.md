# web-research

Lead -> (Researcher A | Researcher B | Researcher C, in parallel) -> Analyst -> Writer.

The Lead splits the question into sub-questions. Three Researchers run on the cheap model
class (`model: cheap` on each child step) with disjoint instructions: two work the web, the
third works the repository with `grep` and `read`. docket has no search tool of its own: the
pod declares a search service (`kind: service`, named `search`) and each web Researcher calls
its `svc__search__search` operation, then reads the pages it picks with `fetch`. A PDF among
them is read by docket's own interpreter inside the jail. The pages stay in the Researcher's own
session; only its reply reaches the Analyst as a handoff. The Analyst and the Writer are the
built-in `analyst` and `writer` roles.

## Search

A search site is not a search tool: measured on 2026-11-04, DuckDuckGo answered a challenge page to
20 of 20 queries and Bing returned links unrelated to the query. A pod searches through a service
it declares, and there are two ways to have one:

| | SearXNG (the default) | Brave Search API |
| --- | --- | --- |
| Cost | free | an API key |
| Runs | in Docker on this machine, `127.0.0.1:8888` | at the provider |
| Set up | `docket setup search searxng` | `docket setup search brave` (the key from a hidden prompt or `--stdin`) |

The recipe ships the SearXNG service, so `docket init --recipe web-research` and `docket pod update
web-research` already declare it in the pod (`services/search.yaml`). One command writes the
settings the container needs and prints the one line that starts it:

```bash
docket setup search searxng            # for the pod of the current directory; --pod NAME for another
docker run -d --name docket-searxng ...   # the line the command printed, with the real settings path
docket pod show                        # needs search-host: ready once the container answers
```

The command is safe to run again: it keeps the settings (and the key in them), leaves a matching
service document as it is and prints the line again. docket never starts or supervises the
container. The settings turn JSON output on and SearXNG's limiter off, because the instance
listens on the loopback only. One service named `search` per pod: a different provider replaces
`services/search.yaml`, so the pipeline does not change.

Limits: SearXNG forwards the query to public engines, which can throttle heavy use; a burst of
queries or a week of use has not been measured.

### Brave Search API (optional)

```bash
printf '%s' "$BRAVE_KEY" | docket setup search brave --stdin   # for the pod of the current directory; --pod NAME for another
docket pod show                        # needs search-host: ready (brave)
```

The command reads the key from a hidden prompt on a terminal or from `--stdin`, never from an
argument, stores it as the secret `brave-search` and writes `brave/services/search.yaml` as the
pod's `services/search.yaml`, replacing the SearXNG document: one service named `search` per
pod, so the pipeline does not change. The header `X-Subscription-Token` carries
`${secret:brave-search}`; the document holds the reference, never the key. The key never travels
over docket's HTTP API: a plan of record (Tack) sees the provider in the pod report (`search`) and
switches it by applying a directory whose `services/search.yaml` is the one it wants, and for
Brave the report's `fix` is the command to run on the machine (`docket setup secret set
brave-search --stdin`). `search-host` counts Brave as ready when that secret is stored; docket
makes no call to Brave to find out, because a probe would spend the key's quota. Switch back with
`docket setup search searxng`, which keeps the stored key.

**Brave's terms: what was verified and what was not (read 2026-11-05).** The pages were read with
a fetch tool that summarises them, so the quotes below are the tool's, each under 125
characters, not a copy of the page.

- Verified: the API terms (api-dashboard.search.brave.com/terms-of-service) are headed "Last
  updated: 1 Sep, 2026". Section 3(b)(i) lists, among what the customer may not do: "store, cache,
  or create a database of Search Results, in whole or in part, other than transient storage".
  Section 3(b)(xiii) lists using the Search Results "to create, evaluate, train, re-train,
  fine-tune, benchmark or otherwise improve" AI models or services. Section 13(c)(ii) requires
  destroying Search Results on termination "(except as otherwise provided in an Order Form)".
- Verified: brave.com/search/api answers whether results may be stored with "Yes, with a plan that
  includes storage rights.", and links no API-specific terms of its own.
- Not verified: which plans include storage rights (the pricing documentation page rendered
  without its plan details), and the exact wording of the transient-storage allowance, which the
  tool paraphrased. The page's prices and free credit read differently in different sections, so
  none is repeated here: read brave.com/search/api before you subscribe.
- Not decided by anyone: whether docket's use fits "transient storage". docket keeps a tool
  result after the turn that made it: it stays in the Researcher's session, so it is in the
  context of the next turns, and it is written to the task's trace until trace retention removes
  it (an exporter you enabled at a privacy level that carries tool output would receive it too).
  Under the terms as read, that is storage beyond a single turn unless your plan has storage
  rights or an Order Form says otherwise. docket does not train or evaluate a model on results.
  Read the terms and your plan before running a production research team on Brave. SearXNG
  involves no Brave term; the public engines it queries have their own.

## Prerequisites

Three things must be in place before the web Researchers can work. A team that works in a folder
(the `respond` blueprint) needs only the third, isolation: under the jail it reads any public host with
no list. A team on a repository needs hosts as well. All are set by the operator,
not by this recipe, and `pod.yaml` declares them as `needs:` so `docket init --recipe` and
`docket pod update` print which are still missing, each with the one command that fixes it.

1. The hosts whose pages the Researchers may read (ADR 0036 decision 17), for a team on a
   repository or one whose jail does not run. `fetchDomains` replaces the pod's list, so give the whole list:

   ```bash
   docket pod set fetchDomains '*.wikipedia.org,docs.python.org'
   ```

   `*.wikipedia.org` covers every subdomain but not the apex. The search service is reached by
   docket's own process, not by `fetch`, so its host is not listed here.

2. A search service that answers (the section above). `search-host` is met only when the service
   named `search` is declared and a `GET` of its base URL gets an answer within two seconds; it
   never blocks an apply, and the pages the agent already knows still read without it.

3. Isolation on, which PDFs need because docket reads them in the jail:

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
`apply` validates the roster, `services/search.yaml` and `pipeline.yaml` before writing anything,
and is safe to run again (a second run plans every item `skip`). `--dry-run` prints the plan
without writing.

## Files

- `pod.yaml` - what `apply` reads: `members: [researcher, analyst, writer]` and
  `needs: [fetch-hosts, search-host, isolation]`.
- `pipeline.yaml` - `lead` (Lead) -> `research` (parallel group: `web-a`, `web-b` and `repo`,
  all Researchers on `model: cheap`) -> `analyst` -> `writer`.
- `services/search.yaml` - the service `search`: one `GET /search` operation (`q`, `format=json`),
  access `read`, on `http://127.0.0.1:8888`. Applied into the pod.
- `searxng/settings.yml` - the settings the SearXNG container reads. Not applied: `docket setup
  search searxng` copies it under the home with a random `secret_key`.
- `brave/services/search.yaml` - the same service for the Brave Search API (`q`, `count`; access
  `read`). Not applied: `docket setup search brave` copies it into the pod.

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-analyst
docket pod remove <project>-writer
docker rm -f docket-searxng           # the container, if you started it
docket setup secret remove brave-search   # the Brave key, if you stored one
```
