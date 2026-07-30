"""API-only request/response DTOs.

Every model here exists solely to shape an HTTP request or response body.
None of these types are consumed by any ``app.services`` method directly —
they either wrap an existing Application Service call's plain-Python
return value (a dataclass, in the case of ``app.api.schemas.workflow``/
``app.api.schemas.audit``) for JSON serialization, or carry an
HTTP-body-only field (``expected_version``) alongside fields an existing
domain model already validates. Reuse an existing ``app.models`` class
directly wherever its shape already matches the wire contract (as
``app.models.request.RequestCreate`` and ``app.models.comment.CommentCreate``
already do) — a new schema is added here only when no existing model's
shape fits, per the Phase 0/1 "introduce API-specific DTOs only when
actually needed" principle.
"""
