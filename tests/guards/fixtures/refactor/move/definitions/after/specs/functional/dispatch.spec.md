# Dispatch

## Requirements

1. A task is claimed before its first hop runs.

## Implementation

- `tasks/claim.py::claim_next` claims; `core/dispatch.py::finish` closes.
- `docket.hops.runner.run_hop` runs one hop.
