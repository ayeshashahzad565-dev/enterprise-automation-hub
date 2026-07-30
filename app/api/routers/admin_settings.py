"""Routes for the admin Platform Settings module: a read-only view of
non-secret application configuration (``app.config.settings.AppSettings``).

No PATCH endpoint exists — ``AppSettings`` is loaded once from
environment variables at process startup (see that module's own
docstring), with no persisted, runtime-mutable settings table anywhere in
the database. Per this phase's explicit "do not create settings with no
backend support" instruction, this module is read-only. SMTP credentials
and the raw Supabase/database connection strings are deliberately never
serialized here — see ``app.api.schemas.admin.PlatformSettingsOut`` for
the exact, hand-picked allow-list of fields this route exposes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_current_identity, get_resources
from app.api.schemas.admin import PlatformSettingsOut
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.bootstrap import ApplicationResources
from app.models.enums import UserRole
from app.utils.response import build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-settings"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/admin/settings")
def get_platform_settings(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    resources: ApplicationResources = Depends(get_resources),
) -> dict[str, Any]:
    """Read-only, non-secret platform configuration. Admin only."""
    rbac.require_role(identity.role, UserRole.ADMIN)
    settings = resources.settings
    out = PlatformSettingsOut(
        environment=settings.environment.value,
        default_escalation_hours=settings.workflow.default_escalation_hours,
        read_per_minute=settings.rate_limits.read_per_minute,
        write_per_minute=settings.rate_limits.write_per_minute,
        upload_per_minute=settings.rate_limits.upload_per_minute,
        login_per_5_minutes=settings.rate_limits.login_per_5_minutes,
        notification_poll_per_minute=settings.rate_limits.notification_poll_per_minute,
        log_level=settings.logging.level,
        smtp_enabled=settings.smtp.is_enabled,
    )
    return build_success_response(serialize(out), request_id=_request_id_of(request))
