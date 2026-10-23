# Trace

## Requirements

1. Events are appended in order and never reordered.

## Implementation

- `src/docket/observe/trace.py`: `record`, `EVENTS`
- `docket.observe.trace.record` is the one writer.
- Tested by `tests/unit/observe/test_trace.py`.
