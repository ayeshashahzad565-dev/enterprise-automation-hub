"""Observability primitives (Prometheus metrics) for the production
infrastructure layer.

Deliberately separate from ``app.config`` (which owns settings loading)
and ``app.api`` (which owns HTTP wiring): this package owns only metric
*definitions*, imported by both ``app.api.middleware`` (which records
them) and ``app.api.routers.metrics`` (which exposes them).
"""

from __future__ import annotations
