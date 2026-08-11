"""Routes for the ``workflow-definitions`` resource: the Workflow
Designer's admin-side authoring/versioning/activation surface.

Every handler is a thin wrapper over ``WorkflowDefinitionService``'s
existing methods (``create_definition``, ``update_draft``,
``activate_version``, ``list_versions``, ``search_definitions``) — the
service itself already enforces every RBAC/validation rule (admin-only
for mutations; non-admins see active-only results for reads), so no
authorization or business logic is duplicated here. This router was
previously only documented (``docs/api_design.md`` Section 19.9) but
never wired to a router file — the same "documented but unbuilt" gap
every prior phase has found once.

There is no ``GET /workflow-definitions/{id}``: ``list_versions``/
``search_definitions`` already embed each version's complete
``definition`` document inline, so the frontend never needs a separate
single-fetch — a deep-linked version page just re-lists its known
``request_type`` and finds the matching version client-side.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import get_current_identity, get_workflow_definition_service
from app.api.schemas.workflow_definitions import (
    CreateWorkflowDefinitionBody,
    UpdateWorkflowDefinitionBody,
    WorkflowDefinitionOut,
)
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.services.exceptions import ValidationError
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["workflow-definitions"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/workflow-definitions")
def list_workflow_definitions(
    request: Request,
    request_type: str | None = Query(None, max_length=200),
    query_text: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: WorkflowDefinitionService = Depends(get_workflow_definition_service),
) -> dict[str, Any]:
    """List versions for one request type, or free-text search across request
    types. See ``WorkflowDefinitionService.list_versions``/``search_definitions``.
    """
    page_obj = Page(number=page, size=page_size)
    if request_type is not None:
        result = service.list_versions(identity, request_type, page=page_obj)
    elif query_text is not None:
        result = service.search_definitions(identity, query_text, page=page_obj)
    else:
        raise ValidationError("Either 'request_type' or 'query_text' is required.")

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(WorkflowDefinitionOut.model_validate(d)) for d in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.post("/workflow-definitions", status_code=201)
def create_workflow_definition(
    request: Request,
    body: CreateWorkflowDefinitionBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: WorkflowDefinitionService = Depends(get_workflow_definition_service),
) -> dict[str, Any]:
    """Create a new, inactive workflow definition version. Admin only.
    See ``WorkflowDefinitionService.create_definition``.
    """
    created = service.create_definition(
        identity,
        request_type=body.request_type,
        definition=body.definition.model_dump(mode="json"),
    )
    out = WorkflowDefinitionOut.model_validate(created)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.patch("/workflow-definitions/{definition_id}")
def update_workflow_definition_draft(
    request: Request,
    definition_id: UUID,
    body: UpdateWorkflowDefinitionBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: WorkflowDefinitionService = Depends(get_workflow_definition_service),
) -> dict[str, Any]:
    """Edit a not-yet-activated workflow definition. Admin only.
    See ``WorkflowDefinitionService.update_draft``.
    """
    updated = service.update_draft(
        identity, definition_id, definition=body.definition.model_dump(mode="json")
    )
    out = WorkflowDefinitionOut.model_validate(updated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.delete("/workflow-definitions/{definition_id}", status_code=204)
def delete_workflow_definition_draft(
    definition_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: WorkflowDefinitionService = Depends(get_workflow_definition_service),
) -> Response:
    """Delete a not-yet-activated workflow definition. Admin only.
    See ``WorkflowDefinitionService.delete_draft``.
    """
    service.delete_draft(identity, definition_id)
    return Response(status_code=204)


@router.post("/workflow-definitions/{definition_id}/activate")
def activate_workflow_definition(
    request: Request,
    definition_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: WorkflowDefinitionService = Depends(get_workflow_definition_service),
) -> dict[str, Any]:
    """Activate a workflow definition version. Admin only.
    See ``WorkflowDefinitionService.activate_version``.
    """
    activated = service.activate_version(identity, definition_id)
    out = WorkflowDefinitionOut.model_validate(activated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))
