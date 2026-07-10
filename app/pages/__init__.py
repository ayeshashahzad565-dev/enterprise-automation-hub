"""The Streamlit Presentation Layer for the Enterprise Automation Hub.

Per this package's design brief, every module here renders UI and
delegates every user action to an Application Service — this package
contains no business logic, no workflow decisions, no SQL, no
repository logic, no authentication logic, and no analytics
calculations.

This package contains:

- ``session``: centralized Streamlit session state, the
  ``AppContainer`` dependency-injection bundle, and the ``AuthGateway``
  protocol boundary this package needs but no lower layer implements.
- ``components``: reusable UI building blocks, including
  ``run_with_feedback``, the single shared "call a service, show a
  spinner, translate any exception into a flash message" pattern every
  page uses.
- ``navigation``: the sidebar, RBAC-aware page visibility, breadcrumbs,
  and the application's single entry point, ``render_app``.
- ``login``: sign-in, sign-out, and session initialization.
- ``dashboard``: the role-aware landing page.
- ``requests``: request list, detail, create, edit, and withdraw.
- ``approvals``: the pending-approvals queue and decision actions.
- ``workflows``: admin-only workflow definition management.
- ``analytics``: KPI cards, tables, and trend charts sourced from
  ``app.analytics``.
- ``admin``: system status, scheduler health, and configuration display.
- ``profile``: account summary and password-reset entry point.

A bootstrap script outside this package is expected to construct a
``session.AppContainer`` (wiring real repositories, services, and an
``session.AuthGateway`` implementation) once, call
``session.set_container(...)``, and then call ``navigation.render_app()``
on every Streamlit rerun.
"""

from __future__ import annotations

from app.pages import (
    admin,
    analytics,
    approvals,
    components,
    dashboard,
    login,
    navigation,
    profile,
    requests,
    session,
    workflows,
)

__all__ = [
    "admin",
    "analytics",
    "approvals",
    "components",
    "dashboard",
    "login",
    "navigation",
    "profile",
    "requests",
    "session",
    "workflows",
]