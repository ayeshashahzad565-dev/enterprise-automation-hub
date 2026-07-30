"""Routes for the authenticated caller's own Dashboard summary.

A thin wrapper over the already-built ``DashboardService
.get_dashboard_summary`` — no router previously exposed it (the same
"documented but unwired" gap this API layer has found and fixed in every
prior phase; the service itself already assembles
``RequestService``/``ApprovalService``/``NotificationService``/
``AnalyticsService`` results and applies its own least-privilege role
gating, so this handler adds no logic beyond calling it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_identity, get_dashboard_service
from app.api.schemas.dashboard import DashboardSummaryOut
from app.auth.authentication import AuthenticatedIdentity
from app.services.dashboard_service import DashboardService
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["dashboard"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/dashboard-summary")
def get_dashboard_summary(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: DashboardService = Depends(get_dashboard_service),
) -> dict[str, Any]:
    """The caller's dashboard summary. See ``DashboardService.get_dashboard_summary``."""
    summary = service.get_dashboard_summary(identity)
    out = DashboardSummaryOut.model_validate(summary)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
