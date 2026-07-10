"""Reusable Streamlit UI components.

Per this package's design brief, every visual pattern repeated across
more than one page — tables, status badges, metric cards, confirmation
dialogs, pagination controls, search bars, filter panels, a workflow
timeline, loading indicators, and empty states — is implemented exactly
once here. No page module in this package re-implements any of these.

This module also defines ``run_with_feedback``, the single place every
page's "call an Application Service, show a spinner, translate any
exception into a flash message" pattern is implemented, since that
pattern is by far the most frequently repeated piece of logic across
every page in this package.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal, Sequence, TypeVar

import streamlit as st

from app.analytics.exceptions import AnalyticsError
from app.auth.exceptions import AuthError
from app.models import WorkflowStage
from app.models.enums import RequestStatus, StageStatus
from app.notifications.exceptions import NotificationError
from app.services.exceptions import EAHError
from app.workflow.exceptions import WorkflowError as EngineWorkflowError

from app.pages import session

__all__ = [
    "flash_messages",
    "run_with_feedback",
    "status_badge",
    "metric_card",
    "render_table",
    "confirm_action",
    "pagination_controls",
    "search_bar",
    "filter_select",
    "workflow_timeline",
    "empty_state",
    "section_header",
]

logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT")

#: Visual tone applied to each status value this application produces.
_STATUS_TONE: dict[str, Literal["success", "warning", "danger", "info", "neutral"]] = {
    RequestStatus.PENDING.value: "warning",
    RequestStatus.IN_REVIEW.value: "info",
    RequestStatus.APPROVED.value: "success",
    RequestStatus.COMPLETED.value: "success",
    RequestStatus.REJECTED.value: "danger",
    StageStatus.PENDING.value: "warning",
    StageStatus.APPROVED.value: "success",
    StageStatus.REJECTED.value: "danger",
    StageStatus.SKIPPED.value: "neutral",
}

_TONE_COLOR: dict[str, str] = {
    "success": "#1a7f37",
    "warning": "#9a6700",
    "danger": "#cf222e",
    "info": "#0969da",
    "neutral": "#6e7781",
}

_TONE_BACKGROUND: dict[str, str] = {
    "success": "#dafbe1",
    "warning": "#fff8c5",
    "danger": "#ffebe9",
    "info": "#ddf4ff",
    "neutral": "#eef0f2",
}


def flash_messages() -> None:
    """Render and clear every currently queued flash message.

    Intended to be called once, at the top of every page's ``render``
    function, before any other content.
    """
    for message in session.drain_flash_messages():
        if message.level == "success":
            st.success(message.text)
        elif message.level == "error":
            st.error(message.text)
        elif message.level == "warning":
            st.warning(message.text)
        else:
            st.info(message.text)


def run_with_feedback(
    action: Callable[[], ResultT],
    *,
    loading_message: str,
    success_message: str | None = None,
) -> ResultT | None:
    """Invoke an Application Service call with a spinner and unified error handling.

    Every exception type raised by the finalized service layers this
    package depends on (``app.services``, ``app.auth``,
    ``app.notifications``, ``app.analytics``, ``app.workflow``) is
    caught here and translated into a queued flash message, so that no
    individual page needs its own ``try``/``except`` block around a
    service call.

    Args:
        action: A zero-argument callable performing the Application
            Service call.
        loading_message: The message shown in the spinner while
            ``action`` runs.
        success_message: If provided, queued as a success flash message
            after ``action`` completes without raising.

    Returns:
        The result of ``action``, or ``None`` if it raised a recognized
        exception (already queued as an error flash message).

    Raises:
        Exception: Any exception type not recognized by this function is
            re-raised, since silently swallowing an unrecognized failure
            would hide a genuine defect rather than surface an expected,
            user-facing condition.
    """
    with st.spinner(loading_message):
        try:
            result = action()
        except (EAHError, AuthError, NotificationError, AnalyticsError, EngineWorkflowError) as exc:
            message = getattr(exc, "message", str(exc))
            logger.warning("Action failed: %s", message, extra={"exception_type": type(exc).__name__})
            session.push_flash("error", message)
            return None

    if success_message is not None:
        session.push_flash("success", success_message)
    return result


def status_badge(value: str) -> None:
    """Render a small, colored badge for a status or stage value.

    Args:
        value: The raw enum value (e.g. ``"pending"``, ``"completed"``).
    """
    tone = _STATUS_TONE.get(value, "neutral")
    color = _TONE_COLOR[tone]
    background = _TONE_BACKGROUND[tone]
    label = value.replace("_", " ").title()
    st.markdown(
        f"<span style='background-color:{background};color:{color};"
        "padding:2px 10px;border-radius:12px;font-size:0.85em;font-weight:600;"
        f"display:inline-block;'>{label}</span>",
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str | int | float, *, help_text: str | None = None) -> None:
    """Render a single KPI metric card.

    Args:
        label: The metric's short label.
        value: The metric's value, already formatted for display.
        help_text: An optional tooltip explaining the metric.
    """
    st.metric(label=label, value=value, help=help_text)


def render_table(
    rows: Sequence[dict[str, Any]],
    *,
    empty_message: str = "No records to display.",
) -> None:
    """Render a sequence of dict rows as a table.

    Args:
        rows: The rows to display, each a mapping of column name to
            display value.
        empty_message: The message shown when ``rows`` is empty, via
            ``empty_state``.
    """
    if not rows:
        empty_state(empty_message)
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def confirm_action(key: str, *, label: str, danger: bool = False) -> bool:
    """Render a two-step confirmation control for a destructive or
    significant action.

    The first render shows a single button labeled ``label``. Clicking
    it marks the confirmation as pending (via ``session.request_confirmation``)
    and reruns the page, at which point this function instead renders
    "Confirm"/"Cancel" buttons. Only clicking "Confirm" causes this
    function to return ``True``.

    Args:
        key: A unique identifier for this confirmable action.
        label: The label for the initial trigger button.
        danger: Whether to render the trigger/confirm buttons with a
            destructive visual style.

    Returns:
        ``True`` only on the render where the user clicks "Confirm";
        ``False`` on every other render.
    """
    button_type = "primary" if danger else "secondary"

    if not session.is_confirmation_pending(key):
        if st.button(label, key=f"{key}_trigger", type=button_type):
            session.request_confirmation(key)
            st.rerun()
        return False

    st.warning("Please confirm this action.")
    col_confirm, col_cancel = st.columns(2)
    confirmed = False
    with col_confirm:
        if st.button("Confirm", key=f"{key}_confirm", type="primary"):
            session.clear_confirmation(key)
            confirmed = True
    with col_cancel:
        if st.button("Cancel", key=f"{key}_cancel"):
            session.clear_confirmation(key)
            st.rerun()
    return confirmed


def pagination_controls(page_key: str, *, total_pages: int) -> int:
    """Render previous/next pagination controls and return the active page.

    Args:
        page_key: The page's stable identifier, used to read/write
            pagination state via ``session``.
        total_pages: The total number of pages available.

    Returns:
        The currently active page number (1-indexed).
    """
    current_page, page_size = session.get_pagination(page_key)
    current_page = max(1, min(current_page, max(total_pages, 1)))

    col_prev, col_label, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("← Previous", key=f"{page_key}_prev", disabled=current_page <= 1):
            session.set_pagination(page_key, page_number=current_page - 1, page_size=page_size)
            st.rerun()
    with col_label:
        st.markdown(
            f"<div style='text-align:center;'>Page {current_page} of {max(total_pages, 1)}</div>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Next →", key=f"{page_key}_next", disabled=current_page >= total_pages):
            session.set_pagination(page_key, page_number=current_page + 1, page_size=page_size)
            st.rerun()

    return current_page


def search_bar(page_key: str, *, placeholder: str = "Search...") -> str:
    """Render a search input bound to a page's stored filter state.

    Args:
        page_key: The page's stable identifier.
        placeholder: The input's placeholder text.

    Returns:
        The current search text (empty string if none entered).
    """
    filters = session.get_filters(page_key)
    return st.text_input(
        "Search", value=filters.get("search", ""), placeholder=placeholder, label_visibility="collapsed"
    )


def filter_select(
    label: str, options: Sequence[str], *, key: str, current_value: str | None
) -> str | None:
    """Render a single-select filter dropdown with an "All" option.

    Args:
        label: The filter's display label.
        options: The selectable values (excluding "All").
        key: A unique Streamlit widget key.
        current_value: The currently selected value, or ``None`` for
            "All".

    Returns:
        The selected value, or ``None`` if "All" is selected.
    """
    display_options = ["All", *options]
    current_index = display_options.index(current_value) if current_value in options else 0
    selected = st.selectbox(label, display_options, index=current_index, key=key)
    return None if selected == "All" else selected


def workflow_timeline(stages: Sequence[WorkflowStage]) -> None:
    """Render an ordered, vertical timeline of a request's workflow stages.

    Args:
        stages: The request's stages, expected in ``stage_order`` order.
    """
    if not stages:
        empty_state("This request has no workflow stages yet.")
        return

    for stage in sorted(stages, key=lambda s: s.stage_order):
        col_marker, col_content = st.columns([1, 8])
        with col_marker:
            status_badge(stage.status.value)
        with col_content:
            st.markdown(f"**Stage {stage.stage_order}: {stage.stage_name}**")
            details: list[str] = []
            if stage.assigned_to is not None:
                details.append(f"Assigned to user `{stage.assigned_to}`")
            elif stage.assigned_role is not None:
                details.append(f"Eligible role: {stage.assigned_role.value}")
            if stage.decided_by is not None and stage.decided_at is not None:
                details.append(f"Decided by `{stage.decided_by}` at {stage.decided_at.isoformat()}")
            if stage.decision_note:
                details.append(f"Note: {stage.decision_note}")
            if details:
                st.caption(" · ".join(details))
        st.divider()


def empty_state(message: str, *, icon: str = "📭") -> None:
    """Render a consistent empty-state placeholder.

    Args:
        message: The message explaining why there is nothing to show.
        icon: An emoji or short glyph displayed above the message.
    """
    st.markdown(
        f"<div style='text-align:center;padding:2rem;color:#6e7781;'>"
        f"<div style='font-size:2rem;'>{icon}</div><div>{message}</div></div>",
        unsafe_allow_html=True,
    )


def section_header(title: str, *, description: str | None = None) -> None:
    """Render a consistent page/section header.

    Args:
        title: The section's title.
        description: An optional short description shown beneath the
            title.
    """
    st.subheader(title)
    if description:
        st.caption(description)