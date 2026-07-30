"""Shared composition helpers for the admin_users/admin_departments/
admin_dashboard routers.

``ProfileRepository`` has no "list every user" method anywhere (confirmed
absent by audit) — only ``list_by_role`` (one role at a time) and
``search_by_name``. Every admin route that needs an organization-wide
user count or a department breakdown composes it here by paging through
``list_by_role`` for all three fixed roles and merging the results
in-memory.

This is an explicit, confirmed design choice: acceptable for this
application's demo/mid-size-organization data volume, and not a
scalable, production-grade aggregate query — a real "list/count all
users" capability would need a new repository method (out of scope for
this thin-wrapper phase, which may not modify ``app.database``).
"""

from __future__ import annotations

from uuid import UUID

from app.database.repositories.base_repository import MAX_PAGE_SIZE, Page
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository
from app.models.enums import UserRole

__all__ = ["fetch_all_profiles", "group_profiles_by_department"]

#: The bucket label used for profiles with no department set, matching
#: the same "group ungrouped rows under an honest placeholder" precedent
#: as ``AnalyticsRepository.count_requests_by_department``'s
#: ``"unspecified"`` (a different literal, since profile.department and
#: request.department are independent free-text fields with no shared
#: vocabulary).
UNASSIGNED_DEPARTMENT = "Unassigned"


def fetch_all_profiles(profile_repo: ProfileRepository, *, company_id: UUID) -> list[ProfileRecord]:
    """Compose the full user population by paging ``list_by_role`` per role.

    Args:
        profile_repo: The repository to read from.
        company_id: Restricts results to this company (tenant).

    Returns:
        Every profile across all three roles within this company, in no
        particular cross-role order (each role's own page is ordered by
        full name).
    """
    profiles: list[ProfileRecord] = []
    for role in UserRole:
        page_number = 1
        while True:
            result = profile_repo.list_by_role(
                role, company_id=company_id, page=Page(number=page_number, size=MAX_PAGE_SIZE)
            )
            profiles.extend(result.items)
            if page_number * MAX_PAGE_SIZE >= result.total_records or not result.items:
                break
            page_number += 1
    return profiles


def group_profiles_by_department(
    profiles: list[ProfileRecord],
) -> dict[str, dict[UserRole, int]]:
    """Group profiles by department, bucketing unset departments together.

    Args:
        profiles: The profiles to group, typically from
            ``fetch_all_profiles``.

    Returns:
        A mapping from department name (or ``UNASSIGNED_DEPARTMENT``) to
        a per-role member count.
    """
    grouped: dict[str, dict[UserRole, int]] = {}
    for profile in profiles:
        key = profile.department or UNASSIGNED_DEPARTMENT
        bucket = grouped.setdefault(key, dict.fromkeys(UserRole, 0))
        bucket[profile.role] += 1
    return grouped
