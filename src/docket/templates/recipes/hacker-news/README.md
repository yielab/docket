# hacker-news

A team that watches Hacker News, keeps a record of its most commented stories with a summary and
the discussion of each, and reports on the last week and on everything it has recorded.

It runs on the `routine` blueprint (`docket init --blueprint routine`): Lead, Analyst, Writer and
Reviewer on a working directory. The recipe adds no member and no role. The Analyst collects and
summarises, the Writer writes the two report files and the Reviewer checks and cannot write.

## What it adds

- `services/hn.yaml` - the service `hn`, the public Hacker News search API at
  `https://hn.algolia.com/api/v1` (no key, host `hn.algolia.com`). Two `GET` operations, both
  read: `svc__hn__search` (the front page, or the stories since a date) and `svc__hn__comments`
  (the comments of one story). A service document cannot fix a query value, so each parameter is
  optional and the pipeline's instructions name the exact values; `attributesToHighlight=none` and
  `attributesToRetrieve` keep a response to a few kilobytes, which a small local model needs.
- `records/stories.yaml` - the set `stories`, keyed by the story's `id`: `title`, `url`, `points`,
  `comments`, `captured` (the day the story was posted), `summary` and `discussion`. A story already
  in the set is returned, not added again, so a second digest of the same page leaves one row each.
  The row's `_at` says when docket captured it.
- `pipelines/digest.yaml` - `docket task add "Digest the front page" --pipeline digest`. The Analyst
  reads the front page and adds the five most commented stories, then reads each story's comments and
  fills `summary` and `discussion` (what people agree on, dispute, and the notable objections). The
  Reviewer lists the newest rows with `rec__query` and answers APPROVE or REQUEST-CHANGES, with one
  rework.
- `routines/weekly-report.yaml` - on Mondays at 08:00 UTC (set `tz` for another zone) the service
  enqueues a task on the blueprint's own pipeline (compile -> draft -> review). The Analyst compiles
  with `rec__query`; the Writer exports the last seven days into `report.md` with `rec__export`,
  most commented first, with each story's summary and discussion, and writes `analysis.md` over
  everything the set holds. The service must be running (`docket start --dispatch`) for the routine
  to fire; the same text can be run once by hand with `docket task add`.

## Apply it

```bash
docket init --blueprint routine         # a new pod on a working directory
docket pod update hacker-news           # adds the service, the set, the pipeline and the routine
docket task add "Digest the front page" --pipeline digest
docket run
docket pod records stories              # the rows
```

`apply` validates every document before writing anything, and is safe to run again (a second run
plans every item `skip`). `--dry-run` prints the plan without writing.

## Limits

- The digest reads titles, points and the comments the API returns (8 per story); it does not open
  the linked article, so a summary rests on the title and on what the commenters explain.
- The service is reached by docket's own process, not the jail, and only on `hn.algolia.com`.
- The Hacker News search API is public and rate limited; the recipe makes about a dozen calls a digest.

## Files

- `pod.yaml` - what `apply` reads: a name and a description; no `members`.
- `services/hn.yaml`, `records/stories.yaml`, `pipelines/digest.yaml`, `routines/weekly-report.yaml` -
  described above.

## Undo

The rows stay in `records.sqlite` under the pod's directory in `DOCKET_HOME`. To stop the schedule
and the pipeline, delete `routines/weekly-report.yaml` and `pipelines/digest.yaml` from the pod's
`config/` directory; delete `services/hn.yaml` there to remove the service.
