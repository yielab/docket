---
kind: prompt
name: history
description: The summarizer's instruction when a session's older turns are replaced by one summary.
version: 1.0.0
layer: compaction
for: any
modelClass: any
inputs:
  label: string
  turns: text
---
You are compacting durable turn history for '${label}'. Your summary replaces the turns below and is the only memory the next request has of them, so keep what a later turn needs, including the outcome of every tool call, and add nothing the turns do not say.

Write these sections in this order. A section with nothing to say is one line saying so.

## Objective and current state
## Decisions taken and why
## Files touched
One line per file: path: what changed.
## Commands run and their result
## Errors seen and whether resolved
## Open items and the next step

Turns, oldest first:

${turns}

Reply with the sections only.
