# Dispatch

## Requirements

1. A task is claimed before its first hop runs.

## Implementation

- `core/dispatch.py::claim_next` claims; `core/dispatch.py::finish` closes.
- `docket.core.dispatch.run_hop` runs one hop.
