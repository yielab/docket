# Trace

## Requirements

1. Events are appended in order and never reordered.

## Implementation

- `src/docket/core/trace.py`: `record`, `EVENTS`
- `docket.core.trace.record` is the one writer.
- Tested by `tests/unit/core/test_trace.py`.
