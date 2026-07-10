"""Request list, detail, create, edit, and withdraw UI.

Per this package's design brief, every read and write on this page goes
through ``app.services.request_service.RequestService`` — no repository
is imported here, and no validation beyond input presence/shape is
performed in this module (structural and business validation is the
Domain Layer's and Application Layer's responsibility, surfaced here as
a flash message via ``components.run_with_feedback``).
"""

from __future__ import annotations

import logging

import streamlit as st

from app.database.repositories.base_repository import Page
from app.models.enums import RequestStatus

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)

_PAGE_KEY = "requests"


def render() -> None:
    """Render the requests page: list/search view, or a selected request's detail view."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None

    selected_id = session.get_cached_selection("selected_request_id")
    if selected_id is not None:
        navigation.render_breadcrumbs("Requests", "Details")
        _render_detail(selected_id)
        return

    navigation.render_breadcrumbs("Requests")
    st.markdown("## Requests")

    tab_list, tab_create = st.tabs(["Browse", "New Request"])
    with tab_list:
        _render_list()
    with tab_create:
        _render_create_form()


def _render_list() -> None:
    """Render the filterable, searchable, paginated request list."""
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    filters = session.get_filters(_PAGE_KEY)

    col_search, col_status, col_type = st.columns([2, 1, 1])
    with col_search:
        search_text = components.search_bar(_PAGE_KEY, placeholder="Search title or description...")
    with col_status:
        status_value = components.filter_select(
            "Status",
            [s.value for s in RequestStatus if s is not RequestStatus.APPROVED],
            key=f"{_PAGE_KEY}_status",
            current_value=filters.get("status"),
        )
    with col_type:
        type_value = st.text_input("Request Type", value=filters.get("request_type") or "")

    new_filters = {
        "search": search_text,
        "status": status_value,
        "request_type": type_value or None,
    }
    if new_filters != filters:
        session.set_filters(_PAGE_KEY, new_filters)
        session.reset_pagination(_PAGE_KEY)

    page_number, page_size = session.get_pagination(_PAGE_KEY)
    status_filter = RequestStatus(status_value) if status_value else None

    if search_text.strip():
        result = components.run_with_feedback(
            lambda: container.request_service.search_requests(
                identity, search_text.strip(), page=Page(number=page_number, size=page_size)
            ),
            loading_message="Searching requests...",
        )
    else:
        result = components.run_with_feedback(
            lambda: container.request_service.list_requests(
                identity,
                status=status_filter,
                request_type=type_value or None,
                page=Page(number=page_number, size=page_size),
            ),
            loading_message="Loading requests...",
        )

    if result is None:
        return

    if not result.items:
        components.empty_state("No requests match your filters.")
        return

    for request in result.items:
        col_info, col_status_badge, col_action = st.columns([4, 2, 1])
        with col_info:
            st.markdown(f"**{request.title}**")
            st.caption(f"{request.request_type} · Created {request.created_at.strftime('%Y-%m-%d')}")
        with col_status_badge:
            components.status_badge(request.status.value)
        with col_action:
            if st.button("View", key=f"view_{request.id}"):
                session.set_cached_selection("selected_request_id", request.id)
                st.rerun()
        st.divider()

    components.pagination_controls(_PAGE_KEY, total_pages=result.total_pages)


def _render_create_form() -> None:
    """Render the new-request creation form."""
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    with st.form("create_request_form"):
        request_type = st.text_input("Request Type", placeholder="e.g. expense_reimbursement")
        title = st.text_input("Title", max_chars=200)
        description = st.text_area("Description", max_chars=5000)
        department = st.text_input("Department (optional)")
        submitted = st.form_submit_button("Submit Request", type="primary")

    if not submitted:
        return

    if not request_type.strip() or not title.strip():
        session.push_flash("error", "Request type and title are required.")
        st.rerun()
        return

    created = components.run_with_feedback(
        lambda: container.request_service.create_request(
            identity,
            request_type=request_type.strip(),
            title=title.strip(),
            description=description.strip() or None,
            department=department.strip() or None,
        ),
        loading_message="Submitting your request...",
        success_message="Request submitted successfully.",
    )
    if created is not None:
        session.set_cached_selection("selected_request_id", created.id)
        st.rerun()


def _render_detail(request_id) -> None:
    """Render a single request's detail view, including edit and withdraw actions.

    Args:
        request_id: The id of the request to display.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    if st.button("← Back to list"):
        session.clear_cached_selection("selected_request_id")
        st.rerun()

    request = components.run_with_feedback(
        lambda: container.request_service.get_request(identity, request_id),
        loading_message="Loading request...",
    )
    if request is None:
        return

    st.markdown(f"## {request.title}")
    col_status, col_type = st.columns(2)
    with col_status:
        components.status_badge(request.status.value)
    with col_type:
        st.caption(f"Type: {request.request_type}")

    st.markdown(request.description or "_No description provided._")
    st.caption(
        f"Created {request.created_at.strftime('%Y-%m-%d %H:%M')} · "
        f"Department: {request.department or 'N/A'}"
    )

    is_owner = request.requester_id == identity.user_id
    is_pending = request.status is RequestStatus.PENDING

    if is_owner and is_pending:
        st.divider()
        components.section_header("Edit Request")
        with st.form("edit_request_form"):
            new_title = st.text_input("Title", value=request.title, max_chars=200)
            new_description = st.text_area(
                "Description", value=request.description or "", max_chars=5000
            )
            new_department = st.text_input("Department", value=request.department or "")
            save = st.form_submit_button("Save Changes")

        if save:
            updated = components.run_with_feedback(
                lambda: container.request_service.update_request(
                    identity,
                    request.id,
                    title=new_title.strip() or None,
                    description=new_description.strip() or None,
                    department=new_department.strip() or None,
                    expected_version=request.version,
                ),
                loading_message="Saving changes...",
                success_message="Request updated.",
            )
            if updated is not None:
                st.rerun()

        st.divider()
        if components.confirm_action("withdraw_request", label="Withdraw Request", danger=True):
            withdrawn = components.run_with_feedback(
                lambda: container.request_service.withdraw_request(
                    identity, request.id, expected_version=request.version
                ),
                loading_message="Withdrawing request...",
                success_message="Request withdrawn.",
            )
            if withdrawn is not None:
                st.rerun()