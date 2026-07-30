"""Routes for the ``ai`` resource: every AI-generated insight in the platform.

Thin wrappers over ``AiInsightService`` — see ``app.api.routers.search``'s
module docstring for the general convention this file follows (a real,
service-backed router, not the ``platform.py``-style "router-direct
repository access" exception).

Every route here additionally depends on ``enforce_ai_rate_limit`` (on top
of the general ``enforce_rate_limit`` applied at ``app.api.main``'s
``include_router`` call) since every one of them may invoke a paid,
multi-second external AI provider request.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_ai_insight_service, get_current_identity
from app.api.rate_limiting import enforce_ai_rate_limit
from app.api.schemas.ai import AiInsightOut, AskAssistantBody
from app.auth.authentication import AuthenticatedIdentity
from app.services.ai_insight_service import AiInsightService
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(enforce_ai_rate_limit)])


def _request_id_of(request: Request) -> str | None:
    """Read the correlation id ``RequestIDMiddleware`` attached to this request."""
    return getattr(request.state, "request_id", None)


@router.get("/requests/{request_id}/summary")
def get_request_summary(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Summarize a request. See ``AiInsightService.summarize_request``."""
    insight = service.summarize_request(identity, request_id)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/requests/{request_id}/approval-summary")
def get_approval_summary(
    request: Request,
    request_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Summarize a request for an approver deciding on it. See
    ``AiInsightService.summarize_approval``."""
    insight = service.summarize_approval(identity, request_id)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/workflows/{request_type}/improvements")
def get_workflow_improvements(
    request: Request,
    request_type: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Suggest improvements to a workflow's active version. See
    ``AiInsightService.suggest_workflow_improvements``."""
    insight = service.suggest_workflow_improvements(identity, request_type)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/operations/bottlenecks")
def get_bottleneck_explanation(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Explain the company's current bottlenecks. See
    ``AiInsightService.explain_bottlenecks``."""
    insight = service.explain_bottlenecks(identity)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/operations/policy-recommendations")
def get_policy_recommendations(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Recommend approval-policy changes. See
    ``AiInsightService.recommend_policies``."""
    insight = service.recommend_policies(identity)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/operations/insights")
def get_operational_insights(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Generate a broad operational-insights briefing. See
    ``AiInsightService.generate_operational_insights``."""
    insight = service.generate_operational_insights(identity)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/operations/executive-summary")
def get_executive_summary(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Generate an AI executive summary. See
    ``AiInsightService.generate_executive_summary``."""
    insight = service.generate_executive_summary(identity)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.post("/assistant/ask")
def ask_assistant(
    request: Request,
    body: AskAssistantBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: AiInsightService = Depends(get_ai_insight_service),
) -> dict[str, Any]:
    """Answer a natural-language question about the caller's own dashboard
    data. See ``AiInsightService.ask_assistant``."""
    history = [(turn.role, turn.content) for turn in body.history]
    insight = service.ask_assistant(identity, body.question, history)
    out = AiInsightOut.model_validate(insight)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
