"""Application service orchestrating cross-entity global search.

Composes already-authorized reads from the finalized per-entity services
(``RequestService``, ``ApprovalService``, ``WorkflowDefinitionService``)
wherever one exists, exactly as ``DashboardService`` already composes
other services rather than querying repositories itself — and falls back
to a repository directly, mirroring ``ServicesAnalyticsService``'s
identical precedent, only for the three entities with no dedicated
service exposing the read this feature needs (``comments`` across more
than one request at a time, ``audit_logs`` likewise, and ``profiles`` by
name — there is no ``CommentService``/``AuditService``/``UserService``
method shaped for a cross-request or cross-user search). This module
performs no authorization logic beyond what those repositories and
services already enforce; it never bypasses a role check, and it never
grants a caller visibility into a request they could not already reach
through ``RequestService``.

**"Fuzzy" is a deliberate, stated scope, not a euphemism.** No full-text-
search or trigram (``pg_trgm``) index is provisioned anywhere in this
schema (the existing ``search_requests`` ILIKE pattern is the only
precedent), and adding one is a real infrastructure decision this feature
does not make unilaterally. Search therefore combines two mechanisms:

1. A server-side, case-insensitive **substring** query (``ILIKE``) — for
   every entity except ``approval`` — narrows the candidate set at the
   database, exactly like ``search_requests`` already does.
2. A dependency-free, in-process ``difflib``-based score
   (``_fuzzy_score``) ranks the (already substring-matched, already
   bounded) candidates and tolerates minor typos *within* that candidate
   set. ``approval`` results have no database-level prefilter at all —
   the caller's own pending-approval queue is small enough (bounded at
   ``MAX_PAGE_SIZE``) to score entirely in Python.

This is real typo tolerance on a bounded, already-authorized working set —
not a true fuzzy/Levenshtein search across an entire multi-hundred-
thousand-row table, which would need the trigram index this schema does
not have. That gap is deliberate, not an oversight.
"""

from __future__ import annotations

import contextvars
import difflib
import logging
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.api.routers.admin_shared import (
    UNASSIGNED_DEPARTMENT,
    fetch_all_profiles,
    group_profiles_by_department,
)
from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.attachment_repository import AttachmentRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import MAX_PAGE_SIZE, Page, PagedResult
from app.database.repositories.comment_repository import CommentRepository
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.saved_filter_repository import SavedFilterRepository
from app.database.repositories.search_history_repository import SearchHistoryRepository
from app.database.repositories.user_repository import ProfileRepository
from app.models import WorkflowStage
from app.models.enums import UserRole
from app.models.search import SavedFilter, SearchHistoryEntry
from app.services.approval_service import ApprovalService
from app.services.exceptions import ValidationError, translate_database_error
from app.services.request_service import RequestService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.utils.decorators import log_calls

__all__ = ["ENTITY_TYPES", "SearchResultItem", "GlobalSearchService"]

logger = logging.getLogger(__name__)

#: The fixed set of entity types this feature searches, in the order
#: results are grouped for display. A caller may restrict a search to a
#: subset of these via ``GlobalSearchService.search``'s ``entity_types``
#: parameter — this is this feature's "filters" capability.
ENTITY_TYPES: tuple[str, ...] = (
    "request",
    "approval",
    "workflow",
    "user",
    "comment",
    "audit_entry",
    "department",
    "notification",
    "attachment",
)

#: The minimum ``_fuzzy_score`` an "approval" or "department" result must
#: reach to be included. Every other entity type is already substring-
#: prefiltered by its own database query and needs no additional cutoff;
#: "approval" and "department" have no such prefilter (see this module's
#: own docstring, and ``_search_departments``'s — departments aren't a
#: table at all), so a threshold is the only thing standing between a
#: search and a full, unranked dump of the caller's entire pending queue
#: or the company's entire department list.
_MIN_APPROVAL_SCORE = 0.3

#: How many characters of surrounding context ``_highlight_snippet`` keeps
#: on each side of a matched substring.
_SNIPPET_CONTEXT_CHARS = 60


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    """One row in a global search result, from any of ``ENTITY_TYPES``.

    Only the fields relevant to ``entity_type`` are meaningfully
    populated; the rest are ``None``, since a "request," a "user," and an
    "approval" are genuinely different shapes converging into one list
    for display — this is an honest reflection of that, not a shared
    schema every entity type happens to fit.

    Attributes:
        entity_type: One of ``ENTITY_TYPES``.
        id: This result's own id (the request/comment/audit entry/
            profile/workflow definition/workflow stage id — whichever
            ``entity_type`` implies), used as a stable UI key.
        title: The result's primary display line.
        subtitle: A secondary, smaller display line.
        snippet: A Markdown-formatted excerpt with the match highlighted,
            from ``_highlight_snippet``.
        score: This result's fuzzy-match score, in ``[0.0, 1.0]``, used
            to sort the combined, cross-entity result list.
        created_at: The result's own creation timestamp.
        request_id: For ``request``/``approval``/``comment``/
            ``audit_entry`` results, the request to deep-link into.
            ``None`` for ``workflow``/``user`` results, which have no
            associated request.
        stage: For ``approval`` results only, the full ``WorkflowStage``
            — ``approvals.py``'s own selection mechanism caches the
            whole stage object, not just its id, so this is carried
            through rather than re-fetched by the caller.
        request_type: For ``workflow`` results only, the request type
            string ``workflows.py``'s own selection mechanism keys off.
    """

    entity_type: str
    id: UUID
    title: str
    subtitle: str
    snippet: str
    score: float
    created_at: datetime
    request_id: UUID | None = None
    stage: WorkflowStage | None = None
    request_type: str | None = None


def _fuzzy_score(query_text: str, *candidate_texts: str | None) -> float:
    """Score how well any of ``candidate_texts`` matches ``query_text``, in ``[0, 1]``.

    Args:
        query_text: The user's search term.
        *candidate_texts: One or more fields to match against (e.g. a
            request's title and description); the best-scoring one wins.

    Returns:
        A score in ``[0.0, 1.0]``; ``0.0`` if every candidate is empty.
    """
    query_l = query_text.strip().lower()
    best = 0.0
    for candidate in candidate_texts:
        if not candidate:
            continue
        candidate_l = candidate.lower()
        if query_l in candidate_l:
            tightness = len(query_l) / len(candidate_l)
            score = 0.85 + 0.15 * tightness
        else:
            score = difflib.SequenceMatcher(None, query_l, candidate_l).ratio()
        best = max(best, score)
    return best


def _highlight_snippet(
    text: str, query_text: str, *, context_chars: int = _SNIPPET_CONTEXT_CHARS
) -> str:
    """Build a Markdown snippet with the first matching substring bolded.

    Renders as Markdown (``**bold**``), matching this application's
    existing convention of rendering comment/description/message text via
    ``st.markdown`` without escaping (e.g. ``components.py``'s decision-
    note rendering, ``profile.py``'s notification rows).

    Args:
        text: The full text to excerpt from.
        query_text: The search term to highlight.
        context_chars: How many characters of context to keep on each
            side of the match.

    Returns:
        A Markdown-formatted snippet, or a plain truncated prefix of
        ``text`` if ``query_text`` is not present as a literal substring
        (the result matched only fuzzily).
    """
    if not text:
        return ""
    needle = query_text.strip().lower()
    idx = text.lower().find(needle)
    if idx == -1 or not needle:
        return text if len(text) <= context_chars * 2 else f"{text[: context_chars * 2]}..."
    match_len = len(needle)
    start = max(0, idx - context_chars)
    end = min(len(text), idx + match_len + context_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:idx]}**{text[idx : idx + match_len]}**{text[idx + match_len : end]}{suffix}"


class GlobalSearchService:
    """Orchestrates fuzzy, filterable, cross-entity search."""

    def __init__(
        self,
        *,
        request_service: RequestService,
        approval_service: ApprovalService,
        workflow_definition_service: WorkflowDefinitionService,
        request_repo: RequestRepository,
        comment_repo: CommentRepository,
        audit_repo: AuditRepository,
        profile_repo: ProfileRepository,
        notification_repo: NotificationRepository,
        attachment_repo: AttachmentRepository,
        saved_filter_repo: SavedFilterRepository,
        search_history_repo: SearchHistoryRepository,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            request_service: Already-role-scoped request reads (also used
                to compute the caller's visible request ids, for scoping
                comment/audit/attachment search).
            approval_service: Already-role-scoped pending-approval reads.
            workflow_definition_service: Already-role-scoped workflow
                definition reads.
            request_repo: Persistence for ``requests``, used only to
                batch-resolve request titles for approval/comment/audit
                results — never to bypass ``request_service``'s own
                authorization.
            comment_repo: Persistence for ``comments``. No ``CommentService``
                method searches across more than one request at a time.
            audit_repo: Persistence for ``audit_logs``, for the same reason.
            profile_repo: Persistence for ``profiles``. No ``UserService``
                exists in this codebase at all; user and department search
                are administrator-only (enforced by this service, not by
                any lower layer).
            notification_repo: Persistence for ``notifications``. A
                notification is inherently scoped to its own recipient at
                the table level (``recipient_id`` equality, no further
                role logic), so this service reads it directly rather
                than through a service, the same as ``profile_repo``.
            attachment_repo: Persistence for ``attachments``, scoped to
                the caller's visible request ids for the same reason as
                ``comment_repo``/``audit_repo``.
            saved_filter_repo: Persistence for a caller's own saved
                searches.
            search_history_repo: Persistence for a caller's own past
                searches.
        """
        self._request_service = request_service
        self._approval_service = approval_service
        self._workflow_definition_service = workflow_definition_service
        self._request_repo = request_repo
        self._comment_repo = comment_repo
        self._audit_repo = audit_repo
        self._profile_repo = profile_repo
        self._notification_repo = notification_repo
        self._attachment_repo = attachment_repo
        self._saved_filter_repo = saved_filter_repo
        self._search_history_repo = search_history_repo
        self._logger = logging.getLogger(f"{__name__}.GlobalSearchService")

    @log_calls()
    def search(
        self,
        identity: AuthenticatedIdentity,
        query_text: str,
        *,
        entity_types: Sequence[str] | None = None,
        page: Page = Page(),
        limit_per_type: int | None = None,
    ) -> PagedResult[SearchResultItem]:
        """Search every entity type the caller may see, ranked together.

        Args:
            identity: The authenticated caller.
            query_text: The search term.
            entity_types: Restrict the search to this subset of
                ``ENTITY_TYPES``, if provided (this feature's "filters"
                capability). Unknown values are silently ignored rather
                than rejected, so a stale or hand-edited filter never
                breaks the whole search. ``None`` searches every type.
            page: The page of the merged, sorted result list to return.
            limit_per_type: Override the number of candidates fetched per
                entity type before merging/sorting/slicing. Defaults to
                ``MAX_PAGE_SIZE`` — most callers should leave this unset.

        Returns:
            A page of every matching result across every searched entity
            type, sorted by fuzzy-match score (ties broken by recency).
            Pagination operates over a **bounded candidate window**: each
            entity type contributes at most ``limit_per_type`` of its own
            best matches to the merged list before it is sliced into
            pages — the same honest, bounded-candidate-set convention
            ``_visible_request_ids`` already uses elsewhere in this
            class, not a live, unbounded count across an entire table. A
            fixed ``MAX_PAGE_SIZE`` window (rather than one sized to just
            the requested page) is deliberate: sizing the window to the
            page would make ``total_records`` — and therefore later
            pages — silently wrong whenever a small page size is
            requested against a larger true match count.

        Raises:
            ValidationError: If ``query_text`` is empty or whitespace-only.
        """
        if not query_text or not query_text.strip():
            raise ValidationError("Search query must not be empty.")

        types = (
            set(entity_types) & set(ENTITY_TYPES) if entity_types is not None else set(ENTITY_TYPES)
        )
        candidate_limit = limit_per_type if limit_per_type is not None else MAX_PAGE_SIZE

        # Each per-entity search below is an independent round trip to a
        # remote Supabase region (~240ms). Run sequentially, an unfiltered
        # search paid the sum of all nine — multiple seconds, on an
        # endpoint the Cmd/Ctrl+K command palette calls on every debounced
        # keystroke. Run concurrently it costs roughly the slowest one.
        #
        # Each submission takes its OWN contextvars.copy_context()
        # snapshot. That is a correctness requirement, not a tuning
        # detail: the RLS-scoped tenant client bound by
        # app.api.dependencies.bind_tenant_database_client lives in a
        # ContextVar, and a bare pool.submit(fn) would start its worker
        # with an empty context — every repository would silently fall
        # back to the service-role client and search rows this caller is
        # not entitled to see. One shared snapshot cannot be reused
        # either: a Context may only be entered by one thread at a time.
        #
        # Ordering is unaffected — results are sorted by score below, not
        # by the order the entity searches happen to finish in.
        searches: list[Callable[[], list[SearchResultItem]]] = []
        is_admin = identity.role is UserRole.ADMIN

        def _plan(method: Callable[..., list[SearchResultItem]]) -> None:
            searches.append(lambda: method(identity, query_text, candidate_limit))

        if "request" in types:
            _plan(self._search_requests)
        if "approval" in types:
            _plan(self._search_approvals)
        if "workflow" in types:
            _plan(self._search_workflows)
        if "user" in types and is_admin:
            _plan(self._search_users)
        if "department" in types and is_admin:
            _plan(self._search_departments)
        if "comment" in types:
            _plan(self._search_comments)
        if "audit_entry" in types:
            _plan(self._search_audit_entries)
        if "notification" in types:
            _plan(self._search_notifications)
        if "attachment" in types:
            _plan(self._search_attachments)

        results: list[SearchResultItem] = []
        if searches:
            with ThreadPoolExecutor(max_workers=len(searches)) as pool:
                futures = [
                    pool.submit(contextvars.copy_context().run, search) for search in searches
                ]
                for future in futures:
                    results.extend(future.result())

        results.sort(key=lambda item: (item.score, item.created_at), reverse=True)

        self._record_search_history(identity, query_text, entity_types, len(results))

        return PagedResult(
            items=results[page.offset : page.offset + page.size],
            page=page.number,
            page_size=page.size,
            total_records=len(results),
        )

    def _record_search_history(
        self,
        identity: AuthenticatedIdentity,
        query_text: str,
        entity_types: Sequence[str] | None,
        result_count: int,
    ) -> None:
        """Best-effort record a search-history entry for the caller.

        A failed write here must never break the search response itself
        — mirroring ``NotificationRepository.create_notification``'s own
        "a failed email send never prevents or reverses the underlying
        insert" precedent, applied to the analogous "history is a
        side effect of search, not a precondition for it" case.

        Args:
            identity: The authenticated caller.
            query_text: The search term that was entered.
            entity_types: The entity-type restriction that was applied,
                if any.
            result_count: How many results the search returned.
        """
        try:
            self._search_history_repo.record(
                user_id=identity.user_id,
                company_id=identity.company_id,
                query_text=query_text.strip(),
                entity_types=list(entity_types) if entity_types is not None else None,
                result_count=result_count,
            )
        except DatabaseError:
            self._logger.warning(
                "Failed to record search history for user %s; search itself still succeeded.",
                identity.user_id,
                exc_info=True,
            )

    def _visible_request_ids(self, identity: AuthenticatedIdentity) -> list[UUID] | None:
        """Return the request ids to scope comment/audit search to.

        Args:
            identity: The authenticated caller.

        Returns:
            ``None`` for an administrator (unrestricted — API-ADD:
            "Administrator — may view all requests, comments,
            attachments, and the full audit trail"). Otherwise, the
            caller's own visible request ids, per ``RequestService.
            list_requests``'s own role scoping, bounded to the first
            ``MAX_PAGE_SIZE`` — the same honest bound this service
            applies wherever a caller's "own" working set is gathered for
            search (see ``_search_approvals``).
        """
        if identity.role is UserRole.ADMIN:
            return None
        visible = self._request_service.list_requests(identity, page=Page(size=MAX_PAGE_SIZE)).items
        return [r.id for r in visible]

    def _request_titles(self, request_ids: Sequence[UUID], *, company_id: UUID) -> dict[UUID, str]:
        """Batch-resolve request titles for display enrichment.

        Args:
            request_ids: The request ids to resolve.
            company_id: The caller's own company (tenant).

        Returns:
            A mapping of request id to title, for however many of
            ``request_ids`` still exist. Never raises for an id that no
            longer resolves — a display enrichment must never break the
            search it decorates.
        """
        unique_ids = list(set(request_ids))
        if not unique_ids:
            return {}
        result = self._request_repo.list_requests(
            company_id=company_id, request_ids=unique_ids, page=Page(size=MAX_PAGE_SIZE)
        )
        return {r.id: r.title for r in result.items}

    def _search_requests(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search requests visible to the caller (``RequestService.search_requests``)."""
        result = self._request_service.search_requests(identity, query_text, page=Page(size=limit))
        return [
            SearchResultItem(
                entity_type="request",
                id=request.id,
                title=request.title,
                subtitle=(
                    f"{request.request_type.replace('_', ' ').title()} · "
                    f"{request.status.value.replace('_', ' ').title()}"
                ),
                snippet=_highlight_snippet(request.description or request.title, query_text),
                score=_fuzzy_score(query_text, request.title, request.description),
                created_at=request.created_at,
                request_id=request.id,
            )
            for request in result.items
        ]

    def _search_approvals(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search the caller's own pending-approval queue.

        Has no database-level prefilter (see this module's docstring) —
        every pending stage assigned to the caller is scored in Python
        and only those meeting ``_MIN_APPROVAL_SCORE`` are returned.
        """
        if identity.role not in (UserRole.APPROVER, UserRole.ADMIN):
            return []

        stages = self._approval_service.list_pending_approvals(
            identity, page=Page(size=MAX_PAGE_SIZE)
        ).items
        if not stages:
            return []

        titles = self._request_titles(
            [stage.request_id for stage in stages], company_id=identity.company_id
        )

        scored: list[SearchResultItem] = []
        for stage in stages:
            request_title = titles.get(stage.request_id, "")
            score = _fuzzy_score(query_text, stage.stage_name, request_title)
            if score < _MIN_APPROVAL_SCORE:
                continue
            display_title = request_title or stage.stage_name
            scored.append(
                SearchResultItem(
                    entity_type="approval",
                    id=stage.id,
                    title=display_title,
                    subtitle=f"Stage: {stage.stage_name}",
                    snippet=_highlight_snippet(display_title, query_text),
                    score=score,
                    created_at=stage.created_at,
                    request_id=stage.request_id,
                    stage=stage,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def _search_workflows(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search workflow definitions by request type.

        Per this feature's own scope note: every page that can display a
        workflow definition (``workflows.py``) is administrator-gated
        (``navigation.guard_role(identity, UserRole.ADMIN)``), even
        though ``WorkflowDefinitionService`` itself permits any
        authenticated caller to read *active* definitions. Returning a
        non-administrator a "workflow" result they could never open
        would be a dead end, so this defers entirely to
        ``search_definitions``'s existing active-only restriction for a
        non-administrator and simply accepts that, in practice, only an
        administrator will ever reach the page these results link to.
        """
        result = self._workflow_definition_service.search_definitions(
            identity, query_text, page=Page(size=limit)
        )
        return [
            SearchResultItem(
                entity_type="workflow",
                id=definition.id,
                title=f"{definition.request_type} (v{definition.version})",
                subtitle="Active" if definition.is_active else "Inactive",
                snippet=_highlight_snippet(definition.request_type, query_text),
                score=_fuzzy_score(query_text, definition.request_type),
                created_at=definition.created_at,
                request_type=definition.request_type,
            )
            for definition in result.items
        ]

    def _search_users(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search profiles by display name. Administrator-only (checked by the caller)."""
        try:
            result = self._profile_repo.search_by_name(
                query_text, company_id=identity.company_id, page=Page(size=limit)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return [
            SearchResultItem(
                entity_type="user",
                id=profile.id,
                title=profile.full_name,
                subtitle=(
                    f"{profile.role.value.title()}"
                    + (f" · {profile.department}" if profile.department else "")
                ),
                snippet=_highlight_snippet(profile.full_name, query_text),
                score=_fuzzy_score(query_text, profile.full_name),
                created_at=profile.created_at,
            )
            for profile in result.items
        ]

    def _search_comments(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search comment bodies, scoped to requests the caller may view."""
        request_ids = self._visible_request_ids(identity)
        if request_ids is not None and not request_ids:
            return []

        try:
            result = self._comment_repo.search(
                query_text, request_ids=request_ids, page=Page(size=limit)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        titles = self._request_titles(
            [comment.request_id for comment in result.items], company_id=identity.company_id
        )
        return [
            SearchResultItem(
                entity_type="comment",
                id=comment.id,
                title=titles.get(comment.request_id, "Comment"),
                subtitle="Comment",
                snippet=_highlight_snippet(comment.body, query_text),
                score=_fuzzy_score(query_text, comment.body),
                created_at=comment.created_at,
                request_id=comment.request_id,
            )
            for comment in result.items
        ]

    def _search_audit_entries(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search audit action codes, scoped to requests the caller may view."""
        request_ids = self._visible_request_ids(identity)
        if request_ids is not None and not request_ids:
            return []

        try:
            result = self._audit_repo.search(
                query_text, request_ids=request_ids, page=Page(size=limit)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        entries = result.items
        titles = self._request_titles(
            [entry.request_id for entry in entries if entry.request_id],
            company_id=identity.company_id,
        )
        resolve_actor = self._build_actor_name_resolver()

        items = []
        for entry in entries:
            action_label = entry.action.replace("_", " ").title()
            request_title = titles.get(entry.request_id, "") if entry.request_id else ""
            actor_name = resolve_actor(entry.actor_id)
            subtitle_parts = [part for part in (actor_name, request_title) if part]
            items.append(
                SearchResultItem(
                    entity_type="audit_entry",
                    id=entry.id,
                    title=action_label,
                    subtitle=" · ".join(subtitle_parts) if subtitle_parts else "System",
                    snippet=_highlight_snippet(action_label, query_text),
                    score=_fuzzy_score(query_text, entry.action, action_label),
                    created_at=entry.created_at,
                    request_id=entry.request_id,
                )
            )
        return items

    def _search_notifications(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search the caller's own notification messages.

        Scoped to ``identity.user_id`` only — a notification is, by
        definition, visible only to its own recipient, so there is no
        broader role-based visibility question to resolve here (unlike
        comment/audit/attachment search).
        """
        try:
            result = self._notification_repo.search_for_recipient(
                query_text, identity.user_id, page=Page(size=limit)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return [
            SearchResultItem(
                entity_type="notification",
                id=notification.id,
                title=notification.message,
                subtitle=(
                    f"{notification.notification_type.value.title()}"
                    + ("" if notification.is_read else " · Unread")
                ),
                snippet=_highlight_snippet(notification.message, query_text),
                score=_fuzzy_score(query_text, notification.message),
                created_at=notification.created_at,
                request_id=notification.request_id,
            )
            for notification in result.items
        ]

    def _search_attachments(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search attachment filenames, scoped to requests the caller may view."""
        request_ids = self._visible_request_ids(identity)
        if request_ids is not None and not request_ids:
            return []

        try:
            result = self._attachment_repo.search(
                query_text, request_ids=request_ids, page=Page(size=limit)
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return [
            SearchResultItem(
                entity_type="attachment",
                id=attachment.id,
                title=attachment.file_name,
                subtitle=attachment.content_type,
                snippet=_highlight_snippet(attachment.file_name, query_text),
                score=_fuzzy_score(query_text, attachment.file_name),
                created_at=attachment.created_at,
                request_id=attachment.request_id,
            )
            for attachment in result.items
        ]

    def _search_departments(
        self, identity: AuthenticatedIdentity, query_text: str, limit: int
    ) -> list[SearchResultItem]:
        """Search distinct department names. Administrator-only (checked by the caller).

        There is no ``departments`` table (confirmed by
        ``admin_departments.py``'s own audit note) — a department is a
        free-text string on ``Profile``, aggregated at request time.
        Reuses ``fetch_all_profiles``/``group_profiles_by_department``
        directly rather than re-implementing their "page through
        ``list_by_role`` for all three roles" composition loop.
        """
        profiles = fetch_all_profiles(self._profile_repo, company_id=identity.company_id)
        grouped = group_profiles_by_department(profiles)

        scored: list[SearchResultItem] = []
        for department_name, by_role in grouped.items():
            score = _fuzzy_score(query_text, department_name)
            if score < _MIN_APPROVAL_SCORE:
                continue
            member_count = sum(by_role.values())
            most_recent = max(
                (
                    p.created_at
                    for p in profiles
                    if (p.department or UNASSIGNED_DEPARTMENT) == department_name
                ),
                default=None,
            )
            scored.append(
                SearchResultItem(
                    entity_type="department",
                    id=uuid.uuid5(uuid.NAMESPACE_OID, department_name),
                    title=department_name,
                    subtitle=f"{member_count} member{'s' if member_count != 1 else ''}",
                    snippet=_highlight_snippet(department_name, query_text),
                    score=score,
                    created_at=most_recent or datetime.min.replace(tzinfo=UTC),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def _build_actor_name_resolver(self) -> Callable[[UUID | None], str | None]:
        """Return a callable resolving a profile id to its display name, memoized per call site.

        Duplicates the same small, memoized-lookup shape
        ``RequestService._build_profile_name_resolver`` already uses,
        consistent with this codebase's convention of not sharing a
        two-line helper across services.
        """
        cache: dict[UUID, str | None] = {}

        def _resolve(profile_id: UUID | None) -> str | None:
            if profile_id is None:
                return None
            if profile_id not in cache:
                try:
                    cache[profile_id] = self._profile_repo.get_by_id(profile_id).full_name
                except RecordNotFoundError:
                    cache[profile_id] = None
            return cache[profile_id]

        return _resolve

    def list_saved_filters(self, identity: AuthenticatedIdentity) -> list[SavedFilter]:
        """List the caller's own saved searches.

        Args:
            identity: The authenticated caller.

        Returns:
            The caller's saved filters, most recently updated first.
        """
        records = self._saved_filter_repo.list_for_user(
            identity.user_id, company_id=identity.company_id
        )
        return [
            SavedFilter(
                id=record.id,
                user_id=record.user_id,
                name=record.name,
                query_text=record.query_text,
                entity_types=record.entity_types,
                filters=record.filters,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]

    def save_filter(
        self,
        identity: AuthenticatedIdentity,
        *,
        name: str,
        query_text: str,
        entity_types: Sequence[str] | None = None,
        filters: dict[str, object] | None = None,
    ) -> SavedFilter:
        """Save a named, reusable search for the caller.

        Args:
            identity: The authenticated caller.
            name: The filter's display name (unique per user).
            query_text: The free-text query to save.
            entity_types: The entity-type restriction to save, if any.
            filters: The advanced-filter payload to save, if any.

        Returns:
            The newly created ``SavedFilter``.

        Raises:
            ValidationError: If ``name`` is empty or whitespace-only, or
                if the caller already has a saved filter with this name
                (a unique-constraint violation, translated the same way
                as every other repository-level constraint failure in
                this codebase).
        """
        if not name or not name.strip():
            raise ValidationError("Saved filter name must not be empty.")
        try:
            record = self._saved_filter_repo.create(
                user_id=identity.user_id,
                company_id=identity.company_id,
                name=name.strip(),
                query_text=query_text,
                entity_types=list(entity_types) if entity_types is not None else None,
                filters=dict(filters) if filters is not None else {},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return SavedFilter(
            id=record.id,
            user_id=record.user_id,
            name=record.name,
            query_text=record.query_text,
            entity_types=record.entity_types,
            filters=record.filters,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def delete_saved_filter(self, identity: AuthenticatedIdentity, filter_id: UUID) -> None:
        """Delete one of the caller's own saved filters.

        Args:
            identity: The authenticated caller.
            filter_id: The saved filter's ``id``.

        Raises:
            NotFoundError: If no saved filter with this id exists for
                this caller (deliberately indistinguishable from "it
                belongs to someone else" — ownership is enforced by the
                repository's own delete predicate, not a separate
                lookup-then-authorize step).
        """
        try:
            self._saved_filter_repo.delete(filter_id, user_id=identity.user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

    def list_recent_searches(
        self, identity: AuthenticatedIdentity, *, limit: int = 10
    ) -> list[SearchHistoryEntry]:
        """List the caller's own recent, de-duplicated search queries.

        Args:
            identity: The authenticated caller.
            limit: The maximum number of distinct queries to return.

        Returns:
            Up to ``limit`` of the caller's most recent distinct
            searches, newest first — also used by the frontend as
            "search suggestions."
        """
        records = self._search_history_repo.list_recent(
            identity.user_id, company_id=identity.company_id, limit=limit
        )
        return [
            SearchHistoryEntry(
                id=record.id,
                user_id=record.user_id,
                query_text=record.query_text,
                entity_types=record.entity_types,
                result_count=record.result_count,
                created_at=record.created_at,
            )
            for record in records
        ]

    def clear_search_history(self, identity: AuthenticatedIdentity) -> None:
        """Delete every one of the caller's own search-history entries.

        Args:
            identity: The authenticated caller.
        """
        self._search_history_repo.clear_for_user(identity.user_id)
