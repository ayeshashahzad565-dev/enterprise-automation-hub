"""Application service orchestrating platform-level feature flag management.

Every method here is gated by ``authorize_platform_admin``, mirroring
``CompanyService``'s exact shape — feature flags are global (not
per-tenant) platform infrastructure state, managed the same way company
records are. Per the Platform Administration module's "lightweight,
informational" scope decision, nothing else in this codebase consumes or
enforces these flags yet.
"""

from __future__ import annotations

import logging

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_platform_admin
from app.database.exceptions import DatabaseError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.feature_flag_repository import (
    FeatureFlagRecord,
    FeatureFlagRepository,
)
from app.models.enums import AuditAction
from app.models.feature_flag import FeatureFlag
from app.services.exceptions import translate_auth_error, translate_database_error
from app.utils.decorators import log_calls

__all__ = ["map_feature_flag_record_to_domain", "FeatureFlagService"]

logger = logging.getLogger(__name__)


def map_feature_flag_record_to_domain(record: FeatureFlagRecord) -> FeatureFlag:
    """Map a persistence-level ``FeatureFlagRecord`` into its Domain Layer
    ``FeatureFlag`` representation.

    Args:
        record: The record returned by ``FeatureFlagRepository``.

    Returns:
        The corresponding ``FeatureFlag`` domain model.
    """
    return FeatureFlag(
        key=record.key,
        description=record.description,
        enabled=record.enabled,
        updated_at=record.updated_at,
    )


class FeatureFlagService:
    """Orchestrates platform-admin-only feature flag creation, listing, and updates."""

    def __init__(self, *, feature_flag_repo: FeatureFlagRepository, audit_repo: AuditRepository) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            feature_flag_repo: Persistence for ``feature_flags``.
            audit_repo: Records every flag mutation this service performs.
        """
        self._feature_flag_repo = feature_flag_repo
        self._audit_repo = audit_repo
        self._logger = logging.getLogger(f"{__name__}.FeatureFlagService")

    def _authorize(self, identity: AuthenticatedIdentity) -> None:
        try:
            authorize_platform_admin(identity)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    @log_calls()
    def create_flag(
        self, identity: AuthenticatedIdentity, *, key: str, description: str, enabled: bool = False
    ) -> FeatureFlag:
        """Define a new feature flag.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            key: The flag's stable identifier.
            description: A human-readable description.
            enabled: The flag's initial state.

        Returns:
            The newly created ``FeatureFlag``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            ValidationError: If ``key`` is already in use.
        """
        self._authorize(identity)

        try:
            created = self._feature_flag_repo.create(
                key=key, description=description, enabled=enabled, updated_by=identity.user_id
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.FEATURE_FLAG_UPDATED,
            actor_id=identity.user_id,
            metadata={"key": key, "enabled": enabled, "created": True},
        )
        return map_feature_flag_record_to_domain(created)

    @log_calls()
    def list_flags(self, identity: AuthenticatedIdentity) -> list[FeatureFlag]:
        """List every feature flag.

        Args:
            identity: The authenticated caller. Must be a platform admin.

        Returns:
            Every ``FeatureFlag``, alphabetically by key.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
        """
        self._authorize(identity)

        try:
            records = self._feature_flag_repo.list_all()
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return [map_feature_flag_record_to_domain(r) for r in records]

    @log_calls()
    def update_flag(
        self,
        identity: AuthenticatedIdentity,
        key: str,
        *,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> FeatureFlag:
        """Update a flag's description and/or on/off state.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            key: The flag's identifier.
            description: The new description, if changing.
            enabled: The new on/off state, if changing.

        Returns:
            The updated ``FeatureFlag``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            NotFoundError: If no flag with this key exists.
        """
        self._authorize(identity)

        try:
            updated = self._feature_flag_repo.update(
                key, description=description, enabled=enabled, updated_by=identity.user_id
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.FEATURE_FLAG_UPDATED,
            actor_id=identity.user_id,
            metadata={"key": key, "enabled": updated.enabled},
        )
        return map_feature_flag_record_to_domain(updated)
