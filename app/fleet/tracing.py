"""Spans, so the reasoning chain is a chain and not a list of rows.

`events._current_trace_id()` has always read the ambient OpenTelemetry
span context correctly — but nothing in this codebase ever opened a
span, so every ledger row raised from the shift loop carried an
`untraced-*` id. The audit ledger said *what* happened; Cloud Trace
could not say what it happened *inside of*.

ADK sets the global tracer provider in `google/adk/telemetry/setup.py`
(reached from `get_fast_api_app(..., otel_to_cloud=...)`), so a tracer
acquired here exports through the same provider and ADK's own model-call
spans nest underneath ours for free. With no provider — unit tests, a
bare import — OpenTelemetry hands back a no-op tracer, spans cost
nothing, and `_current_trace_id()` falls back exactly as it does today.

Deliberately not spanned: the telemetry heartbeat. At 0.5 Hz across a
multi-day shift that is hundreds of thousands of empty spans, and the
ledger already excludes telemetry from persistence for the same reason.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

TRACER = trace.get_tracer("steward.fleet")


@contextmanager
def span(name: str, **attributes: Any):
    """Open a span, attach what matters, and let failures be visible.

    An exception is recorded and re-raised — a span that swallowed the
    error would be worse than no span, because the trace would claim
    success.
    """
    with TRACER.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            raise


def mark_failed(current, reason: str) -> None:
    """Fail a span without raising — for the outcomes that are decisions
    rather than errors, like a quarantine."""
    if current is not None:
        current.set_status(Status(StatusCode.ERROR, reason[:200]))
