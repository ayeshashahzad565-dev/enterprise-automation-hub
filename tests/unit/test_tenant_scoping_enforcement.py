"""Automated, CI-enforced checks backing this codebase's tenant-isolation
architecture (see docs/tenant_isolation.md). These are the mechanical half
of "defense in depth": rather than relying on convention or a docstring
someone might not read, each check below fails the build outright if a
future change quietly reintroduces the gap this architecture closed.

Three independent checks:
1. Every concrete repository must explicitly declare its client-scoping
   mode — enforced structurally (a required constructor kwarg), verified
   here so the failure mode is a named, readable test rather than an
   obscure ``TypeError`` deep in ``app.bootstrap``.
2. Every authenticated route must bind the per-request tenant-scoped
   client — otherwise a repository flipped to RLS enforcement would
   silently run on its service-role fallback for that route, with no
   error, just quietly weaker isolation than intended.
3. The company-wide list/search entry points on the repositories that
   stay on the service-role client must route through
   ``BaseRepository._scoped_query`` — the mandatory-tenant-filter helper —
   rather than a bare, droppable ``.eq("company_id", ...)`` call.
"""

from __future__ import annotations

import inspect

import fastapi.routing as fastapi_routing
import pytest

from app.api.dependencies import bind_tenant_database_client, get_current_identity
from app.api.main import create_app
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.attachment_repository import AttachmentRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.comment_repository import CommentRepository
from app.database.repositories.company_license_repository import CompanyLicenseRepository
from app.database.repositories.company_repository import CompanyRepository
from app.database.repositories.feature_flag_repository import FeatureFlagRepository
from app.database.repositories.invitation_repository import InvitationRepository
from app.database.repositories.job_repository import JobRepository
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.platform_stats_repository import PlatformStatsRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.saved_filter_repository import SavedFilterRepository
from app.database.repositories.search_history_repository import SearchHistoryRepository
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)

pytestmark = pytest.mark.unit

_ALL_CONCRETE_REPOSITORIES = [
    RequestRepository,
    CommentRepository,
    AttachmentRepository,
    ApprovalRepository,
    AnalyticsRepository,
    AuditRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    FeatureFlagRepository,
    JobRepository,
    CompanyRepository,
    CompanyLicenseRepository,
    ProfileRepository,
    InvitationRepository,
    SearchHistoryRepository,
    SavedFilterRepository,
    PlatformStatsRepository,
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
]


class TestEveryRepositoryDeclaresItsClientScopingMode:
    @pytest.mark.parametrize("repo_cls", _ALL_CONCRETE_REPOSITORIES, ids=lambda c: c.__name__)
    def test_always_use_injected_client_is_a_required_keyword_only_argument(self, repo_cls) -> None:
        parameter = inspect.signature(repo_cls.__init__).parameters.get("always_use_injected_client")
        assert parameter is not None, (
            f"{repo_cls.__name__}.__init__ must accept 'always_use_injected_client' explicitly."
        )
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{repo_cls.__name__}'s 'always_use_injected_client' must be keyword-only, "
            "so a positional call can never set it by accident."
        )
        assert parameter.default is inspect.Parameter.empty, (
            f"{repo_cls.__name__}'s 'always_use_injected_client' must have no default — a future "
            "repository must make a conscious choice, never silently inherit one."
        )

    def test_every_concrete_repository_in_the_package_is_covered_by_this_list(self) -> None:
        """Guards against this test file itself going stale: if a new
        repository module is added under app.database.repositories without
        also adding it to ``_ALL_CONCRETE_REPOSITORIES`` above, this fails
        loudly instead of the new class silently going unchecked."""
        import pkgutil

        import app.database.repositories as repositories_package
        from app.database.repositories.base_repository import BaseRepository

        covered_names = {cls.__name__ for cls in _ALL_CONCRETE_REPOSITORIES}
        found_names: set[str] = set()
        for module_info in pkgutil.iter_modules(repositories_package.__path__):
            if module_info.name == "base_repository":
                continue
            module = __import__(
                f"app.database.repositories.{module_info.name}", fromlist=["*"]
            )
            for attr in vars(module).values():
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, BaseRepository)
                    and attr is not BaseRepository
                    and attr.__module__ == module.__name__
                ):
                    found_names.add(attr.__name__)
        missing = found_names - covered_names
        assert not missing, (
            f"New repositor{'y' if len(missing) == 1 else 'ies'} not covered by this test's "
            f"repository list: {sorted(missing)}. Add them to _ALL_CONCRETE_REPOSITORIES above."
        )


#: Paths that must always be reachable without authentication, regardless
#: of environment (health checks are probed by orchestrators before any
#: credential exists; the invitation-validate/accept pair is how a brand
#: new user, who by definition has no account yet, joins a company).
#: ``GET /metrics`` is deliberately excluded from this fixed set: it's only
#: mounted when ``METRICS_ENABLED`` is truthy (see
#: ``app.api.main._metrics_enabled``), so asserting its presence here would
#: make this test depend on an environment variable no other test in this
#: file touches. It's still checked below, conditionally, when it shows up.
_ALWAYS_PUBLIC_ROUTE_PATHS = frozenset(
    {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/health",
        "/api/v1/invitations/validate",
        "/api/v1/invitations/accept",
    }
)

#: A conservative floor, well below the current real count (111 as of this
#: writing), on how many authenticated routes this traversal must find.
#: Its only job is to fail loudly if route flattening itself silently stops
#: working again in some *other* way than the one fixed here — e.g. a
#: future FastAPI release renames ``iter_route_contexts`` or changes what
#: it yields — rather than reproducing the original bug's failure mode,
#: where the traversal quietly examined zero real routes and every
#: assertion about "no unbound routes" passed vacuously.
_MINIMUM_EXPECTED_AUTHENTICATED_ROUTES = 50


class TestEveryAuthenticatedRouteBindsTheTenantScopedClient:
    """Regression coverage for a real bug in this test file itself: FastAPI
    changed how ``include_router``-mounted sub-routers are represented on
    ``app.routes``. Concrete ``APIRoute`` objects (which carry the
    ``.dependant`` this traversal needs) are no longer spliced directly
    into the parent app's route list; each ``include_router`` call instead
    adds one opaque ``fastapi.routing._IncludedRouter`` wrapper, which has
    neither ``.path`` nor ``.dependant`` of its own — the real routes live
    several levels deeper, inside ``wrapper.original_router.routes``, and
    that nesting can recurse arbitrarily (a router that includes routers).

    The previous version of this file walked ``app.routes`` one level deep
    and skipped anything without a ``.dependant`` attribute. Because every
    substantive route in this app arrives via ``app.include_router(...)``
    (see ``app.api.main``), that previous traversal examined precisely
    zero real endpoints — every route it saw was either a docs/OpenAPI
    ``Route`` with no ``.dependant``, or an ``_IncludedRouter`` wrapper
    with no ``.dependant``. With nothing to examine, the "no unbound
    routes" assertion held on an empty list and passed — not because
    tenant binding was verified, but because there was nothing left to
    check. That's precisely why the module docstring's second bullet is
    "Every authenticated route must bind the per-request tenant-scoped
    client": that guarantee had silently stopped being enforced.

    The one test that *should* have caught this
    (``test_the_deliberately_public_routes_do_not_resolve_identity_at_all``,
    below) did catch it: it asserted the public health routes show up on
    the "no identity resolved" side, which requires the traversal to see
    at least one route with a ``.dependant`` — with the traversal
    examining nothing, that set was empty and the assertion failed. That
    failure is what surfaced this bug; it was never a false negative, just
    a symptom appearing on the canary test rather than the main one.

    Both tests below now use ``fastapi.routing.iter_route_contexts``, the
    same routine FastAPI's own OpenAPI generator (``get_openapi``) uses
    internally to flatten a route tree of arbitrary ``_IncludedRouter``
    nesting into concrete, attribute-complete route contexts. Since it's
    the mechanism FastAPI itself relies on to describe every real
    endpoint, a route this traversal misses is a route ``/api/docs`` would
    also misdescribe — making a future silent divergence far less likely
    than hand-rolling a second, parallel flattening routine here.
    """

    def test_no_route_resolves_identity_without_also_binding_the_tenant_client(self) -> None:
        app = create_app(resources_factory=lambda: None)  # never invoked; routes exist eagerly
        route_contexts = list(fastapi_routing.iter_route_contexts(app.routes))

        examined = 0
        authenticated = 0
        unbound_routes: list[str] = []
        for route_context in route_contexts:
            dependant = getattr(route_context, "dependant", None)
            if dependant is None:
                continue
            examined += 1
            calls = _collect_dependency_calls(dependant)
            if get_current_identity not in calls:
                continue
            authenticated += 1
            if bind_tenant_database_client not in calls:
                methods = sorted(route_context.methods or [])
                unbound_routes.append(f"{methods} {route_context.path}")

        # Guards against this test regressing to its original failure mode:
        # if route flattening ever silently breaks again, `examined`/
        # `authenticated` collapse to 0 and the assertion below would pass
        # vacuously exactly like before, on an empty list, for a different
        # reason. Failing here instead turns that into a loud, specific
        # error instead of a false sense of security.
        assert examined >= _MINIMUM_EXPECTED_AUTHENTICATED_ROUTES, (
            f"Only found {examined} routes with resolvable dependency info out of "
            f"{len(route_contexts)} total route contexts — expected at least "
            f"{_MINIMUM_EXPECTED_AUTHENTICATED_ROUTES}. This traversal may be silently "
            "failing to see real routes again (see this class's docstring)."
        )
        assert authenticated >= _MINIMUM_EXPECTED_AUTHENTICATED_ROUTES, (
            f"Only found {authenticated} authenticated routes — expected at least "
            f"{_MINIMUM_EXPECTED_AUTHENTICATED_ROUTES}. This traversal may be silently "
            "failing to see real routes again (see this class's docstring)."
        )
        assert not unbound_routes, (
            "These routes resolve an authenticated identity but never bind the per-request "
            "tenant-scoped database client (app.api.main's _rate_limited dependency list is "
            "the usual place this is attached): " + ", ".join(unbound_routes)
        )

    def test_the_deliberately_public_routes_do_not_resolve_identity_at_all(self) -> None:
        """Sanity check that the test above isn't vacuously true — health,
        the public invitation routes, and (when enabled) metrics are
        genuinely unauthenticated, so they should appear only on the
        "identity not resolved" side, never the authenticated side."""
        app = create_app(resources_factory=lambda: None)
        route_contexts = list(fastapi_routing.iter_route_contexts(app.routes))

        public_paths: set[str] = set()
        authenticated_paths: set[str] = set()
        for route_context in route_contexts:
            dependant = getattr(route_context, "dependant", None)
            if dependant is None:
                continue
            path = route_context.path
            if path is None:
                continue
            if get_current_identity in _collect_dependency_calls(dependant):
                authenticated_paths.add(path)
            else:
                public_paths.add(path)

        # Same anti-vacuousness guard as the sibling test above, phrased in
        # terms of this test's own data: if flattening silently breaks,
        # both sets collapse towards empty and every assertion below would
        # otherwise pass (or fail) for the wrong reason.
        assert public_paths, "Found zero public routes — route flattening may be broken again."
        assert public_paths >= _ALWAYS_PUBLIC_ROUTE_PATHS, (
            f"Expected these always-public routes to resolve no identity: "
            f"{sorted(_ALWAYS_PUBLIC_ROUTE_PATHS - public_paths)}"
        )
        assert _ALWAYS_PUBLIC_ROUTE_PATHS.isdisjoint(authenticated_paths), (
            f"These routes are expected to be public but are resolving an authenticated "
            f"identity: {sorted(_ALWAYS_PUBLIC_ROUTE_PATHS & authenticated_paths)}"
        )
        if "/metrics" in public_paths | authenticated_paths:
            assert "/metrics" in public_paths, "GET /metrics must not require authentication."


def _collect_dependency_calls(dependant) -> set:
    calls = {dependant.call}
    for sub_dependant in dependant.dependencies:
        calls |= _collect_dependency_calls(sub_dependant)
    return calls


class TestCompanyWideListMethodsUseTheMandatoryScopedQueryHelper:
    """Targeted, per-method source checks — not a blanket file-wide AST
    sweep — since these files also contain plenty of methods correctly
    scoped by a different, non-company axis (request_id, recipient_id,
    a single row's own id), which a blanket sweep would false-positive on.
    Each entry below is a company-wide listing/search entry point on a
    repository that stays on the service-role client."""

    @pytest.mark.parametrize(
        ("repo_cls", "method_name"),
        [
            (RequestRepository, "list_requests"),
            (RequestRepository, "search_requests"),
            (ApprovalRepository, "list_pending_for_approver"),
            (ApprovalRepository, "list_overdue_stages"),
            (WorkflowStageRepository, "list_decided"),
            (AuditRepository, "list_all"),
            (InvitationRepository, "list_invitations"),
            (InvitationRepository, "find_pending_by_email"),
        ],
        ids=lambda v: getattr(v, "__name__", v),
    )
    def test_method_routes_through_scoped_query(self, repo_cls, method_name: str) -> None:
        source = inspect.getsource(getattr(repo_cls, method_name))
        assert "_scoped_query" in source, (
            f"{repo_cls.__name__}.{method_name} takes a company-wide company_id filter but does "
            "not call self._scoped_query(...) — a bare .eq('company_id', ...) can be silently "
            "dropped in a future edit; _scoped_query cannot."
        )

    @pytest.mark.parametrize(
        ("repo_cls", "method_name"),
        [
            (ApprovalRepository, "list_overdue_stages_all_companies"),
            (AuditRepository, "list_platform_wide"),
        ],
        ids=lambda v: getattr(v, "__name__", v),
    )
    def test_deliberately_cross_tenant_methods_are_explicitly_marked(
        self, repo_cls, method_name: str
    ) -> None:
        source = inspect.getsource(getattr(repo_cls, method_name))
        assert "tenant-scope-exempt" in source, (
            f"{repo_cls.__name__}.{method_name} is a deliberate cross-tenant read but is missing "
            "its '# tenant-scope-exempt: <reason>' marker comment."
        )
