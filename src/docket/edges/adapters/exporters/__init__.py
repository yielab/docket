"""Wire adapters for observability export.

Each module here is the only place in docket that knows one destination's wire
format; ``core/telemetry.py``'s ``Span``/``SpanEvent`` model stays vendor-free.
"""

from __future__ import annotations
