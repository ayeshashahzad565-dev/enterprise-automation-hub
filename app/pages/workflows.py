"""Admin-only workflow definition management UI.

Per this package's design brief, this page contains no workflow
validation logic of its own — every rule (structural JSON shape,
assignment-strategy field requirements, unique/contiguous stage
ordering, at-most-one-active-per-type) is enforced by
``app.workflow.WorkflowEngine`` inside
``app.services.workflow_definition_service.WorkflowDefinitionService``,
and any violation surfaces here as a flash message via
``components.run_with_feedback``. This page performs only JSON *syntax*
parsing (``json.loads``) before handing the resulting dict to the
service — that is input-format handling, not workflow validation.

``WorkflowDefinitionService``'s API is scoped to one request type at a
time (there is no "list every workflow definition across every request
type" method anywhere in the finalized architecture). This page is
scoped accordingly: an administrator enters the request type they want
to manage.
"""

from __future__ import annotations

import json
import logging

import streamlit as st

from app.database.repositories.base_repository import Page
from app.models.enums import UserRole

from app.pages import components, navigation, session

__all__ = ["render"]

logger = logging.getLogger(__name__)

_PAGE_KEY = "workflows"

_EXAMPLE_DEFINITION = {
    "stages": [
        {
            "order": 1,
            "name": "Manager Review",
            "assignment_strategy": "requester_manager",
            "escalation_hours": 48,
        },
        {
            "order": 2,
            "name": "Finance Review",
            "assignment_strategy": "department_queue",
            "assigned_role": "approver",
            "department": "finance",
            "escalation_hours": 72,
        },
    ]
}


def render() -> None:
    """Render the workflow definitions administration page."""
    components.flash_messages()
    identity = session.get_identity()
    assert identity is not None
    navigation.guard_role(identity, UserRole.ADMIN)
    navigation.render_breadcrumbs("Workflows")

    st.markdown("## Workflow Definitions")
    st.info(
        "Workflow definitions are managed one request type at a time — there is no "
        "system-wide listing available. Enter a request type below to view or "
        "manage its versions."
    )

    request_type = st.text_input(
        "Request Type", value=session.get_cached_selection("workflows_request_type") or ""
    )
    if request_type.strip():
        session.set_cached_selection("workflows_request_type", request_type.strip())

    if not request_type.strip():
        return

    tab_versions, tab_create = st.tabs(["Versions", "Create New Version"])
    with tab_versions:
        _render_versions(request_type.strip())
    with tab_create:
        _render_create(request_type.strip())


def _render_versions(request_type: str) -> None:
    """Render the version history for a request type, with activation controls.

    Args:
        request_type: The request type to display versions for.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    page_number, page_size = session.get_pagination(_PAGE_KEY)
    result = components.run_with_feedback(
        lambda: container.workflow_definition_service.list_versions(
            identity, request_type, page=Page(number=page_number, size=page_size)
        ),
        loading_message="Loading versions...",
    )
    if result is None:
        return

    if not result.items:
        components.empty_state(f"No workflow definitions exist yet for '{request_type}'.")
        return

    for definition in result.items:
        with st.expander(
            f"Version {definition.version}"
            + (" (Active)" if definition.is_active else " (Draft)"),
            expanded=definition.is_active,
        ):
            if definition.is_active:
                st.success("This version is currently active.")
            else:
                st.warning("This version is inactive.")

            st.json(definition.definition.model_dump(mode="json"))

            if not definition.is_active:
                col_activate, col_edit = st.columns(2)
                with col_activate:
                    if components.confirm_action(
                        f"activate_{definition.id}", label="Activate This Version"
                    ):
                        activated = components.run_with_feedback(
                            lambda: container.workflow_definition_service.activate_version(
                                identity, definition.id
                            ),
                            loading_message="Activating...",
                            success_message=f"Version {definition.version} activated.",
                        )
                        if activated is not None:
                            st.rerun()
                with col_edit:
                    if st.button("Edit Draft", key=f"edit_{definition.id}"):
                        session.set_cached_selection("editing_definition_id", definition.id)
                        session.set_cached_selection(
                            "editing_definition_json",
                            json.dumps(definition.definition.model_dump(mode="json"), indent=2),
                        )
                        st.rerun()

    editing_id = session.get_cached_selection("editing_definition_id")
    if editing_id is not None:
        st.divider()
        components.section_header("Edit Draft Definition")
        raw_json = st.text_area(
            "Definition JSON",
            value=session.get_cached_selection("editing_definition_json") or "",
            height=300,
            key="edit_definition_json_input",
        )
        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("Save Draft", type="primary", key="save_draft"):
                _submit_update(editing_id, raw_json)
        with col_cancel:
            if st.button("Cancel Edit", key="cancel_edit"):
                session.clear_cached_selection("editing_definition_id")
                session.clear_cached_selection("editing_definition_json")
                st.rerun()

    components.pagination_controls(_PAGE_KEY, total_pages=result.total_pages)


def _submit_update(definition_id, raw_json: str) -> None:
    """Parse and submit an edited draft definition.

    Args:
        definition_id: The id of the definition being edited.
        raw_json: The edited JSON text.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    parsed = _parse_json(raw_json)
    if parsed is None:
        return

    updated = components.run_with_feedback(
        lambda: container.workflow_definition_service.update_draft(
            identity, definition_id, definition=parsed
        ),
        loading_message="Saving draft...",
        success_message="Draft updated.",
    )
    if updated is not None:
        session.clear_cached_selection("editing_definition_id")
        session.clear_cached_selection("editing_definition_json")
        st.rerun()


def _render_create(request_type: str) -> None:
    """Render the form for creating a new workflow definition version.

    Args:
        request_type: The request type the new version will govern.
    """
    container = session.get_container()
    identity = session.get_identity()
    assert identity is not None

    st.caption(
        "Author the definition as JSON. Structural validation (stage ordering, "
        "required fields per assignment strategy) is performed by the Workflow "
        "Engine when you submit — errors will be shown here, not caught in advance."
    )
    with st.expander("Show example definition"):
        st.json(_EXAMPLE_DEFINITION)

    raw_json = st.text_area(
        "Definition JSON",
        value=json.dumps(_EXAMPLE_DEFINITION, indent=2),
        height=300,
        key="create_definition_json_input",
    )

    if st.button("Create New Version", type="primary"):
        parsed = _parse_json(raw_json)
        if parsed is None:
            return
        created = components.run_with_feedback(
            lambda: container.workflow_definition_service.create_definition(
                identity, request_type=request_type, definition=parsed
            ),
            loading_message="Creating version...",
            success_message="New draft version created.",
        )
        if created is not None:
            st.rerun()


def _parse_json(raw_json: str) -> dict | None:
    """Parse a text area's contents as JSON, reporting a syntax error via flash.

    This is input-format parsing only — it never inspects the parsed
    structure for workflow-specific correctness; that remains the
    Workflow Engine's responsibility.

    Args:
        raw_json: The raw text to parse.

    Returns:
        The parsed dict, or ``None`` if parsing failed (a flash message
        has already been queued in that case).
    """
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        session.push_flash("error", f"Invalid JSON: {exc}")
        return None
    if not isinstance(parsed, dict):
        session.push_flash("error", "The definition must be a JSON object.")
        return None
    return parsed