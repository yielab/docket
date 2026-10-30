# records

A set, a capture pipeline and a weekly report for a pod on the `routine` blueprint.

The `routine` blueprint (`docket init --blueprint routine`) is Lead, Analyst, Writer and Reviewer on a
working directory, with the pipeline compile -> draft -> review. It keeps nothing between runs until a
set is declared; this recipe declares one and ships the two ways to use it. It adds no member and no
role, because the blueprint has them. Applied to a pod on another blueprint it still validates, but the
roster it names (`analyst`, `reviewer`, and a writer for the report) is the `routine` one.

## What it adds

- `records/entries.yaml` - the set `entries`: `ref` (the key), `title` and `amount`. `pod update`
  creates the table in the pod's `records.sqlite`; edit the columns to fit your data. It only ever adds
  a column, never removes, renames or retypes one.
- `pipelines/capture.yaml` - `docket task add "<entries>" --pipeline capture`. The Analyst adds a
  row for each entry in the task's input with `rec__entries__add`; a repeated `ref` returns the row
  that exists, so a resumed hop that repeats its call writes once. The Reviewer counts the rows this
  task added with `rec__query` against the input and answers APPROVE or REQUEST-CHANGES. The Reviewer
  denies `write`, which covers every record write, so it can check the set and never change it.
- `routines/weekly-report.yaml` - on Mondays at 08:00 UTC (set `tz` for another zone) the service enqueues a task on the blueprint's
  own pipeline. The Writer exports the set into `report.md` with `rec__export`, without the rows
  passing through the model. Change `schedule` or the description to suit; the service must be running
  (`docket start --dispatch`) for a routine to fire.

## Apply it

```bash
docket init --blueprint routine         # a new pod on a working directory
docket pod update records               # adds the set, the pipeline and the routine
docket pod records entries              # the rows, once a task has added some
```

`apply` validates every document before writing anything, and is safe to run again (a second run
plans every item `skip`). `--dry-run` prints the plan without writing.

## Files

- `pod.yaml` - what `apply` reads: a name and a description; no `members`.
- `records/entries.yaml`, `pipelines/capture.yaml`, `routines/weekly-report.yaml` - described above.

## Undo

The rows are the pod's own data and stay in `records.sqlite` under the pod's directory in
`DOCKET_HOME`. To stop the schedule and the pipeline, delete `routines/weekly-report.yaml` and
`pipelines/capture.yaml` from the pod's `config/` directory.
