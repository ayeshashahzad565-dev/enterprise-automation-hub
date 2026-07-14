"""Centralized page routing, sidebar, menu generation, and RBAC-aware navigation.

Per this package's design brief, this is the single place page routing
and the sidebar menu are defined — no other module in this package
constructs a navigation menu of its own. Dispatch to each concrete page
module's ``render()`` function is performed via a local import inside
``render_app``, so that page modules remain free to import this module
for ``guard_role``/breadcrumbs without creating an import cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import streamlit as st

from app.auth.authentication import AuthenticatedIdentity
from app.auth.rbac import require_role
from app.auth.exceptions import RoleNotPermittedError
from app.models.enums import UserRole

from app.pages import session

__all__ = ["NavItem", "NAV_ITEMS", "guard_role", "render_breadcrumbs", "render_sidebar", "render_app"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NavItem:
    """A single sidebar navigation entry.

    Attributes:
        key: The page's stable routing key.
        label: The entry's display label.
        icon: A short emoji/glyph shown alongside the label.
        allowed_roles: The roles permitted to see and access this page,
            or ``None`` if every authenticated role may access it.
    """

    key: str
    label: str
    icon: str
    allowed_roles: tuple[UserRole, ...] | None


#: The fixed set of pages this application exposes, in sidebar order.
NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem(key="dashboard", label="Dashboard", icon="🏠", allowed_roles=None),
    NavItem(key="requests", label="Requests", icon="📄", allowed_roles=None),
    NavItem(key="approvals", label="Approvals", icon="✅", allowed_roles=(UserRole.APPROVER, UserRole.ADMIN)),
    NavItem(key="workflows", label="Workflows", icon="🔀", allowed_roles=(UserRole.ADMIN,)),
    NavItem(
        key="analytics",
        label="Analytics",
        icon="📊",
        allowed_roles=(UserRole.APPROVER, UserRole.ADMIN),
    ),
    NavItem(key="admin", label="Admin", icon="🛠️", allowed_roles=(UserRole.ADMIN,)),
    NavItem(key="profile", label="Profile", icon="👤", allowed_roles=None),
)

_PAGE_TITLES: dict[str, str] = {item.key: item.label for item in NAV_ITEMS}


def guard_role(identity: AuthenticatedIdentity, *allowed_roles: UserRole) -> bool:
    """Stop rendering the current page if the identity's role is not permitted.

    Args:
        identity: The current caller's identity.
        *allowed_roles: The roles permitted on this page.

    Returns:
        ``True`` if access is permitted. If access is not permitted, this
        function renders an error message and calls ``st.stop()``, so it
        never returns ``False`` to its caller.
    """
    try:
        require_role(identity.role, *allowed_roles)
    except RoleNotPermittedError:
        logger.warning(
            "Access denied: user=%s role=%s allowed=%s",
            identity.user_id,
            identity.role.value,
            [r.value for r in allowed_roles],
            extra={"user_id": str(identity.user_id)},
        )
        st.error("You do not have permission to view this page.")
        st.stop()
    return True


def render_breadcrumbs(*path: str) -> None:
    """Render a simple breadcrumb trail.

    Args:
        *path: The breadcrumb segments, from root to current page.
    """
    st.caption(" / ".join(("Home", *path)))


def _visible_items(identity: AuthenticatedIdentity) -> tuple[NavItem, ...]:
    """Return the navigation items visible to a given identity.

    Args:
        identity: The current caller's identity.

    Returns:
        The subset of ``NAV_ITEMS`` this identity's role may access.
    """
    return tuple(
        item for item in NAV_ITEMS if item.allowed_roles is None or identity.role in item.allowed_roles
    )


def render_sidebar(identity: AuthenticatedIdentity) -> str:
    """Render the sidebar navigation menu and return the selected page key.

    Args:
        identity: The current caller's identity, used to filter which
            pages are shown.

    Returns:
        The selected page's key.
    """
    with st.sidebar:
        st.markdown("### Enterprise Automation Hub")
        st.caption(f"Signed in as {identity.email or identity.user_id} ({identity.role.value})")
        st.divider()

        visible = _visible_items(identity)
        current_key = session.get_active_page() or visible[0].key
        if current_key not in {item.key for item in visible}:
            current_key = visible[0].key

        labels = [f"{item.icon}  {item.label}" for item in visible]
        keys = [item.key for item in visible]
        current_index = keys.index(current_key)

        selected_label = st.radio(
            "Navigate", labels, index=current_index, label_visibility="collapsed"
        )
        selected_key = keys[labels.index(selected_label)]
        session.set_active_page(selected_key)

        st.divider()
        if st.button("Log out", key="sidebar_logout"):
            from app.pages import login  # local import avoids a module-load-time cycle

            login.logout()
            st.rerun()

    return selected_key


def render_app() -> None:
    """The application's single entry point: gate on authentication, render
    the sidebar, and dispatch to the active page's ``render()`` function.

    This is the intended function for a bootstrap script to call on every
    Streamlit rerun, after having already called ``session.set_container``
    once. Every page module is imported lazily, inside this function, to
    avoid a circular import between ``navigation.py`` and the page
    modules that themselves import ``navigation.guard_role``/
    ``render_breadcrumbs``.
    """
    from app.pages import (  # local imports: see docstring
        admin,
        analytics,
        approvals,
        dashboard,
        login,
        profile,
        requests as requests_page,
        workflows,
    )

    if login.handle_auth_callback():
        return

    if not session.is_authenticated():
        login.render()
        return

    if session.is_recovery_pending():
        login.render_password_reset()
        return

    identity = session.get_identity()
    assert identity is not None  # guaranteed by is_authenticated() above

    active_key = render_sidebar(identity)

    dispatch = {
        "dashboard": dashboard.render,
        "requests": requests_page.render,
        "approvals": approvals.render,
        "workflows": workflows.render,
        "analytics": analytics.render,
        "admin": admin.render,
        "profile": profile.render,
    }

    page_fn = dispatch.get(active_key, dashboard.render)
    page_fn()