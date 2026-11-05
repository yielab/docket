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
| Set up | `docket setup search searxng` | planned; until then add the service by hand with `docket setup service add` and a stored secret |

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

## Undo

```bash
docket pod unset pipeline
docket pod remove <project>-researcher
docket pod remove <project>-analyst
docket pod remove <project>-writer
docker rm -f docket-searxng           # the container, if you started it
```
