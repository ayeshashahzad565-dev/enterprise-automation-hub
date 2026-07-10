"""Pending approvals, stage details, approve/reject actions, and comments.

Per this package's design brief, every decision on this page goes
through ``app.services.approval_service.ApprovalService`` — this module
contains no workflow decision logic and no optimistic-locking logic of
its own; a ``ConcurrencyError`` raised by the service (because the stage
was decided by someone else since this page last loaded it) is caught by
``components.run_with_feedback`` and surfaced as a flash message
instructing the user to refresh.

Two capability gaps in the finalized Application Service Layer shape
this page's design, both handled honestly rather than with a fake
implementation:

- **No service exposes "fetch a single stage by id."**
  ``ApprovalService`` only exposes ``list_pending_approvals`` (the
  caller's own queue) and the decision methods. This page therefore
  caches the *full* ``WorkflowStage`` object selected from the queue
  listing (which already carries every field this page needs), rather
  than caching only an id and attempting a lookup that no service
  supports.
- **No service exposes "list every stage for a request."** A workflow
  history/timeline for the parent request cannot be shown; this is
  stated explicitly in the UI rather than silently omitted.

**Comments are not available on this page**, for the same reason: no
``CommentService`` or comment persistence layer exists anywhere in the
finalized architecture.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.database.repositories.base_repository import Page
from app.models import WorkflowStage
from app.models.enums import StageStatus

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)

_PAGE_KEY = "approvals"
_SELECTION_KEY = "selected_pending_stage"


def render() -> None:
    """Render the approvals page: pending queue, or a selected stage's detail view."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.guard_role(identity, *_allowed_roles())

    selected_stage: WorkflowStage | None = session.get_cached_selection(_SELECTION_KEY)
    if selected_stage is not None:
        navigation.render_breadcrumbs("Approvals", "Stage Detail")
        _render_stage_detail(selected_stage)
        return

    navigation.render_breadcrumbs("Approvals")
    st.markdown("## Pending Approvals")
    _render_queue()


def _allowed_roles() -> tuple:
    """Return the roles permitted on this page.

    Returns:
        The tuple of allowed ``UserRole`` values, sourced from this
        page's own navigation entry to avoid restating the list twice.
    """
    for item in navigation.NAV_ITEMS:
        if item.key == _PAGE_KEY:
            return item.allowed_roles or ()
    return ()


def _render_queue() -> None:
    """Render the caller's pending approval stages."""
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    page_number, page_size = session.get_pagination(_PAGE_KEY)
    result = components.run_with_feedback(
        lambda: container.approval_service.list_pending_approvals(
            identity, page=Page(number=page_number, size=page_size)
        ),
        loading_message="Loading pending approvals...",
    )
    if result is None:
        return

    if not result.items:
        components.empty_state("You have no pending approvals.", icon="✅")
        return

    for stage in result.items:
        col_info, col_action = st.columns([4, 1])
        with col_info:
            st.markdown(f"**{stage.stage_name}** (order {stage.stage_order})")
            st.caption(f"Request `{stage.request_id}` · Created {stage.created_at.strftime('%Y-%m-%d')}")
        with col_action:
            if st.button("Review", key=f"review_{stage.id}"):
                # Cache the fully-loaded stage object itself — no service
                # exposes a "fetch a single stage by id" lookup, per this
                # module's docstring, so the queue result is the only
                # source of this data available to this page.
                session.set_cached_selection(_SELECTION_KEY, stage)
                st.rerun()
        st.divider()

    components.pagination_controls(_PAGE_KEY, total_pages=result.total_pages)


def _render_stage_detail(stage: WorkflowStage) -> None:
    """Render a single pending stage's detail view with approve/reject actions.

    Args:
        stage: The cached stage to display, as selected from the queue.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    if st.button("← Back to queue"):
        session.clear_cached_selection(_SELECTION_KEY)
        st.rerun()

    parent_request = components.run_with_feedback(
        lambda: container.request_service.get_request(identity, stage.request_id),
        loading_message="Loading request details...",
    )
    if parent_request is None:
        return

    st.markdown(f"## {stage.stage_name}")
    components.status_badge(stage.status.value)
    st.caption(f"Belongs to request: **{parent_request.title}** ({parent_request.request_type})")
    st.markdown(parent_request.description or "_No description provided._")

    st.divider()
    components.section_header("Workflow History")
    st.info(
        "A full stage-by-stage workflow history is not available on this page. "
        "No Application Service currently exposes a 'list every stage for a request' "
        "read operation."
    )

    if stage.status is not StageStatus.PENDING:
        st.info("This stage has already been decided.")
        _render_comments_unavailable_notice()
        return

    st.divider()
    components.section_header("Decision")
    decision_note = st.text_area("Decision note", key=f"note_{stage.id}")

    col_approve, col_reject = st.columns(2)
    with col_approve:
        if st.button("Approve", type="primary", key=f"approve_{stage.id}"):
            outcome = components.run_with_feedback(
                lambda: container.approval_service.approve_stage(
                    identity,
                    stage.id,
                    expected_version=stage.version,
                    decision_note=decision_note.strip() or None,
                ),
                loading_message="Recording approval...",
                success_message="Stage approved.",
            )
            if outcome is not None:
                session.clear_cached_selection(_SELECTION_KEY)
                st.rerun()
    with col_reject:
        if st.button("Reject", key=f"reject_{stage.id}"):
            if not decision_note.strip():
                session.push_flash("error", "A decision note is required to reject a stage.")
                st.rerun()
            else:
                outcome = components.run_with_feedback(
                    lambda: container.approval_service.reject_stage(
                        identity,
                        stage.id,
                        expected_version=stage.version,
                        decision_note=decision_note.strip(),
                    ),
                    loading_message="Recording rejection...",
                    success_message="Stage rejected.",
                )
                if outcome is not None:
                    session.clear_cached_selection(_SELECTION_KEY)
                    st.rerun()

    st.caption(
        "If this action fails with a conflict, another approver may have already "
        "decided this stage — return to the queue and refresh."
    )

    st.divider()
    _render_comments_unavailable_notice()


def _render_comments_unavailable_notice() -> None:
    """Render an honest notice that comments are not available.

    No ``CommentService`` or comment persistence exists in the finalized
    architecture (see this module's docstring), so this section states
    that plainly rather than presenting a non-functional form.
    """
    components.section_header("Comments")
    st.info(
        "Comments are not available in this build. No comment persistence layer "
        "or Application Service exists in the current architecture to support them."
    )